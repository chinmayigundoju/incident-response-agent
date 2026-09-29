from app.core.errors import ApplicationError
from app.models.incident import Incident, IncidentStatus

ALLOWED_TRANSITIONS: dict[IncidentStatus, set[IncidentStatus]] = {
    IncidentStatus.DETECTED: {
        IncidentStatus.TRIAGED,
        IncidentStatus.INVESTIGATING,
        IncidentStatus.RESOLVED,
    },
    IncidentStatus.TRIAGED: {IncidentStatus.INVESTIGATING, IncidentStatus.RESOLVED},
    IncidentStatus.INVESTIGATING: {IncidentStatus.DIAGNOSIS_PROPOSED, IncidentStatus.RESOLVED},
    IncidentStatus.DIAGNOSIS_PROPOSED: {
        IncidentStatus.INVESTIGATING,
        IncidentStatus.MITIGATION_PROPOSED,
        IncidentStatus.RESOLVED,
    },
    IncidentStatus.MITIGATION_PROPOSED: {
        IncidentStatus.AWAITING_APPROVAL,
        IncidentStatus.RESOLVED,
    },
    IncidentStatus.AWAITING_APPROVAL: {
        IncidentStatus.MITIGATING,
        IncidentStatus.INVESTIGATING,
        IncidentStatus.RESOLVED,
    },
    IncidentStatus.MITIGATING: {
        IncidentStatus.VERIFYING_RECOVERY,
        IncidentStatus.INVESTIGATING,
        IncidentStatus.RESOLVED,
    },
    IncidentStatus.VERIFYING_RECOVERY: {IncidentStatus.RESOLVED, IncidentStatus.INVESTIGATING},
    IncidentStatus.RESOLVED: {IncidentStatus.POSTMORTEM_REVIEW},
    IncidentStatus.POSTMORTEM_REVIEW: {IncidentStatus.MEMORY_COMMITTED},
    IncidentStatus.MEMORY_COMMITTED: set(),
}


class IncidentTransitionService:
    def transition(self, incident: Incident, target: IncidentStatus) -> None:
        if target == incident.status:
            return
        if target not in ALLOWED_TRANSITIONS[incident.status]:
            raise ApplicationError(
                "INVALID_INCIDENT_TRANSITION",
                f"Cannot transition incident from {incident.status.value} to {target.value}",
                409,
            )
        incident.status = target
