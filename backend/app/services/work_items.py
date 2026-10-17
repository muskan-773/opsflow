"""Work-item service: the concurrency-critical business logic.

All mutating paths use atomic SQL ``UPDATE ... WHERE <guard> RETURNING`` and
write the activity event in the same transaction. The HTTP layer commits via
the ``get_db`` dependency; this service only ``flush``es so it stays inside
the caller's transaction.
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import or_, select, update, func
from sqlalchemy.orm import Session

from .. import models, schemas
from ..activity import record_event
from ..idempotency import store as store_idempotency, request_hash_matches, get_existing
from .outbox import enqueue_outbox_job
from ..permissions import (
    assert_can_approve,
    assert_can_assign,
    assert_can_create,
    assert_can_edit,
    assert_can_read,
    assert_can_transition,
    assert_team_member,
    role_for_team,
    visible_team_ids,
)

# Workflow state transition map: (from_status, to_status) -> allowed roles
TRANSITIONS: dict[tuple[str, str], set[str]] = {
    ("open", "in_progress"): {"member", "lead", "admin"},
    ("in_progress", "awaiting_approval"): {"member", "lead", "admin"},
    ("awaiting_approval", "resolved"): {"lead", "admin"},      # approval
    ("awaiting_approval", "in_progress"): {"lead", "admin"},   # reject / send back
    ("resolved", "closed"): {"lead", "admin"},
    ("resolved", "in_progress"): {"lead", "admin"},           # reopen
}



def _enrich(item: models.WorkItem, db: Session) -> models.WorkItem:
    """Attach names used by WorkItemOut without changing the row."""
    # Names are read-only lookups; not part of the persisted row.
    if item.team_id is not None:
        item.team_name = _name(db, models.Team, item.team_id)
    item.creator_name = _name(db, models.User, item.creator_id)
    item.assignee_name = _name(db, models.User, item.assignee_id) if item.assignee_id else None
    return item


def _name(db: Session, model, pk: Optional[int]) -> Optional[str]:
    if pk is None:
        return None
    row = db.query(model).filter(model.id == pk).with_entities(model.name if hasattr(model, "name") else None).first()
    # teams have 'name'; users have 'name'
    obj = db.get(model, pk)
    if obj is None:
        return None
    return getattr(obj, "name", None)


def create_work_item(
    db: Session,
    payload: schemas.WorkItemCreate,
    user: models.User,
    idempotency_key: Optional[str] = None,
    raw_body: Optional[bytes] = None,
) -> schemas.WorkItemOut:
    """Create a work item, with optional idempotency.

    Enforces: user must be able to create in the target team; assignee (if
    given) must be a member of that team.
    """
    # Idempotency replay check
    if idempotency_key:
        existing = get_existing(db, idempotency_key, user.id)
        if existing is not None:
            if not request_hash_matches(existing, raw_body):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Idempotency key was already used with a different request body.",
                )
            return _replay(existing)

    role = assert_can_create(user, payload.team_id)

    # Validate assignee is a member of the team (if provided).
    if payload.assignee_id is not None:
        _assert_user_in_team(db, payload.assignee_id, payload.team_id)

    item = models.WorkItem(
        title=payload.title,
        description=payload.description,
        type=payload.type.value,
        priority=payload.priority.value,
        status=schemas.WorkItemStatus.open.value,
        team_id=payload.team_id,
        assignee_id=payload.assignee_id,
        creator_id=user.id,
        due_date=payload.due_date,
        version=1,
    )
    db.add(item)
    db.flush()  # get id, stay in transaction

    record_event(db, item.id, user.id, "created", field="status", old_value=None, new_value="open")
    enqueue_outbox_job(
        db,
        event_type="work_item.created",
        aggregate_id=item.id,
        payload={
            "work_item_id": item.id,
            "title": item.title,
            "team_id": item.team_id,
            "creator_id": user.id,
            "assignee_id": item.assignee_id,
        },
    )

    if item.assignee_id is not None:
        record_event(
            db, item.id, user.id, "assigned", field="assignee", old_value=None, new_value=item.assignee_id
        )
        enqueue_outbox_job(
            db,
            event_type="work_item.assigned",
            aggregate_id=item.id,
            payload={
                "work_item_id": item.id,
                "title": item.title,
                "team_id": item.team_id,
                "assignee_id": item.assignee_id,
            },
        )

    out = _to_out(_enrich(item, db))

    # Persist idempotency key and canonical response in the same transaction
    if idempotency_key:
        store_idempotency(
            db,
            idempotency_key,
            user.id,
            raw_body,
            json.dumps(out.model_dump(mode="json")),
            status.HTTP_201_CREATED,
        )
    return out


def _replay(record: models.IdempotencyKey) -> schemas.WorkItemOut:
    """Return the stored response for a repeated idempotency key."""
    data = json.loads(record.response_body)
    out = schemas.WorkItemOut.model_validate(data)
    # Tag the replay so the route can set the stored status code.
    out.__dict__["_replayed"] = True
    out.__dict__["_stored_status"] = record.status_code
    return out


def _to_out(item: models.WorkItem) -> schemas.WorkItemOut:
    data = {
        "id": item.id,
        "title": item.title,
        "description": item.description,
        "type": item.type,
        "priority": item.priority,
        "status": item.status,
        "team_id": item.team_id,
        "team_name": getattr(item, "team_name", None),
        "assignee_id": item.assignee_id,
        "assignee_name": getattr(item, "assignee_name", None),
        "creator_id": item.creator_id,
        "creator_name": getattr(item, "creator_name", None),
        "due_date": item.due_date,
        "version": item.version,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }
    return schemas.WorkItemOut.model_validate(data)


# Listing with server-side filter, search, pagination
def list_work_items(
    db: Session,
    user: models.User,
    *,
    status_filter: Optional[str] = None,
    priority: Optional[str] = None,
    assignee_id: Optional[int] = None,
    team_id: Optional[int] = None,
    q: Optional[str] = None,
    page: int = 1,
    size: int = 20,
) -> schemas.WorkItemListResponse:
    if page < 1:
        page = 1
    if size < 1 or size > 100:
        size = 20

    teams = visible_team_ids(user, db)
    if not teams:
        return schemas.WorkItemListResponse(items=[], meta=schemas.WorkItemListMeta(total=0, page=page, size=size, pages=0))

    stmt = select(models.WorkItem).where(models.WorkItem.team_id.in_(teams))

    if status_filter:
        stmt = stmt.where(models.WorkItem.status == status_filter)
    if priority:
        stmt = stmt.where(models.WorkItem.priority == priority)
    if assignee_id is not None:
        stmt = stmt.where(models.WorkItem.assignee_id == assignee_id)
    if team_id is not None:
        if team_id not in teams:
            # user cannot view a team they're not on
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not a member of that team.")
        stmt = stmt.where(models.WorkItem.team_id == team_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(models.WorkItem.title.ilike(like), models.WorkItem.description.ilike(like)))

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    pages = (total + size - 1) // size if total else 0
    rows = db.execute(stmt.order_by(models.WorkItem.created_at.desc()).offset((page - 1) * size).limit(size)).scalars().all()

    items = [_to_out(_enrich(r, db)) for r in rows]
    return schemas.WorkItemListResponse(
        items=items,
        meta=schemas.WorkItemListMeta(total=total, page=page, size=size, pages=pages),
    )


def get_work_item_detail(
    db: Session, item_id: int, user: models.User
) -> schemas.WorkItemDetail:
    item = _get_or_404(db, item_id)
    assert_can_read(user, item.team_id)
    _enrich(item, db)

    comments = []
    for c in sorted(item.comments, key=lambda c: c.created_at):
        c.author_name = _name(db, models.User, c.author_id)
        comments.append(
            schemas.CommentOut(
                id=c.id,
                work_item_id=c.work_item_id,
                author_id=c.author_id,
                author_name=c.author_name,
                body=c.body,
                created_at=c.created_at,
            )
        )

    activity = []
    for e in sorted(item.activity, key=lambda e: e.created_at):
        e.actor_name = _name(db, models.User, e.actor_id) if e.actor_id else None
        activity.append(
            schemas.ActivityEventOut(
                id=e.id,
                work_item_id=e.work_item_id,
                actor_id=e.actor_id,
                actor_name=e.actor_name,
                event_type=e.event_type,
                field=e.field,
                old_value=e.old_value,
                new_value=e.new_value,
                created_at=e.created_at,
            )
        )

    return schemas.WorkItemDetail(
        **_to_out(item).model_dump(),
        comments=comments,
        activity=activity,
    )


def get_activity(
    db: Session, item_id: int, user: models.User, page: int = 1, size: int = 50
) -> list[schemas.ActivityEventOut]:
    item = _get_or_404(db, item_id)
    assert_can_read(user, item.team_id)
    if page < 1:
        page = 1
    if size < 1 or size > 200:
        size = 50
    rows = (
        db.query(models.ActivityEvent)
        .filter(models.ActivityEvent.work_item_id == item_id)
        .order_by(models.ActivityEvent.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    out = []
    for e in rows:
        out.append(
            schemas.ActivityEventOut(
                id=e.id,
                work_item_id=e.work_item_id,
                actor_id=e.actor_id,
                actor_name=_name(db, models.User, e.actor_id) if e.actor_id else None,
                event_type=e.event_type,
                field=e.field,
                old_value=e.old_value,
                new_value=e.new_value,
                created_at=e.created_at,
            )
        )
    return out


# Update with optimistic locking
def update_work_item(
    db: Session, item_id: int, payload: schemas.WorkItemUpdate, user: models.User
) -> schemas.WorkItemOut:
    """Edit a work item with optimistic locking.

    Uses an atomic conditional UPDATE keyed on (id, version). If 0 rows are
    updated we fetch the current row: 404 if it vanished, 409 if it exists but
    the version differs. The activity event is written in the same transaction.
    """
    # Pre-check authorization using the in-memory row (also used for 404/409).
    current = db.get(models.WorkItem, item_id)
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Work item not found.")
    assert_can_edit(user, current)

    changes = {}
    for field_name in ("title", "description", "type", "priority", "due_date"):
        value = getattr(payload, field_name)
        if value is not None:
            changes[field_name] = value.value if isinstance(value, schemas.WorkItemType) or isinstance(value, schemas.Priority) else value

    # Atomic conditional update on version.
    values = {**changes, "version": models.WorkItem.version + 1}
    result = db.execute(
        update(models.WorkItem)
        .where(models.WorkItem.id == item_id, models.WorkItem.version == payload.version)
        .values(**values)
    )
    if result.rowcount == 0:
        latest = db.get(models.WorkItem, item_id)
        if latest is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Work item not found.")
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Stale version: the item is now at version {latest.version}.",
            headers={"X-Current-Version": str(latest.version)},
        )

    # Refresh to reflect the incremented version and applied changes.
    db.refresh(current)
    for field_name, value in changes.items():
        record_event(
            db, item_id, user.id, "updated", field=field_name,
            old_value=None, new_value=str(value),
        )
    return _to_out(_enrich(current, db))


# Atomic claim
def claim_work_item(db: Session, item_id: int, user: models.User) -> schemas.WorkItemOut:
    """Atomically assign an unassigned item to the current user.

    Conditional UPDATE: only assigns if assignee_id IS NULL. Two concurrent
    claims race on the same row; the DB row lock guarantees exactly one
    UPDATE matches. The other gets 0 rows → 409.
    """
    item = _get_or_404(db, item_id)
    assert_can_create(user, item.team_id)  # viewer cannot claim

    result = db.execute(
        update(models.WorkItem)
        .where(models.WorkItem.id == item_id, models.WorkItem.assignee_id.is_(None))
        .values(assignee_id=user.id, version=models.WorkItem.version + 1)
    )
    if result.rowcount == 0:
        latest = db.get(models.WorkItem, item_id)
        who = "already assigned" if latest and latest.assignee_id else "no longer available"
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Could not claim: item is {who}.",
            headers={"X-Current-Version": str(latest.version) if latest else "0"},
        )

    db.refresh(item)
    record_event(
        db, item_id, user.id, "claimed", field="assignee",
        old_value=None, new_value=user.id,
    )
    enqueue_outbox_job(
        db,
        event_type="work_item.assigned",
        aggregate_id=item.id,
        payload={
            "work_item_id": item.id,
            "title": item.title,
            "team_id": item.team_id,
            "assignee_id": user.id,
            "action": "claimed",
        },
    )
    return _to_out(_enrich(item, db))


# Assign / reassign
def assign_work_item(
    db: Session, item_id: int, payload: schemas.WorkItemAssign, user: models.User
) -> schemas.WorkItemOut:
    item = _get_or_404(db, item_id)
    assert_can_assign(user, item.team_id)
    _assert_user_in_team(db, payload.assignee_id, item.team_id)

    old_assignee = item.assignee_id
    result = db.execute(
        update(models.WorkItem)
        .where(models.WorkItem.id == item_id, models.WorkItem.version == item.version)
        .values(assignee_id=payload.assignee_id, version=models.WorkItem.version + 1)
    )
    if result.rowcount == 0:
        latest = db.get(models.WorkItem, item_id)
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Stale version: item is now at version {latest.version}.",
        )

    db.refresh(item)
    record_event(
        db, item_id, user.id, "assigned", field="assignee",
        old_value=old_assignee, new_value=payload.assignee_id,
    )
    enqueue_outbox_job(
        db,
        event_type="work_item.assigned",
        aggregate_id=item.id,
        payload={
            "work_item_id": item.id,
            "title": item.title,
            "team_id": item.team_id,
            "assignee_id": payload.assignee_id,
            "action": "assigned",
        },
    )
    return _to_out(_enrich(item, db))


# Workflow transition
def transition_work_item(
    db: Session, item_id: int, payload: schemas.WorkItemTransition, user: models.User
) -> schemas.WorkItemOut:
    item = _get_or_404(db, item_id)
    role = assert_can_transition(user, item)

    target = payload.target_status.value
    key = (item.status, target)
    if key not in TRANSITIONS:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Transition '{item.status}' -> '{target}' is not allowed.",
        )

    allowed_roles = TRANSITIONS[key]
    if role not in allowed_roles:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail=f"Your role ('{role}') cannot make this transition.",
        )

    # Approval step: awaiting_approval -> resolved requires Lead/admin.
    if key == ("awaiting_approval", "resolved"):
        assert_can_approve(user, item)

    old_status = item.status
    result = db.execute(
        update(models.WorkItem)
        .where(models.WorkItem.id == item_id, models.WorkItem.version == item.version)
        .values(status=target, version=models.WorkItem.version + 1)
    )
    if result.rowcount == 0:
        latest = db.get(models.WorkItem, item_id)
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Stale version: item is now at version {latest.version}.",
        )

    db.refresh(item)
    event_type = {
        ("awaiting_approval", "resolved"): "approved",
        ("awaiting_approval", "in_progress"): "rejected",
    }.get(key, "status_changed")
    record_event(
        db, item_id, user.id, event_type, field="status",
        old_value=old_status, new_value=target,
    )
    enqueue_outbox_job(
        db,
        event_type=f"work_item.{event_type}",
        aggregate_id=item.id,
        payload={
            "work_item_id": item.id,
            "title": item.title,
            "team_id": item.team_id,
            "old_status": old_status,
            "new_status": target,
        },
    )
    return _to_out(_enrich(item, db))



# Comments
def add_comment(
    db: Session, item_id: int, payload: schemas.CommentCreate, user: models.User
) -> schemas.CommentOut:
    item = _get_or_404(db, item_id)
    assert_team_member(user, item.team_id)
    comment = models.Comment(work_item_id=item_id, author_id=user.id, body=payload.body)
    db.add(comment)
    db.flush()
    record_event(
        db, item_id, user.id, "commented", field="comment",
        old_value=None, new_value=comment.id,
    )
    return schemas.CommentOut(
        id=comment.id,
        work_item_id=comment.work_item_id,
        author_id=comment.author_id,
        author_name=user.name,
        body=comment.body,
        created_at=comment.created_at,
    )


# Internal helpers
def _get_or_404(db: Session, item_id: int) -> models.WorkItem:
    item = db.get(models.WorkItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Work item not found.")
    return item


def _assert_user_in_team(db: Session, user_id: int, team_id: int) -> None:
    exists = (
        db.query(models.Membership)
        .filter(models.Membership.user_id == user_id, models.Membership.team_id == team_id)
        .first()
    )
    if exists is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Assignee is not a member of the item's team.",
        )
