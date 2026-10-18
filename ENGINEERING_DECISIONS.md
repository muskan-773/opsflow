# Engineering Decisions

**Author:** Muskan Kumari  
**Project:** OpsFlow — Operations Under Pressure  
**Evaluation:** Newtonite Software Engineering Challenge  

This document explains the key engineering decisions made while building OpsFlow. For each decision, I describe the real-world operational context, the technical options considered, the rationale behind the chosen design, and the practical trade-offs accepted.

---

## 1. Concurrency Control: Optimistic Locking via Version Columns and Conditional Updates

### Context
In high-pressure operations, multiple operators often interact with the same work items simultaneously. If two operators read a ticket at the same time and both submit edits, a naive `UPDATE` causes the "lost update" problem, where the second write silently overwrites the first.

For task claiming, the race condition is even more critical: two operators seeing an unassigned urgent ticket might both click "Claim". If not handled atomically, both will believe they own the task, leading to duplicated effort or dropped responsibilities.

### Options Considered
1. **Pessimistic Locking (`SELECT ... FOR UPDATE`):** Holds database row-level locks for the entire duration of a transaction. While safe, holding locks during HTTP request lifecycles impairs concurrency, increases connection pool exhaustion risks, and creates deadlock potential under load.
2. **Distributed Application Locks (e.g. Redis Redlock):** Maintains locks outside PostgreSQL. This introduces external infrastructure dependencies, tricky lease expiration logic, and dual-state failure modes if the database write fails after the lock is acquired.
3. **Last-Writer-Wins (No Concurrency Guard):** Simplest to write, but fatal for operational integrity. Edits silently overwrite each other with no audit trail or conflict warning.
4. **Optimistic Locking via Integer Versioning (Chosen):** Tracks a `version` integer on each row. Every mutating `UPDATE` checks the version and increments it atomically.

### Chosen Approach
I implemented optimistic locking at the database query level:

*For work item updates:*
```sql
UPDATE work_items
SET title = :title, description = :description, version = version + 1, updated_at = NOW()
WHERE id = :id AND version = :client_version;
```
If `rowcount == 0`, the item has been modified by someone else since the client fetched it. The server immediately returns `HTTP 409 Conflict` along with the current version, prompting the client to reload the latest state before attempting further edits.

*For atomic claiming:*
```sql
UPDATE work_items
SET assignee_id = :user_id, version = version + 1, updated_at = NOW()
WHERE id = :id AND assignee_id IS NULL;
```
PostgreSQL's row-level lock ensures that even if two requests arrive in the exact same millisecond, only one transaction matches the `WHERE assignee_id IS NULL` clause. The loser gets 0 rows updated and receives a `409 Conflict`.

### Trade-offs
- Clients must include the `version` field in update payloads.
- Under extremely high contention on a single item, rejected clients must handle retries or reloads. For operational work items, this contention is intermittent and 409 feedback is far preferable to silent data loss.

---

## 2. Authorization Architecture: Centralized Server-Side Enforcement per Team and Role

### Context
Work items contain sensitive internal information (e.g., payment discrepancies, compliance violations, security incidents). Authorization cannot simply rely on the frontend hiding buttons; any user can invoke the API directly via cURL or Swagger. Furthermore, permissions must be team-scoped: a user might be a Lead in Customer Support but only a Viewer in Payments.

### Options Considered
1. **Route-Level Decorators/Middleware (`@require_role("lead")`):** Clean for simple apps, but fails when authorization depends on the resource's team (which is only known after loading the item or inspecting the request payload).
2. **Ad-hoc `if` Checks in Route Handlers:** Scattering checks across routes leads to duplicated logic, inconsistent error messages, and easy-to-miss security bugs when new endpoints are introduced.
3. **Centralized Policy Module (`app/permissions.py`) (Chosen):** A single module containing explicit, unit-testable assertions (`assert_can_create`, `assert_can_edit`, `assert_can_assign`, `assert_can_approve`).

### Chosen Approach
I created a join table `memberships(user_id, team_id, role)` where role is one of `viewer`, `member`, or `lead`. A global `is_admin` boolean on the `users` table provides superuser bypass.

Every business action calls the corresponding assertion function in `app/permissions.py`:
- `assert_can_read(user, team_id)`: Enforces team tenancy. Cross-team reads return `HTTP 403 Forbidden`.
- `assert_can_create(user, team_id)`: Viewers cannot create work items.
- `assert_can_edit(user, item)`: Members may only edit items they either created or are assigned to. Leads and Admins can edit any item in their team.
- `assert_can_assign(user, team_id)`: Assigning or reassigning items requires Lead or Admin privileges.
- `assert_can_approve(user, item)`: Moving an item from `awaiting_approval` to `resolved` is strictly reserved for Leads and Admins.

### Trade-offs
- Roles are verified in Python rather than in database row-level security (RLS) policies. This keeps our service logic explicit, readable, and easy to test with Pytest mocks without requiring custom Postgres functions.

---

## 3. Audit History & Consistency: Transactional Append-Only Activity Log

### Context
Operational accountability requires that every status transition, assignment, and priority change be recorded. If an auditor asks why an urgent payment ticket was closed, the system must show who approved it, who claimed it, and when. Crucially, the work item change and the activity record must never get out of sync.

### Options Considered
1. **Post-Commit Event Logging:** Writing the activity record in a background thread or after the HTTP transaction commits. If the application server crashes or restarts right after updating the item, the activity event is permanently lost, leaving the database state untraceable.
2. **Database Triggers:** Writing triggers in PL/pgSQL to insert into an audit table on every `UPDATE`. While reliable, triggers obscure business context (e.g., whether an update was an "approval" vs a "manual status edit") and complicate local testing and migrations.
3. **In-Transaction Domain Event Persistence (Chosen):** Inserting into `activity_events` within the exact same database transaction that updates `work_items`.

### Chosen Approach
The helper function `record_event(db, work_item_id, actor_id, event_type, ...)` executes `db.flush()` rather than `db.commit()`. The transaction boundary is owned by FastAPI's dependency injection (`get_db`). If any part of the service fails, the entire transaction rolls back cleanly. If it succeeds, the item update and the history record commit together atomically.

The `activity_events` table is append-only by design: there are no `UPDATE` or `DELETE` endpoints in the system.

### Trade-offs
- The `activity_events` table will grow faster than `work_items`. In production, this table would eventually require time-based table partitioning (e.g., partitioning by `created_at` month), which is straightforward to add in PostgreSQL.

---

## 4. Idempotency Guarantees: Request Hash Verification with Atomic Response Persistence

### Context
Under high network latency or flaky mobile connections, users frequently double-click "Submit" buttons, or clients automatically retry HTTP requests upon transient connection drops. Without idempotency protection on `POST /items`, each retry creates a duplicate incident, cluttering operations dashboards and splitting response efforts.

### Options Considered
1. **Frontend-Only Debouncing:** Disabling submit buttons after one click. This prevents simple double-clicks but provides zero protection against automated network retries, browser page refreshes, or script execution.
2. **Database Unique Constraints (e.g., unique on title + team):** Restrictive and incorrect: legitimate operational situations often require creating separate tickets with similar titles.
3. **Transactional Idempotency-Key Header (Chosen):** The client provides a unique `Idempotency-Key` header with mutation requests.

### Chosen Approach
When `POST /items` receives an `Idempotency-Key`:
1. The server queries `idempotency_keys` for that `(key, user_id)` pair.
2. If found, it compares the SHA-256 hash of the incoming request payload with the stored `request_hash`.
   - If the hashes match, it immediately returns the stored JSON response and HTTP status code without executing the create logic again.
   - If the hashes differ, it rejects the request with `HTTP 422 Unprocessable Content`, preventing accidental key collisions from masking different data.
3. If not found, it creates the work item, generates the canonical response, and writes the `IdempotencyKey` record in the **same database transaction**.

### Trade-offs
- Storing full serialized JSON responses consumes additional table storage.
- A periodic cleanup job is required in production to prune keys older than 24 hours.

---

## 5. Asynchronous Processing: Transactional Outbox Pattern with Retry Backoff

### Context
When a work item is claimed, assigned, or transitioned, downstream systems often need to be notified (e.g., notifying the new assignee, pinging a Slack channel, or updating an external compliance register).

Making external HTTP or SMTP calls synchronously during the client's request causes high API latency, couples our availability to external third parties, and risks inconsistency if the database commit succeeds but the external call fails (or vice versa).

### Options Considered
1. **In-Memory Background Tasks (e.g., FastAPI `BackgroundTasks`):** Runs tasks in the background after the response is sent. However, tasks reside entirely in server memory: if the server restarts or crashes, all pending notifications are permanently lost.
2. **Direct Queue Publication (e.g., publishing to RabbitMQ/Kafka inside the route):** Suffers from the "dual-write" problem: either the database commit fails after publishing the message (phantom message), or the message publish fails after the DB commit (lost message).
3. **Transactional Outbox Pattern (Chosen):** The application writes the event into an `outbox_jobs` table as part of the primary database transaction. A separate background worker reads the outbox, dispatches notifications, and handles failures with exponential backoff and consumer idempotency.

### Chosen Approach
I implemented the Transactional Outbox pattern with two tables:
- `outbox_jobs`: Stores `event_type`, `aggregate_id`, `payload`, `status` (`pending`, `completed`, `failed`), `attempts`, `max_attempts`, and `scheduled_for`.
- `processed_notifications`: Acts as an idempotency deduplication ledger so that at-least-once outbox delivery produces exactly-once notifications.

When an item is claimed or transitioned:
1. `enqueue_outbox_job` writes an event row inside the existing transaction.
2. The background worker (`backend/worker.py` or scheduled runner) queries pending jobs where `scheduled_for <= NOW()`.
3. If an error occurs, it records `last_error`, increments `attempts`, and calculates exponential backoff (`delay = 2 ** attempts` seconds) to update `scheduled_for`.
4. If `attempts >= max_attempts` (default 3), the job transitions permanently to `failed` for operator inspection.

### Trade-offs
- Slightly introduces a brief delay (polling interval of 1–2 seconds) before notifications are delivered, which is completely acceptable for operational workflows.

---

## 6. Optimistic UI Reconciliation: Instant Feedback with Automated Snapshot Rollback

### Context
In fast-paced triage, operators need immediate visual responsiveness when claiming tasks or changing statuses. Waiting 300ms for a network round-trip on every action makes the UI feel sluggish. However, if the UI simply updates and ignores server rejection, the operator operates on incorrect assumptions.

### Options Considered
1. **Pessimistic UI (Spinners on Every Action):** Blocks the interface until the server confirms the change. Safe, but degrades operator throughput.
2. **Naive Optimistic UI (No Rollback):** Updates the UI immediately and ignores or shows a tiny toast on failure, leaving the screen showing inaccurate state until a manual browser refresh.
3. **Optimistic Reconciliation with Snapshot Rollback (Chosen):** The UI immediately renders the expected state, but retains a shallow snapshot of the previous state. If the server returns a 409 Conflict or 403 Forbidden, the component immediately reverts to the snapshot and surfaces the server's explanation.

### Chosen Approach
In `frontend/src/pages/WorkItemDetailPage.jsx`:
- When clicking "Claim", the client snapshots `item`, immediately renders the current user as assignee, increments the local version, and disables the claim button.
- If the server confirms (200), the state is finalized and the activity timeline refreshes.
- If the server rejects with `409 Conflict` (another user claimed the item in the same second), the catch handler reverts `item` to the previous snapshot and displays:  
  `"Claim conflict: This item was already claimed or updated by another user. Reloading latest state..."`, followed by an automatic reload.
- For unauthorized transitions (403), the status badge immediately snaps back to its prior state with a clear permission alert.

### Trade-offs
- Component state logic must preserve and manage rollback snapshots.

---

## 7. Query Performance & Scale Awareness: Server-Side Pagination and Composite Indexes

### Context
An internal ops system easily accumulates tens of thousands of work items and hundreds of thousands of activity events over time. Fetching all items and filtering in JavaScript would crash browser tabs and exhaust server memory.

### Chosen Approach
1. **Server-Side Pagination:** The `/items` endpoint enforces `page` and `size` parameters (capped at 100), returning metadata (`total`, `page`, `size`, `pages`).
2. **Composite Indexes:**
   - `ix_work_items_status_priority` on `(status, priority)` to optimize urgent triage views.
   - `ix_work_items_team_assignee` on `(team_id, assignee_id)` for "Assigned to me" queries.
   - `ix_outbox_jobs_status_scheduled` on `(status, scheduled_for)` for the worker polling loop.
3. **Search Strategy:** For the current dataset size, SQL `ILIKE` on `title` and `description` provides flexible partial matching. For 10x scale, this would be replaced with a PostgreSQL `tsvector` GIN index.
