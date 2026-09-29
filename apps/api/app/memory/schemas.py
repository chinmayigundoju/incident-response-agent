from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class MemoryHealth(BaseModel):
    configured: bool
    available: bool


class VerifiedIncidentMemory(BaseModel):
    incident_id: str
    service: str
    environment: str
    symptoms: list[str] = Field(min_length=1)
    confirmed_root_cause: str
    decisive_evidence: list[str] = Field(min_length=1)
    successful_mitigation: str
    failed_investigation_paths: list[str] = Field(default_factory=list)
    runbook: str | None = None
    recovery_verification: str | None = None
    important_caveats: list[str] = Field(default_factory=list)
    resolved: bool
    verified: bool
    verification_basis: Literal[
        "approved_postmortem", "approved_resolution", "seeded_historical_incident"
    ]

    @model_validator(mode="after")
    def trusted_memory_requirements(self) -> "VerifiedIncidentMemory":
        if not self.resolved or not self.verified or not self.confirmed_root_cause.strip():
            raise ValueError("trusted memory requires a resolved, verified incident and root cause")
        return self


class MemoryRecord(BaseModel):
    text: str
    source_document: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    relevance: float | None = None
    ranking: dict[str, float] = Field(default_factory=dict)


class RecallResult(BaseModel):
    available: bool
    memories: list[MemoryRecord] = Field(default_factory=list)


class RetentionResult(BaseModel):
    bank_id: str
    document_id: str
    retained: bool


class ReflectionResult(BaseModel):
    available: bool
    text: str | None = None
