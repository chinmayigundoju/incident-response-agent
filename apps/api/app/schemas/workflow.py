import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DecisionRequest(BaseModel):
    approver_identifier: str = Field(min_length=1, max_length=255)
    comment: str | None = Field(default=None, max_length=2000)


class RootCauseRequest(BaseModel):
    confirmed_root_cause: str = Field(min_length=10, max_length=5000)
    verification_comment: str = Field(min_length=1, max_length=2000)
    approver_identifier: str = Field(min_length=1, max_length=255)


class RecommendationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    incident_id: uuid.UUID
    action_type: str
    description: str
    rationale: str
    risk_level: str
    approval_required: bool
    status: str
    created_at: datetime
    updated_at: datetime


class ApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    recommendation_id: uuid.UUID
    decision: str
    approver_identifier: str
    comment: str | None
    decided_at: datetime


class ActionExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    recommendation_id: uuid.UUID
    status: str
    result: dict[str, Any]
    executed_at: datetime


class RecoveryResult(BaseModel):
    recovered: bool
    status: str
    evidence: dict[str, Any]


class PostmortemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    incident_id: uuid.UUID
    draft_markdown: str
    final_markdown: str | None
    approved_by: str | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RootCauseVerificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    incident_id: uuid.UUID
    root_cause: str
    approver_identifier: str
    comment: str | None
    confirmed_at: datetime


class MemoryCommitResult(BaseModel):
    status: Literal["committed", "already_committed"]
    document_id: str
