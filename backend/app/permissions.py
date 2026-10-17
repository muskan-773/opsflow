"""Authorization for OpsFlow.

A single ``Permissions`` helper is the only place that decides whether a user
may perform an action on a resource. Every protected route calls it, so
authorization is enforced on the server — not by hiding buttons.

Roles (per team, from ``memberships.role``):
  * lead   — full team powers incl. approve + assign/reassign
  * member — create, claim, edit own, transition (not approve)
  * viewer — read only
``user.is_admin`` is a global override: an admin can act on any team as a
lead-equivalent.
"""
from __future__ import annotations

from typing import Iterable

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from . import models


def role_for_team(user: models.User, team_id: int) -> str | None:
    """Return the user's per-team role, or ``"admin"`` if a global admin."""
    if user.is_admin:
        return "admin"
    for m in user.memberships:
        if m.team_id == team_id:
            return m.role
    return None


def assert_team_member(user: models.User, team_id: int) -> str:
    """User must belong to the team (or be global admin). Returns their role.

    Raises 403 if they are not a member of the team at all.
    """
    role = role_for_team(user, team_id)
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this team.",
        )
    return role


def assert_can_read(user: models.User, team_id: int) -> str:
    """Any team member can read."""
    return assert_team_member(user, team_id)


def assert_can_create(user: models.User, team_id: int) -> str:
    """viewer cannot create."""
    role = assert_team_member(user, team_id)
    if role == "viewer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Viewers cannot create work items.")
    return role


def assert_can_edit(user: models.User, item: models.WorkItem) -> str:
    """Members may edit only items they created or are assigned to; leads/admins any."""
    role = assert_team_member(user, item.team_id)
    if role in ("lead", "admin"):
        return role
    if role == "viewer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Viewers cannot edit work items.")
    # member: only own items
    if user.id not in (item.creator_id, (item.assignee_id or -1)):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Members may only edit items they created or are assigned to.",
        )
    return role


def assert_can_assign(user: models.User, team_id: int) -> str:
    role = assert_team_member(user, team_id)
    if role not in ("lead", "admin"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Only a team Lead (or admin) can assign or reassign items.",
        )
    return role


def assert_can_transition(user: models.User, item: models.WorkItem) -> str:
    """viewers cannot transition; members/leads/admins can (subject to workflow rules)."""
    role = assert_team_member(user, item.team_id)
    if role == "viewer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Viewers cannot transition items.")
    return role


def assert_can_approve(user: models.User, item: models.WorkItem) -> str:
    """Approval is a Lead/admin action only."""
    role = assert_team_member(user, item.team_id)
    if role not in ("lead", "admin"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Only a team Lead (or admin) can approve items.",
        )
    return role


def visible_team_ids(user: models.User, db: Session) -> list[int]:
    """Team ids the user can see. Admin sees all teams."""
    if user.is_admin:
        return [t.id for t in db.query(models.Team).all()]
    return [m.team_id for m in user.memberships]
