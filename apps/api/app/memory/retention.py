import json

from app.memory.schemas import VerifiedIncidentMemory


def render_verified_incident(memory: VerifiedIncidentMemory) -> str:
    data = {
        "incident_identifier": memory.incident_id,
        "affected_service": memory.service,
        "environment": memory.environment,
        "symptoms": memory.symptoms,
        "confirmed_root_cause": memory.confirmed_root_cause,
        "decisive_evidence": memory.decisive_evidence,
        "successful_mitigation": memory.successful_mitigation,
        "failed_investigation_paths": memory.failed_investigation_paths,
        "runbook": memory.runbook,
        "recovery_verification": memory.recovery_verification,
        "important_caveats": memory.important_caveats,
        "verification_status": "verified",
        "verification_basis": memory.verification_basis,
    }
    return json.dumps(data, indent=2, sort_keys=True)
