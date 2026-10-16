"""SQLAlchemy models for OpsFlow.

Tables:
  users, teams, memberships, work_items, comments, activity_events,
  idempotency_keys.

Notes:
  * ``memberships`` makes roles per-team (user, team, role). ``admin`` is a
    global role stored on the user (``is_admin``), separate from per-team
    roles, so an admin can act on every team.
  * ``work_items.version`` is the optimistic-locking token.
  * ``activity_events`` is append-only — there is no UPDATE/DELETE path.
  * Indexes cover the common filtering/join fields used by the list and
    dashboard queries.
"""
from __future__ import annotations

from datetime import datetime, date
from typing import Optional

from sqlalchemy import (
    Integer,
    String,
    Text,
    Boolean,
    DateTime,
    Date,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from .database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Global admin flag — admin can act on every team regardless of memberships.
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )


class Membership(Base):
    __tablename__ = "memberships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    # per-team role: lead | member | viewer  (admin is global, on the user)
    role: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "team_id", name="uq_user_team"),)

    user: Mapped["User"] = relationship(back_populates="memberships")
    team: Mapped["Team"] = relationship(back_populates="memberships")


class WorkItem(Base):
    __tablename__ = "work_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False, index=True)
    assignee_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    team: Mapped["Team"] = relationship(foreign_keys=[team_id])
    assignee: Mapped[Optional["User"]] = relationship(foreign_keys=[assignee_id])
    creator: Mapped["User"] = relationship(foreign_keys=[creator_id])
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="work_item", cascade="all, delete-orphan", order_by="Comment.created_at"
    )
    activity: Mapped[list["ActivityEvent"]] = relationship(
        back_populates="work_item", cascade="all, delete-orphan", order_by="ActivityEvent.created_at"
    )

    __table_args__ = (
        Index("ix_work_items_status_priority", "status", "priority"),
        Index("ix_work_items_team_assignee", "team_id", "assignee_id"),
    )


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    work_item_id: Mapped[int] = mapped_column(ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    work_item: Mapped["WorkItem"] = relationship(back_populates="comments")
    author: Mapped["User"] = relationship(foreign_keys=[author_id])


class ActivityEvent(Base):
    """Append-only history. There is intentionally no update/delete path."""
    __tablename__ = "activity_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    work_item_id: Mapped[int] = mapped_column(ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    field: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    old_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    work_item: Mapped["WorkItem"] = relationship(back_populates="activity")
    actor: Mapped[Optional["User"]] = relationship(foreign_keys=[actor_id])


class IdempotencyKey(Base):
    """Stores the full response for a create request so a repeated key
    returns the stored result instead of creating a duplicate."""
    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    request_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    response_body: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OutboxJob(Base):
    """Transactional Outbox table for reliable asynchronous events (e.g. notifications).
    Written inside the same database transaction as the work-item mutation."""
    __tablename__ = "outbox_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    aggregate_type: Mapped[str] = mapped_column(String(32), nullable=False, default="work_item")
    aggregate_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)  # pending | processing | completed | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_outbox_jobs_status_scheduled", "status", "scheduled_for"),
    )


class ProcessedNotification(Base):
    """Consumer idempotency store to guarantee that at-least-once outbox
    delivery produces exactly-once side effects."""
    __tablename__ = "processed_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("outbox_jobs.id", ondelete="CASCADE"), unique=True, nullable=False)
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

