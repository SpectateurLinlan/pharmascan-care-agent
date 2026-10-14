"""Demo bootstrap endpoint.

Persistent ``POST /api/demo/start`` uses the verified Supabase user identity.
Only the explicitly local in-memory mode derives unauthenticated demo identity
from a browser client_id. All records remain synthetic/demo_only.

The persistent request factory creates only the authenticated user's own
profile through RLS. No administrative identity provisioner enters this path.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..container import demo_patient_id
from ..deps import ApplicationContainer, get_container, get_principal
from ..schemas import DemoStartRequest, DemoStartResponse

router = APIRouter(prefix="/api/demo", tags=["demo"])


@router.post("/start", response_model=DemoStartResponse)
def start(
    payload: DemoStartRequest,
    request: Request,
    container: ApplicationContainer = Depends(get_container),
) -> DemoStartResponse:
    patient_id = (
        get_principal(request, None).patient_id
        if container.auth.mode == "supabase"
        else demo_patient_id(payload.client_id)
    )
    # Admin setup only: ensure the synthetic identity exists. Idempotent, and it
    # touches no patient data. ``admin`` is None for the in-memory wiring, where
    # no owner rows are required.
    if container.admin is not None:
        container.admin.ensure_identity(patient_id=patient_id)
    session = (
        container.orchestrator.get_session(patient_id=patient_id, session_id=payload.session_id)
        if payload.session_id
        else None
    )
    if session is None or session.state == "expired":
        session = container.orchestrator.start_session(patient_id=patient_id)
    active = container.enrollment.list_medications(patient_id)
    return DemoStartResponse(
        patient_id=patient_id,
        session_id=session.id,
        seeded_medication_count=len(active),
    )
