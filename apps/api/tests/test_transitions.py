import pytest

from app.core.errors import ApplicationError
from app.models.incident import Incident, IncidentStatus
from app.services.transitions import IncidentTransitionService


def test_invalid_transition_rejected() -> None:
    incident = Incident(status=IncidentStatus.DETECTED)
    with pytest.raises(ApplicationError) as error:
        IncidentTransitionService().transition(incident, IncidentStatus.MEMORY_COMMITTED)
    assert error.value.code == "INVALID_INCIDENT_TRANSITION"
