"""Pydantic request/response schemas.

The work-item create/update schemas use string enums for type, priority and
status so invalid values are rejected at the validation layer with a clear
422 before reaching the service.
"""
from __future__ import annotations

from datetime import datetime, date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict


# Core Enums
class WorkItemType(str, Enum):
    incident = "incident"
    customer_issue = "customer_issue"
    payment = "payment"
    compliance = "compliance"
    task = "task"


class Priority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class WorkItemStatus(str, Enum):
    open = "open"
    in_progress = "in_progress"
    awaiting_approval = "awaiting_approval"
    resolved = "resolved"
    closed = "closed"


class Role(str, Enum):
    lead = "lead"
    member = "member"
    viewer = "viewer"


# Auth schemas
class LoginRequest(BaseModel):
    email: str = Field(..., examples=["lead.ops@opsflow.demo"])
    password: str = Field(..., examples=["lead123"])


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class MembershipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    team_id: int
    team_name: str
    role: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    name: str
    is_admin: bool
    memberships: list[MembershipOut] = []


# Work item schemas
class WorkItemCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    type: WorkItemType
    priority: Priority = Priority.medium
    team_id: int
    assignee_id: Optional[int] = None
    due_date: Optional[date] = None


class WorkItemUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    type: Optional[WorkItemType] = None
    priority: Optional[Priority] = None
    due_date: Optional[date] = None
    # version is the optimistic-locking token the client must send.
    version: int = Field(..., description="Current version the client based its edit on")


class WorkItemAssign(BaseModel):
    assignee_id: int


class WorkItemTransition(BaseModel):
    target_status: WorkItemStatus


class CommentCreate(BaseModel):
    body: str = Field(..., min_length=1)


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    work_item_id: int
    author_id: int
    author_name: Optional[str] = None
    body: str
    created_at: datetime


class ActivityEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    work_item_id: int
    actor_id: Optional[int]
    actor_name: Optional[str] = None
    event_type: str
    field: Optional[str]
    old_value: Optional[str]
    new_value: Optional[str]
    created_at: datetime


class WorkItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    description: Optional[str]
    type: str
    priority: str
    status: str
    team_id: int
    team_name: Optional[str] = None
    assignee_id: Optional[int]
    assignee_name: Optional[str] = None
    creator_id: int
    creator_name: Optional[str] = None
    due_date: Optional[date]
    version: int
    created_at: datetime
    updated_at: datetime


class WorkItemDetail(WorkItemOut):
    comments: list[CommentOut] = []
    activity: list[ActivityEventOut] = []


class WorkItemListMeta(BaseModel):
    total: int
    page: int
    size: int
    pages: int


class WorkItemListResponse(BaseModel):
    items: list[WorkItemOut]
    meta: WorkItemListMeta


# Dashboard schemas
class DashboardStats(BaseModel):
    total_open: int
    critical_high: int
    assigned_to_me: int
    unassigned_urgent: int
    awaiting_my_approval: int


class DashboardResponse(BaseModel):
    stats: DashboardStats
    assigned_to_me: list[WorkItemOut]
    unassigned_urgent: list[WorkItemOut]
    awaiting_my_approval: list[WorkItemOut]


Token.model_rebuild()
