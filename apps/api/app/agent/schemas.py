import enum
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class EvidenceType(enum.StrEnum):
    INCIDENT_CONTEXT = "INCIDENT_CONTEXT"
    METRIC = "METRIC"
    LOG = "LOG"
    TRACE = "TRACE"
    DEPLOYMENT = "DEPLOYMENT"
    RUNBOOK = "RUNBOOK"
    HISTORICAL_MEMORY = "HISTORICAL_MEMORY"
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    RECOVERY = "RECOVERY"


class HypothesisStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    REJECTED = "REJECTED"
    CONFIRMED = "CONFIRMED"


class Confidence(enum.StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ActionType(enum.StrEnum):
    ROLLBACK_CHECKOUT_DEMO = "ROLLBACK_CHECKOUT_DEMO"
    RESET_PAYMENT_FAULT = "RESET_PAYMENT_FAULT"
    RESET_DB_POOL_FAULT = "RESET_DB_POOL_FAULT"
    NO_ACTION = "NO_ACTION"
    ESCALATE = "ESCALATE"


class InvestigationEvidence(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    type: EvidenceType
    source: str
    service: str
    summary: str
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    details: dict[str, Any]


class AgentHypothesis(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    statement: str
    status: HypothesisStatus
    confidence: Confidence
    supporting_evidence_ids: list[uuid.UUID] = Field(default_factory=list)
    contradicting_evidence_ids: list[uuid.UUID] = Field(default_factory=list)


class ToolRequest(BaseModel):
    kind: Literal["tool"] = "tool"
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    rationale: str


class ToolCallRecord(BaseModel):
    tool: str
    evidence_id: uuid.UUID
    status: Literal["SUCCEEDED", "UNAVAILABLE"]


class Diagnosis(BaseModel):
    kind: Literal["diagnosis"] = "diagnosis"
    status: Literal["PROPOSED"] = "PROPOSED"
    primary_hypothesis: AgentHypothesis
    root_cause_statement: str
    supporting_evidence: list[uuid.UUID] = Field(min_length=1)
    contradicting_evidence: list[uuid.UUID] = Field(default_factory=list)
    remaining_uncertainties: list[str] = Field(default_factory=list)
    historical_precedent: str | None = None
    recommended_next_step: str
    recommended_action: ActionType
    action_rationale: str
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]


AgentStep = ToolRequest | Diagnosis


class InvestigationResult(BaseModel):
    incident_id: str
    status: str
    proposed_diagnosis: Diagnosis
    hypotheses: list[AgentHypothesis]
    evidence: list[InvestigationEvidence]
    historical_memories: list[InvestigationEvidence]
    recommended_action: ActionType
    tool_calls: list[ToolCallRecord]
    iterations: int
