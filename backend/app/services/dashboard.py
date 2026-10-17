"""Dashboard service: the "needs attention" counts and lists.

All counts are scoped to the user's visible teams and computed on the server
with indexed queries — the browser never filters the full list.
"""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import func, select

from .. import models, schemas
from ..permissions import visible_team_ids
from .work_items import _enrich, _to_out

OPEN_STATUSES = ("open", "in_progress", "awaiting_approval")
URGENT_PRIORITIES = ("high", "critical")


def build_dashboard(db, user: models.User) -> schemas.DashboardResponse:
    teams = visible_team_ids(user, db)
    if not teams:
        return schemas.DashboardResponse(
            stats=schemas.DashboardStats(0, 0, 0, 0, 0),
            assigned_to_me=[],
            unassigned_urgent=[],
            awaiting_my_approval=[],
        )

    base = select(models.WorkItem).where(models.WorkItem.team_id.in_(teams))

    total_open = db.scalar(
        select(func.count()).select_from(
            base.where(models.WorkItem.status.in_(OPEN_STATUSES)).subquery()
        )
    ) or 0

    critical_high = db.scalar(
        select(func.count()).select_from(
            base.where(
                models.WorkItem.status.in_(OPEN_STATUSES),
                models.WorkItem.priority.in_(URGENT_PRIORITIES),
            ).subquery()
        )
    ) or 0

    assigned_to_me_count = db.scalar(
        select(func.count()).select_from(
            base.where(
                models.WorkItem.assignee_id == user.id,
                models.WorkItem.status.in_(OPEN_STATUSES),
            ).subquery()
        )
    ) or 0

    unassigned_urgent_count = db.scalar(
        select(func.count()).select_from(
            base.where(
                models.WorkItem.assignee_id.is_(None),
                models.WorkItem.priority.in_(URGENT_PRIORITIES),
                models.WorkItem.status.in_(OPEN_STATUSES),
            ).subquery()
        )
    ) or 0

    # Items awaiting the user's approval: items in awaiting_approval on teams
    # where the user is lead/admin.
    lead_team_ids = [t for t in teams if (user.is_admin or role_for_team(user, t) in ("lead",))]
    if user.is_admin:
        lead_team_ids = teams
    awaiting_count = 0
    if lead_team_ids:
        awaiting_count = db.scalar(
            select(func.count()).select_from(
                select(models.WorkItem)
                .where(
                    models.WorkItem.team_id.in_(lead_team_ids),
                    models.WorkItem.status == "awaiting_approval",
                )
                .subquery()
            )
        ) or 0

    # Lists (small, capped)
    def _list(stmt, limit=10):
        rows = db.execute(stmt.order_by(models.WorkItem.created_at.desc()).limit(limit)).scalars().all()
        return [_to_out(_enrich(r, db)) for r in rows]

    me_list = _list(
        select(models.WorkItem).where(
            models.WorkItem.team_id.in_(teams),
            models.WorkItem.assignee_id == user.id,
            models.WorkItem.status.in_(OPEN_STATUSES),
        )
    )
    urgent_list = _list(
        select(models.WorkItem).where(
            models.WorkItem.team_id.in_(teams),
            models.WorkItem.assignee_id.is_(None),
            models.WorkItem.priority.in_(URGENT_PRIORITIES),
            models.WorkItem.status.in_(OPEN_STATUSES),
        )
    )
    awaiting_list = []
    if lead_team_ids:
        awaiting_list = _list(
            select(models.WorkItem).where(
                models.WorkItem.team_id.in_(lead_team_ids),
                models.WorkItem.status == "awaiting_approval",
            )
        )

    return schemas.DashboardResponse(
        stats=schemas.DashboardStats(
            total_open=total_open,
            critical_high=critical_high,
            assigned_to_me=assigned_to_me_count,
            unassigned_urgent=unassigned_urgent_count,
            awaiting_my_approval=awaiting_count,
        ),
        assigned_to_me=me_list,
        unassigned_urgent=urgent_list,
        awaiting_my_approval=awaiting_list,
    )


def role_for_team(user: models.User, team_id: int) -> str | None:
    if user.is_admin:
        return "admin"
    for m in user.memberships:
        if m.team_id == team_id:
            return m.role
    return None
