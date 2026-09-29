import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.incident import IncidentStatus


class IncidentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    external_alert_id: str | None
    fingerprint: str | None
    title: str
    service: str
    environment: str
    severity: str
    status: IncidentStatus
    started_at: datetime
    detected_at: datetime
    mitigated_at: datetime | None
    resolved_at: datetime | None
    summary: str | None
    confirmed_root_cause: str | None
    created_at: datetime
    updated_at: datetime


class IncidentEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    incident_id: uuid.UUID
    occurred_at: datetime
    actor_type: str
    event_type: str
    source: str
    payload: dict[str, Any]
    created_at: datetime


class EvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    incident_id: uuid.UUID
    type: str
    source: str
    query: str | None
    observed_at: datetime
    content: dict[str, Any]
    content_hash: str | None
    created_at: datetime


class HypothesisRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    incident_id: uuid.UUID
    statement: str
    status: str
    confidence: str | None
    created_at: datetime
    updated_at: datetime
