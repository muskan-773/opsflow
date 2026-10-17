"""Work-item routes.

Authorization is enforced inside the service layer for every protected
resource, so the safety does not depend on the frontend hiding buttons.
Optimistic-locking (version) and idempotency are surfaced here and handled
in the service.
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth import get_current_user
from ..database import get_db
from ..services import work_items as svc

router = APIRouter(tags=["work-items"])


def _stored_status(out: schemas.WorkItemOut) -> Optional[int]:
    return getattr(out, "_stored_status", None)


@router.get("/items", response_model=schemas.WorkItemListResponse)
def list_items(
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    assignee_id: Optional[int] = Query(None),
    team_id: Optional[int] = Query(None),
    q: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return svc.list_work_items(
        db, current_user,
        status_filter=status, priority=priority, assignee_id=assignee_id,
        team_id=team_id, q=q, page=page, size=size,
    )


@router.post("/items", response_model=schemas.WorkItemOut, status_code=status.HTTP_201_CREATED)
def create_item(
    payload: schemas.WorkItemCreate,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    raw_body: Optional[bytes] = Depends(lambda: None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    # We need the raw request body to compute a request hash for idempotency
    # mismatch detection. FastAPI has already parsed it into `payload`; we
    # reconstruct a stable canonical representation for hashing.
    body_bytes = json.dumps(payload.model_dump(mode="json"), sort_keys=True).encode() if idempotency_key else None
    out = svc.create_work_item(db, payload, current_user, idempotency_key, body_bytes)
    stored = _stored_status(out)
    if stored is not None:
        response.status_code = stored
    return out


@router.get("/items/{item_id}", response_model=schemas.WorkItemDetail)
def get_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return svc.get_work_item_detail(db, item_id, current_user)


@router.patch("/items/{item_id}", response_model=schemas.WorkItemOut)
def update_item(
    item_id: int,
    payload: schemas.WorkItemUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return svc.update_work_item(db, item_id, payload, current_user)


@router.post("/items/{item_id}/claim", response_model=schemas.WorkItemOut)
def claim_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return svc.claim_work_item(db, item_id, current_user)


@router.post("/items/{item_id}/assign", response_model=schemas.WorkItemOut)
def assign_item(
    item_id: int,
    payload: schemas.WorkItemAssign,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return svc.assign_work_item(db, item_id, payload, current_user)


@router.post("/items/{item_id}/transition", response_model=schemas.WorkItemOut)
def transition_item(
    item_id: int,
    payload: schemas.WorkItemTransition,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return svc.transition_work_item(db, item_id, payload, current_user)


@router.post("/items/{item_id}/comments", response_model=schemas.CommentOut, status_code=status.HTTP_201_CREATED)
def add_comment(
    item_id: int,
    payload: schemas.CommentCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return svc.add_comment(db, item_id, payload, current_user)


@router.get("/items/{item_id}/activity", response_model=list[schemas.ActivityEventOut])
def get_activity(
    item_id: int,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return svc.get_activity(db, item_id, current_user, page, size)
