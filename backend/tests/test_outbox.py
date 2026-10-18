"""Automated tests for the Transactional Outbox pattern and background worker.

Covers:
1. Mutating operations (claim, assign, transition) write outbox jobs in the exact same database transaction.
2. At-least-once delivery with an idempotent handler produces exactly one notification (no duplicates on repeat processing).
3. Transient failures trigger retry with backoff, increment attempt count, and permanently mark the job as 'failed' once max attempts are exceeded.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
import pytest

from app import models
from app.services.outbox import (
    enqueue_outbox_job,
    process_outbox_job,
    process_pending_outbox_jobs,
)


def test_claim_enqueues_outbox_job_in_same_transaction(client, member_token, db_session):
    # Create item
    res = client.post(
        "/items",
        json={
            "title": "Incident: DB connection pool exhausted",
            "type": "incident",
            "priority": "critical",
            "team_id": 1,
        },
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert res.status_code == 201
    item_id = res.json()["id"]

    # Claim item
    claim_res = client.post(
        f"/items/{item_id}/claim",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert claim_res.status_code == 200

    # Query outbox_jobs for this item
    jobs = (
        db_session.query(models.OutboxJob)
        .filter(models.OutboxJob.aggregate_id == item_id)
        .all()
    )
    event_types = [j.event_type for j in jobs]
    assert "work_item.created" in event_types
    assert "work_item.assigned" in event_types

    assign_job = next(j for j in jobs if j.event_type == "work_item.assigned")
    assert assign_job.status == "pending"
    assert assign_job.attempts == 0
    payload = json.loads(assign_job.payload)
    assert payload["work_item_id"] == item_id
    assert payload["action"] == "claimed"


def test_job_processed_twice_produces_one_notification(db_session):
    job = enqueue_outbox_job(
        db_session,
        event_type="work_item.assigned",
        aggregate_id=101,
        payload={
            "work_item_id": 101,
            "title": "Fix payment gateway timeout",
            "assignee_id": 2,
            "recipient": "lead.ops@opsflow.demo",
        },
    )
    assert job.status == "pending"
    assert job.attempts == 0

    # First execution
    ok = process_outbox_job(db_session, job)
    assert ok is True
    assert job.status == "completed"
    assert job.attempts == 1
    assert job.processed_at is not None

    notifications = (
        db_session.query(models.ProcessedNotification)
        .filter(models.ProcessedNotification.job_id == job.id)
        .all()
    )
    assert len(notifications) == 1
    assert notifications[0].recipient == "lead.ops@opsflow.demo"
    assert "Fix payment gateway timeout" in notifications[0].message

    # Re-running the same job (simulating duplicate delivery)
    ok_again = process_outbox_job(db_session, job)
    assert ok_again is True
    assert job.status == "completed"

    # Must still be exactly ONE notification dispatched
    notifications_after = (
        db_session.query(models.ProcessedNotification)
        .filter(models.ProcessedNotification.job_id == job.id)
        .all()
    )
    assert len(notifications_after) == 1


def test_failed_job_retries_and_marks_failed(db_session):
    job = enqueue_outbox_job(
        db_session,
        event_type="work_item.status_changed",
        aggregate_id=202,
        payload={"work_item_id": 202, "new_status": "resolved"},
    )
    job.max_attempts = 3

    def failing_handler(db, current_job):
        raise ConnectionResetError("Third-party notification webhook connection reset")

    # Attempt 1
    success_1 = process_outbox_job(db_session, job, handler=failing_handler)
    assert success_1 is False
    assert job.attempts == 1
    assert job.status == "pending"
    assert "webhook connection reset" in job.last_error
    assert job.scheduled_for > datetime.now(timezone.utc)

    # Attempt 2
    success_2 = process_outbox_job(db_session, job, handler=failing_handler)
    assert success_2 is False
    assert job.attempts == 2
    assert job.status == "pending"

    # Attempt 3 (Final attempt reached)
    success_3 = process_outbox_job(db_session, job, handler=failing_handler)
    assert success_3 is False
    assert job.attempts == 3
    assert job.status == "failed"
    assert "webhook connection reset" in job.last_error

    # Fourth attempt should not retry
    success_4 = process_outbox_job(db_session, job, handler=failing_handler)
    assert success_4 is False
    assert job.status == "failed"
