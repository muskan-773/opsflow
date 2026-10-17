"""Transactional Outbox service for reliable asynchronous background processing.

Events (e.g. notifications for assignee or status change) are enqueued inside
the caller's transaction alongside the work item mutation. A background worker
subsequently picks up pending jobs, dispatches them with exponential backoff on
transient failure, and ensures idempotent handling to avoid duplicate side effects.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models


def enqueue_outbox_job(
    db: Session,
    event_type: str,
    aggregate_id: int,
    payload: dict,
    aggregate_type: str = "work_item",
) -> models.OutboxJob:
    """Insert an outbox job into the database inside the current transaction."""
    job = models.OutboxJob(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=json.dumps(payload, sort_keys=True),
        status="pending",
        attempts=0,
        max_attempts=3,
        scheduled_for=datetime.now(timezone.utc),
    )
    db.add(job)
    db.flush()
    return job


def default_notification_handler(db: Session, job: models.OutboxJob) -> None:
    """Simulates dispatching an external notification with consumer idempotency."""
    # Check if this job was already dispatched
    existing = db.query(models.ProcessedNotification).filter(
        models.ProcessedNotification.job_id == job.id
    ).first()
    if existing is not None:
        return

    payload = json.loads(job.payload)
    recipient = payload.get("recipient") or f"user-{payload.get('assignee_id', 'ops')}"
    message = (
        f"Event '{job.event_type}' for {job.aggregate_type} #{job.aggregate_id}: "
        f"{payload.get('title', 'Work item update')}"
    )

    record = models.ProcessedNotification(
        job_id=job.id,
        recipient=str(recipient),
        message=message,
        sent_at=datetime.now(timezone.utc),
    )
    db.add(record)
    db.flush()


def process_outbox_job(
    db: Session,
    job: models.OutboxJob,
    handler: Optional[Callable[[Session, models.OutboxJob], None]] = None,
) -> bool:
    """Process a single outbox job with retry backoff and idempotency protection."""
    if job.status == "completed":
        return True

    if job.attempts >= job.max_attempts:
        job.status = "failed"
        db.flush()
        return False

    dispatcher = handler or default_notification_handler

    try:
        job.attempts += 1
        dispatcher(db, job)
        job.status = "completed"
        job.processed_at = datetime.now(timezone.utc)
        job.last_error = None
        db.flush()
        return True
    except Exception as exc:
        job.last_error = str(exc)
        if job.attempts >= job.max_attempts:
            job.status = "failed"
        else:
            job.status = "pending"
            delay = 2 ** job.attempts  # exponential backoff: 2s, 4s, 8s...
            job.scheduled_for = datetime.now(timezone.utc) + timedelta(seconds=delay)
        db.flush()
        return False


def process_pending_outbox_jobs(
    db: Session,
    batch_size: int = 10,
    handler: Optional[Callable[[Session, models.OutboxJob], None]] = None,
) -> int:
    """Query and process pending outbox jobs that are ready for execution."""
    now = datetime.now(timezone.utc)
    stmt = (
        select(models.OutboxJob)
        .where(
            models.OutboxJob.status == "pending",
            models.OutboxJob.scheduled_for <= now,
        )
        .order_by(models.OutboxJob.created_at.asc())
        .limit(batch_size)
    )
    jobs = db.execute(stmt).scalars().all()

    processed_count = 0
    for job in jobs:
        if process_outbox_job(db, job, handler=handler):
            processed_count += 1

    return processed_count
