"""Demo bootstrap endpoint.

The hackathon demo has no real auth. ``POST /api/demo/start`` therefore mints
a *synthetic* patient scoped to a browser ``client_id``. This is explicitly
NOT authentication and grants no access to any real record.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..container import demo_patient_id
from ..deps import ApplicationContainer, get_container
from ..schemas import DemoStartRequest, DemoStartResponse

router = APIRouter(prefix="/api/demo", tags=["demo"])


@router.post("/start", response_model=DemoStartResponse)
def start(
    payload: DemoStartRequest,
    container: ApplicationContainer = Depends(get_container),
) -> DemoStartResponse:
    patient_id = demo_patient_id(payload.client_id)
    session = container.orchestrator.start_session(patient_id=patient_id)
    active = container.enrollment._medications.list_for_patient(patient_id)
    return DemoStartResponse(
        patient_id=patient_id,
        session_id=session.id,
        seeded_medication_count=len(active),
    )
