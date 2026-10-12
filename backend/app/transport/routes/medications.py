"""Medication endpoints: list, draft, review, confirm, activate.

Every route is scoped to the demo principal's synthetic patient id. Routes
call application services only — they never touch a repository or the DB.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from ...application.timezone import LOCAL_TZ_PROVIDER
from ...contracts.dto import FrequencyRuleDTO, RegimenDraftInput
from ...domain.errors import NotFoundError
from ..container import demo_patient_id
from ..deps import ApplicationContainer, get_container
from ..schemas import (
    ConfirmActivateRequest,
    ConfirmActivateResponse,
    ConfirmChallengeResponse,
    DraftCreateRequest,
    DraftCreateResponse,
    DraftReviewRequest,
    DraftReviewResponse,
    MedicationListResponse,
    MedicationSummary,
)

router = APIRouter(prefix="/api", tags=["medications"])


def _require_patient(client_id: str) -> UUID:
    """Demo principal -> synthetic patient id. Not authentication."""
    if not client_id.strip():
        raise NotFoundError("client_id is required")
    return demo_patient_id(client_id)


@router.get("/me/medications", response_model=MedicationListResponse)
def list_medications(
    client_id: str = Query(min_length=1, max_length=128),
    container: ApplicationContainer = Depends(get_container),
) -> MedicationListResponse:
    patient_id = _require_patient(client_id)
    summaries: list[MedicationSummary] = []
    for medication in container.enrollment._medications.list_for_patient(patient_id):
        regimen = container.enrollment._regimens.find_active_for_medication(
            patient_id, medication.id
        )
        if regimen is None:
            continue
        summaries.append(
            MedicationSummary(
                medication_id=medication.id,
                regimen_id=regimen.id,
                display_name=medication.display_name,
                is_prn=regimen.is_prn,
                version_no=regimen.version_no,
                identity_status=medication.identity_status.value,
                source_backed=medication.source_id is not None,
            )
        )
    return MedicationListResponse(item_count=len(summaries), medications=summaries)


@router.post("/medications/drafts", response_model=DraftCreateResponse)
def create_draft(
    payload: DraftCreateRequest,
    client_id: str = Query(min_length=1, max_length=128),
    container: ApplicationContainer = Depends(get_container),
) -> DraftCreateResponse:
    """Create a draft. Missing required inputs keep it pending — never active."""
    patient_id = _require_patient(client_id)

    frequency: FrequencyRuleDTO | None = None
    if payload.frequency_kind is not None:
        frequency = FrequencyRuleDTO(
            kind=payload.frequency_kind,
            local_times=list(payload.frequency_local_times),
            days_of_week=list(payload.frequency_days_of_week),
            every_hours=payload.frequency_every_hours,
        )

    result = container.enrollment.enroll_draft(
        patient_id=patient_id,
        draft=RegimenDraftInput(
            medication_name=payload.medication_name,
            dose_amount=payload.dose_amount,
            dose_unit=payload.dose_unit,
            frequency_rule=frequency,
            is_prn=payload.is_prn,
            route=payload.route,
            food_instruction=payload.food_instruction,
        ),
    )
    return DraftCreateResponse(
        medication_id=result.medication.id,
        regimen_id=result.regimen.id,
        state=result.regimen.state.value,
        source_id=result.medication.source_id,
        missing_instructions=[m.field.value for m in result.missing_instructions],
        reviewable_field_ids=[f.id for f in result.source_fields],
    )


@router.post("/medications/drafts/{source_id}/review", response_model=DraftReviewResponse)
def review_draft(
    source_id: UUID,
    payload: DraftReviewRequest,
    client_id: str = Query(min_length=1, max_length=128),
    container: ApplicationContainer = Depends(get_container),
) -> DraftReviewResponse:
    """Patient confirms extracted fields; required for any activation."""
    patient_id = _require_patient(client_id)
    count = container.enrollment.review_source_fields(
        patient_id=patient_id, source_id=source_id, field_ids=payload.field_ids
    )
    return DraftReviewResponse(reviewed_field_count=count, source_id=source_id)


@router.post(
    "/medications/drafts/{regimen_id}/challenge",
    response_model=ConfirmChallengeResponse,
)
def request_challenge(
    regimen_id: UUID,
    client_id: str = Query(min_length=1, max_length=128),
    session_id: UUID = Query(),
    container: ApplicationContainer = Depends(get_container),
) -> ConfirmChallengeResponse:
    """Issue a single-use confirmation challenge bound to the session version.

    The session is first moved to ``awaiting_confirmation``; the version it
    returns is what the client must echo back on activation.
    """
    patient_id = _require_patient(client_id)
    session = container.orchestrator.get_session(
        patient_id=patient_id, session_id=session_id
    )
    if session is None:
        raise NotFoundError(f"Agent session {session_id} not found for this patient")

    regimen = container.enrollment._regimens.get(patient_id, regimen_id)
    if regimen is None:
        raise NotFoundError(f"Regimen {regimen_id} not found")

    session = container.orchestrator.await_confirmation(
        patient_id=patient_id, session_id=session_id
    )
    challenge, _token = container.enrollment.request_activation_challenge(
        patient_id=patient_id,
        regimen_id=regimen_id,
        session_id=session_id,
        session_state_version=session.state_version,
    )
    return ConfirmChallengeResponse(
        regimen_id=regimen_id,
        challenge_id=challenge.id,
        session_id=session_id,
        session_state=session.state,
        session_state_version=session.state_version,
        expires_at=challenge.expires_at,
        summary={
            "medication_name": _medication_name(container, patient_id, regimen),
            "dose_amount": regimen.dose_amount,
            "dose_unit": regimen.dose_unit,
            "frequency": regimen.frequency_rule,
            "is_prn": regimen.is_prn,
            "version_no": regimen.version_no,
            "local_timezone": str(LOCAL_TZ_PROVIDER.local_tz(patient_id)),
        },
    )


@router.post("/medications/activate", response_model=ConfirmActivateResponse)
def activate(
    payload: ConfirmActivateRequest,
    client_id: str = Query(min_length=1, max_length=128),
    container: ApplicationContainer = Depends(get_container),
) -> ConfirmActivateResponse:
    """Consume a confirmed challenge and activate the regimen version."""
    patient_id = _require_patient(client_id)
    container.enrollment.confirm_challenge(
        patient_id=patient_id, challenge_id=payload.challenge_id
    )
    activated = container.enrollment.activate_regimen(
        patient_id=patient_id,
        regimen_id=payload.regimen_id,
        challenge_id=payload.challenge_id,
        session_state=payload.session_state,
        session_state_version=payload.session_state_version,
    )
    return ConfirmActivateResponse(
        regimen_id=activated.regimen.id,
        state=activated.regimen.state.value,
        superseded_regimen_ids=activated.superseded_regimen_ids,
    )


def _medication_name(
    container: ApplicationContainer, patient_id: UUID, regimen
) -> str:
    medication = container.enrollment._medications.get(
        patient_id, regimen.patient_medication_id
    )
    return medication.display_name if medication else "Unknown medication"
