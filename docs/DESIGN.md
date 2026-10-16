# OpsFlow — Design & Architecture Notes

Operations Under Pressure: an internal operations management platform to create,
assign, track, approve, and resolve operational work items across teams.

## 1. Goals and Scope

Build one tight vertical slice that is provably correct under concurrency, enforces
real server-side authorization per team/resource, maintains a tamper-resistant
transactional activity log, and processes asynchronous jobs reliably.

### In Scope
- Seeded teams and demo users representing diverse roles (Admin, Lead, Member, Viewer).
- Work items with type (incident, customer issue, payment, compliance, task), priority,
  status, team scoping, assignee, creator, due date, version number, and timestamps.
- Controlled workflow state machine:
  `Open -> In Progress -> Awaiting Approval -> Resolved -> Closed`.
- Concurrency guarantees:
  - Atomic task claim (`WHERE assignee_id IS NULL`) preventing duplicate assignment.
  - Optimistic locking via integer `version` guarding against lost updates.
  - Idempotency key handling caching canonical responses for repeated requests.
- Server-enforced authorization:
  - Team membership and role check in a single service function (`permissions.py`).
  - Viewers are read-only; Members can create, claim, and edit own items; Leads/Admins can assign, reassign, and approve.
- Transactional audit log:
  - Append-only `activity_events` committed in the exact same DB transaction as item mutations.
- Reliable asynchronous processing:
  - Transactional Outbox pattern (`outbox_jobs`) capturing events with change transactions.
  - Asynchronous background worker with exponential backoff and idempotent handling (`processed_notifications`).
- Optimistic UI reconciliation:
  - Immediate local state transition with automated snapshot rollback upon 409/403 HTTP rejection.

### Deliberately Out of Scope
- External SMTP gateway integration (simulated via outbox notifications table).
- SSO / SAML authentication providers.
- Realtime WebSocket push (client refetch / polling is sufficient).
- Arbitrary binary file attachments.

---

## 2. Roles and Permissions Matrix

Roles are scoped per team in the `memberships` table (`user_id`, `team_id`, `role`).
Global admins (`user.is_admin = True`) bypass team scoping with lead-level authority across all teams.

| Action | Viewer | Member | Lead | Admin |
|--------|:------:|:------:|:----:|:-----:|
| Read items (own team) | Yes | Yes | Yes | Yes |
| Create work item | No | Yes | Yes | Yes |
| Edit work item | No | Own only* | Yes | Yes |
| Claim unassigned item | No | Yes | Yes | Yes |
| Assign / reassign item | No | No | Yes | Yes |
| Workflow transition (standard) | No | Yes | Yes | Yes |
| Approve / reject (Awaiting Approval) | No | No | Yes | Yes |
| Add comment | No | Yes | Yes | Yes |

\* Members can only edit items they created or are assigned to.

---

## 3. Workflow State Machine

```
Open  ──────>  In Progress  ──────>  Awaiting Approval  ──────>  Resolved  ──────>  Closed
                   ^                         |                      |
                   |                         v (reject)             v (reopen)
                   +─────────────────────────+                      |
                   |                                                |
                   +────────────────────────────────────────────────+
```

Allowed Transitions:
- `open` -> `in_progress` (Member, Lead, Admin)
- `in_progress` -> `awaiting_approval` (Member, Lead, Admin)
- `awaiting_approval` -> `resolved` (Lead, Admin only - Approval gate)
- `awaiting_approval` -> `in_progress` (Lead, Admin - Reject / Request changes)
- `resolved` -> `closed` (Lead, Admin)
- `resolved` -> `in_progress` (Lead, Admin - Reopen)

Any invalid jump or unauthorized role attempt returns HTTP 409 Conflict or 403 Forbidden.

---

## 4. Data Model

- **users**: `id`, `email` (unique), `name`, `password_hash`, `is_active`, `is_admin`, `created_at`.
- **teams**: `id`, `name` (unique), `description`, `created_at`.
- **memberships**: `id`, `user_id` (FK), `team_id` (FK), `role` (`lead` | `member` | `viewer`), `unique(user_id, team_id)`.
- **work_items**: `id`, `title`, `description`, `type`, `priority`, `status`, `team_id` (FK), `assignee_id` (FK nullable), `creator_id` (FK), `due_date`, `version` (int default 1), `created_at`, `updated_at`.
  - Composite indexes: `(status, priority)`, `(team_id, assignee_id)`.
- **comments**: `id`, `work_item_id` (FK), `author_id` (FK), `body`, `created_at`.
- **activity_events**: `id`, `work_item_id` (FK), `actor_id` (FK nullable), `event_type`, `field`, `old_value`, `new_value`, `created_at`. Append-only.
- **idempotency_keys**: `key` (PK), `user_id` (FK), `request_hash`, `response_body`, `status_code`, `created_at`.
- **outbox_jobs**: `id`, `event_type`, `aggregate_type`, `aggregate_id`, `payload`, `status` (`pending` | `processing` | `completed` | `failed`), `attempts`, `max_attempts`, `last_error`, `scheduled_for`, `processed_at`, `created_at`.
- **processed_notifications**: `id`, `job_id` (FK unique), `recipient`, `message`, `sent_at`.

---

## 5. Critical Behaviors & Edge Case Handling

1. **Atomic Claim**:
   `UPDATE work_items SET assignee_id = :uid, version = version + 1 WHERE id = :id AND assignee_id IS NULL;`
   If rowcount == 0, the row was claimed concurrently -> returns HTTP 409 Conflict.

2. **Optimistic Locking**:
   `UPDATE work_items SET ..., version = version + 1 WHERE id = :id AND version = :client_version;`
   If rowcount == 0, item was modified concurrently -> returns HTTP 409 Conflict with the current version header.

3. **Idempotency Key Validation**:
   `POST /items` accepts `Idempotency-Key` header.
   - If key exists and request body matches: replays cached JSON response.
   - If key exists but request body differs: rejects with HTTP 422 Unprocessable Content.
   - If new key: saves response inside the same database transaction as the create.

4. **Transactional Outbox & Worker**:
   - Mutations enqueue an event into `outbox_jobs` in the mutation's transaction.
   - The decoupled background worker polls `outbox_jobs`, invokes handlers with exponential backoff (`2 ** attempts` delay), and records to `processed_notifications` to enforce consumer idempotency.

5. **Optimistic UI Reconciliation**:
   - In React, user actions immediately update UI state and increment local version.
   - If server rejects with 409/403, UI rolls back instantaneously to snapshot state and renders a clear conflict banner.
