"""Activity-history helper.

Activity events are written inside the caller's transaction, so the change
and its history commit together or roll back together. Events are append-only
— this module only inserts, never updates or deletes.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from . import models


def record_event(
    db: Session,
    work_item_id: int,
    actor_id: Optional[int],
    event_type: str,
    field: Optional[str] = None,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
) -> models.ActivityEvent:
    """Insert one append-only activity event on ``db`` (not committed here)."""
    event = models.ActivityEvent(
        work_item_id=work_item_id,
        actor_id=actor_id,
        event_type=event_type,
        field=field,
        old_value=None if old_value is None else str(old_value),
        new_value=None if new_value is None else str(new_value),
    )
    db.add(event)
    db.flush()  # populate id; stay in caller's transaction
    return event
