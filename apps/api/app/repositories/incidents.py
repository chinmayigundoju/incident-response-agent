import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.incident import (
    ACTIVE_INCIDENT_STATUSES,
    ActionExecution,
    Approval,
    Hypothesis,
    Incident,
    IncidentEvent,
    IncidentStatus,
    Postmortem,
    Recommendation,
    RootCauseVerification,
    TelemetryEvidence,
)


class IncidentRepository:
    def __init__(self, session: Session):
        self.session = session

    def list(self, *, limit: int = 100, offset: int = 0) -> Sequence[Incident]:
        statement = (
            select(Incident).order_by(Incident.detected_at.desc()).limit(limit).offset(offset)
        )
        return self.session.scalars(statement).all()

    def get(self, incident_id: uuid.UUID) -> Incident | None:
        return self.session.get(Incident, incident_id)

    def get_for_update(self, incident_id: uuid.UUID) -> Incident | None:
        return self.session.scalars(
            select(Incident).where(Incident.id == incident_id).with_for_update()
        ).first()

    def find_active_by_fingerprint(self, fingerprint: str) -> Incident | None:
        statement = (
            select(Incident)
            .where(
                Incident.fingerprint == fingerprint,
                Incident.status.in_(ACTIVE_INCIDENT_STATUSES),
            )
            .order_by(Incident.detected_at.desc())
        )
        return self.session.scalars(statement).first()

    def find_by_external_alert_id(self, external_alert_id: str) -> Incident | None:
        return self.session.scalars(
            select(Incident).where(Incident.external_alert_id == external_alert_id)
        ).first()

    def find_latest_by_fingerprint(self, fingerprint: str) -> Incident | None:
        statement = (
            select(Incident)
            .where(Incident.fingerprint == fingerprint)
            .order_by(Incident.detected_at.desc())
        )
        return self.session.scalars(statement).first()

    def create(
        self,
        *,
        title: str,
        service: str,
        environment: str,
        severity: str,
        started_at: datetime,
        fingerprint: str | None,
        external_alert_id: str | None,
    ) -> Incident:
        incident = Incident(
            title=title,
            service=service,
            environment=environment,
            severity=severity,
            started_at=started_at,
            fingerprint=fingerprint,
            external_alert_id=external_alert_id,
            status=IncidentStatus.DETECTED,
        )
        self.session.add(incident)
        self.session.flush()
        return incident

    def create_active_or_get(self, **values: Any) -> Incident:
        try:
            with self.session.begin_nested():
                return self.create(**values)
        except IntegrityError as exc:
            constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            if constraint not in {
                "uq_incidents_active_fingerprint",
                "uq_incidents_external_alert_id",
            }:
                raise
            fingerprint = values.get("fingerprint")
            external_alert_id = values.get("external_alert_id")
            incident = self.find_active_by_fingerprint(str(fingerprint)) if fingerprint else None
            if incident is None and external_alert_id:
                incident = self.find_by_external_alert_id(str(external_alert_id))
            if incident is None:
                raise
            return incident

    def append_event(
        self,
        incident: Incident,
        *,
        event_type: str,
        payload: dict[str, Any],
        occurred_at: datetime,
        actor_type: str = "SYSTEM",
        source: str = "alertmanager",
    ) -> IncidentEvent:
        event = IncidentEvent(
            incident_id=incident.id,
            event_type=event_type,
            payload=payload,
            occurred_at=occurred_at,
            actor_type=actor_type,
            source=source,
        )
        self.session.add(event)
        self.session.flush()
        return event

    def list_events(self, incident_id: uuid.UUID) -> Sequence[IncidentEvent]:
        statement = (
            select(IncidentEvent)
            .where(IncidentEvent.incident_id == incident_id)
            .order_by(IncidentEvent.occurred_at)
        )
        return self.session.scalars(statement).all()

    def list_evidence(self, incident_id: uuid.UUID) -> Sequence[TelemetryEvidence]:
        statement = (
            select(TelemetryEvidence)
            .where(TelemetryEvidence.incident_id == incident_id)
            .order_by(TelemetryEvidence.observed_at)
        )
        return self.session.scalars(statement).all()

    def list_hypotheses(self, incident_id: uuid.UUID) -> Sequence[Hypothesis]:
        statement = (
            select(Hypothesis)
            .where(Hypothesis.incident_id == incident_id)
            .order_by(Hypothesis.created_at)
        )
        return self.session.scalars(statement).all()

    def add_evidence(
        self,
        incident_id: uuid.UUID,
        *,
        evidence_type: str,
        source: str,
        query: str | None,
        observed_at: datetime,
        content: dict[str, Any],
        content_hash: str,
    ) -> TelemetryEvidence:
        evidence = TelemetryEvidence(
            incident_id=incident_id,
            type=evidence_type,
            source=source,
            query=query,
            observed_at=observed_at,
            content=content,
            content_hash=content_hash,
        )
        self.session.add(evidence)
        self.session.flush()
        return evidence

    def add_hypothesis(
        self, incident_id: uuid.UUID, *, statement: str, status: str, confidence: float
    ) -> Hypothesis:
        hypothesis = Hypothesis(
            incident_id=incident_id,
            statement=statement,
            status=status,
            confidence=confidence,
        )
        self.session.add(hypothesis)
        self.session.flush()
        return hypothesis

    def add_recommendation(
        self,
        incident_id: uuid.UUID,
        *,
        action_type: str,
        description: str,
        rationale: str,
        risk_level: str,
    ) -> Recommendation:
        recommendation = Recommendation(
            incident_id=incident_id,
            action_type=action_type,
            description=description,
            rationale=rationale,
            risk_level=risk_level,
            approval_required=True,
            status="PENDING",
        )
        self.session.add(recommendation)
        self.session.flush()
        return recommendation

    def list_recommendations(self, incident_id: uuid.UUID) -> Sequence[Recommendation]:
        return self.session.scalars(
            select(Recommendation)
            .where(Recommendation.incident_id == incident_id)
            .order_by(Recommendation.created_at)
        ).all()

    def get_recommendation(self, recommendation_id: uuid.UUID) -> Recommendation | None:
        return self.session.get(Recommendation, recommendation_id)

    def get_approval(self, recommendation_id: uuid.UUID) -> Approval | None:
        return self.session.scalars(
            select(Approval).where(Approval.recommendation_id == recommendation_id)
        ).first()

    def add_approval(
        self,
        recommendation_id: uuid.UUID,
        *,
        decision: str,
        approver_identifier: str,
        comment: str | None,
    ) -> Approval:
        approval = Approval(
            recommendation_id=recommendation_id,
            decision=decision,
            approver_identifier=approver_identifier,
            comment=comment,
            decided_at=datetime.now(UTC),
        )
        self.session.add(approval)
        self.session.flush()
        return approval

    def get_execution(self, recommendation_id: uuid.UUID) -> ActionExecution | None:
        return self.session.scalars(
            select(ActionExecution).where(ActionExecution.recommendation_id == recommendation_id)
        ).first()

    def add_execution(
        self, recommendation_id: uuid.UUID, *, status: str, result: dict[str, Any]
    ) -> ActionExecution:
        execution = ActionExecution(
            recommendation_id=recommendation_id,
            status=status,
            result=result,
            executed_at=datetime.now(UTC),
        )
        self.session.add(execution)
        self.session.flush()
        return execution

    def get_root_cause_verification(self, incident_id: uuid.UUID) -> RootCauseVerification | None:
        return self.session.scalars(
            select(RootCauseVerification).where(RootCauseVerification.incident_id == incident_id)
        ).first()

    def add_root_cause_verification(
        self,
        incident_id: uuid.UUID,
        *,
        root_cause: str,
        approver_identifier: str,
        comment: str | None,
    ) -> RootCauseVerification:
        verification = RootCauseVerification(
            incident_id=incident_id,
            root_cause=root_cause,
            approver_identifier=approver_identifier,
            comment=comment,
        )
        self.session.add(verification)
        self.session.flush()
        return verification

    def get_postmortem(self, incident_id: uuid.UUID) -> Postmortem | None:
        return self.session.scalars(
            select(Postmortem).where(Postmortem.incident_id == incident_id)
        ).first()

    def add_postmortem(self, incident_id: uuid.UUID, draft_markdown: str) -> Postmortem:
        postmortem = Postmortem(incident_id=incident_id, draft_markdown=draft_markdown)
        self.session.add(postmortem)
        self.session.flush()
        return postmortem

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()
