from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AlertmanagerAlert(BaseModel):
    model_config = ConfigDict(extra="ignore")
    status: Literal["firing", "resolved"]
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: datetime
    endsAt: datetime | None = None
    generatorURL: str | None = None
    fingerprint: str | None = None

    @field_validator("startsAt", "endsAt")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        return value


class AlertmanagerWebhook(BaseModel):
    model_config = ConfigDict(extra="ignore")
    version: str
    status: Literal["firing", "resolved"]
    receiver: str
    groupKey: str = ""
    truncatedAlerts: int = 0
    commonLabels: dict[str, str] = Field(default_factory=dict)
    commonAnnotations: dict[str, str] = Field(default_factory=dict)
    externalURL: str | None = None
    alerts: list[AlertmanagerAlert] = Field(min_length=1, max_length=100)


class WebhookResult(BaseModel):
    accepted: int
    incident_ids: list[str]


def normalized_payload(alert: AlertmanagerAlert) -> dict[str, Any]:
    return {
        "status": alert.status,
        "labels": alert.labels,
        "annotations": alert.annotations,
        "starts_at": alert.startsAt.isoformat(),
        "ends_at": alert.endsAt.isoformat() if alert.endsAt else None,
        "generator_url": alert.generatorURL,
        "fingerprint": alert.fingerprint,
    }
