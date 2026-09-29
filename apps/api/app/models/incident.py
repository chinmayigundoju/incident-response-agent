import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class IncidentStatus(enum.StrEnum):
    DETECTED = "DETECTED"
    TRIAGED = "TRIAGED"
    INVESTIGATING = "INVESTIGATING"
    DIAGNOSIS_PROPOSED = "DIAGNOSIS_PROPOSED"
    MITIGATION_PROPOSED = "MITIGATION_PROPOSED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    MITIGATING = "MITIGATING"
    VERIFYING_RECOVERY = "VERIFYING_RECOVERY"
    RESOLVED = "RESOLVED"
    POSTMORTEM_REVIEW = "POSTMORTEM_REVIEW"
    MEMORY_COMMITTED = "MEMORY_COMMITTED"


ACTIVE_INCIDENT_STATUSES = (
    IncidentStatus.DETECTED,
    IncidentStatus.TRIAGED,
    IncidentStatus.INVESTIGATING,
    IncidentStatus.DIAGNOSIS_PROPOSED,
    IncidentStatus.MITIGATION_PROPOSED,
    IncidentStatus.AWAITING_APPROVAL,
    IncidentStatus.MITIGATING,
    IncidentStatus.VERIFYING_RECOVERY,
)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class Incident(TimestampMixin, Base):
    __tablename__ = "incidents"
    __table_args__ = (
        Index("ix_incidents_fingerprint", "fingerprint"),
        Index("ix_incidents_service_status", "service", "status"),
        Index(
            "uq_incidents_active_fingerprint",
            "fingerprint",
            unique=True,
            postgresql_where=text(
                "fingerprint IS NOT NULL AND status IN ("
                "'DETECTED', 'TRIAGED', 'INVESTIGATING', 'DIAGNOSIS_PROPOSED', "
                "'MITIGATION_PROPOSED', 'AWAITING_APPROVAL', 'MITIGATING', "
                "'VERIFYING_RECOVERY')"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_alert_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    fingerprint: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(255))
    service: Mapped[str] = mapped_column(String(128))
    environment: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(32))
    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus, name="incident_status"), default=IncidentStatus.DETECTED
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    mitigated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[str | None] = mapped_column(Text)
    confirmed_root_cause: Mapped[str | None] = mapped_column(Text)
    events: Mapped[list["IncidentEvent"]] = relationship(back_populates="incident")


class IncidentEvent(Base):
    __tablename__ = "incident_events"
    __table_args__ = (Index("ix_incident_events_incident_occurred", "incident_id", "occurred_at"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE")
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    actor_type: Mapped[str] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(128))
    source: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    incident: Mapped[Incident] = relationship(back_populates="events")


class TelemetryEvidence(Base):
    __tablename__ = "telemetry_evidence"
    __table_args__ = (
        Index("ix_telemetry_evidence_incident_observed", "incident_id", "observed_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE")
    )
    type: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(128))
    query: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    content_hash: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Hypothesis(TimestampMixin, Base):
    __tablename__ = "hypotheses"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), index=True
    )
    statement: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[str | None] = mapped_column(String(16))


class HypothesisEvidence(Base):
    __tablename__ = "hypothesis_evidence"
    __table_args__ = (UniqueConstraint("hypothesis_id", "evidence_id"),)
    hypothesis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hypotheses.id", ondelete="CASCADE"), primary_key=True
    )
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("telemetry_evidence.id", ondelete="CASCADE"),
        primary_key=True,
    )
    relationship: Mapped[str] = mapped_column(String(32))


class Recommendation(TimestampMixin, Base):
    __tablename__ = "recommendations"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), index=True
    )
    action_type: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String(32))
    approval_required: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(32))


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (UniqueConstraint("recommendation_id"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recommendation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recommendations.id", ondelete="CASCADE"), index=True
    )
    decision: Mapped[str] = mapped_column(String(32))
    approver_identifier: Mapped[str] = mapped_column(String(255))
    comment: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ActionExecution(TimestampMixin, Base):
    __tablename__ = "action_executions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recommendation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recommendations.id", ondelete="CASCADE"),
        unique=True,
    )
    status: Mapped[str] = mapped_column(String(32))
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RootCauseVerification(Base):
    __tablename__ = "root_cause_verifications"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), unique=True
    )
    root_cause: Mapped[str] = mapped_column(Text)
    approver_identifier: Mapped[str] = mapped_column(String(255))
    comment: Mapped[str | None] = mapped_column(Text)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Runbook(TimestampMixin, Base):
    __tablename__ = "runbooks"
    __table_args__ = (UniqueConstraint("service", "title", "version"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    service: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(255))
    version: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)


class Postmortem(TimestampMixin, Base):
    __tablename__ = "postmortems"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), unique=True
    )
    draft_markdown: Mapped[str] = mapped_column(Text)
    final_markdown: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[str | None] = mapped_column(String(255))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MemorySync(TimestampMixin, Base):
    __tablename__ = "memory_sync"
    __table_args__ = (UniqueConstraint("incident_id", "bank_id", "document_id"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), index=True
    )
    bank_id: Mapped[str] = mapped_column(String(255))
    document_id: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32))
    checksum: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    retained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
