"""Medication endpoints: list, draft, review, confirm, activate.

Every route is scoped to the identity resolved by ``get_principal``: a
verified Supabase JWT in ``AUTH_MODE=supabase``, or the explicitly
unauthenticated demo principal otherwise. Routes call application services
only — they never touch a repository or the DB.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from ...application.timezone import LOCAL_TZ_PROVIDER
from ...contracts.dto import FrequencyRuleDTO, RegimenDraftInput
from ...domain.errors import NotFoundError
from ..auth import AuthenticatedPrincipal
from ..deps import ApplicationContainer, get_container, get_principal
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


class RegimenHistoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    regimen_id: UUID
    display_name: str
    version_no: int
    state: str
    effective_from: datetime | None
    effective_to: datetime | None
    medication_id: UUID
    course_start_date: date | None
    course_end_date: date | None
    dose_amount: float | None
    dose_unit: str | None
    food_instruction: str | None
    is_prn: bool
    local_times: list[str]


@router.get("/me/regimens", response_model=list[RegimenHistoryItem])
def regimen_history(
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
) -> list[RegimenHistoryItem]:
    result = []
    for medication in container.enrollment.list_medications(principal.patient_id):
        for regimen in container.enrollment.list_regimens(principal.patient_id, medication.id):
            result.append(
                RegimenHistoryItem(
                    regimen_id=regimen.id,
                    display_name=medication.display_name,
                    version_no=regimen.version_no,
                    state=str(regimen.state),
                    effective_from=regimen.effective_from,
                    effective_to=regimen.effective_to,
                    medication_id=medication.id,
                    course_start_date=regimen.course_start_date,
                    course_end_date=regimen.course_end_date,
                    dose_amount=regimen.dose_amount,
                    dose_unit=regimen.dose_unit,
                    food_instruction=regimen.food_instruction,
                    is_prn=regimen.is_prn,
                    local_times=(regimen.frequency_rule or {}).get("local_times", []),
                )
            )
    return result


@router.get("/me/medications", response_model=MedicationListResponse)
def list_medications(
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
) -> MedicationListResponse:
    patient_id = principal.patient_id
    summaries: list[MedicationSummary] = []
    for medication in container.enrollment.list_medications(patient_id):
        regimen = container.enrollment.find_active_regimen(patient_id, medication.id)
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
                dose_amount=regimen.dose_amount,
                dose_unit=regimen.dose_unit,
                frequency_rule=regimen.frequency_rule,
                food_instruction=regimen.food_instruction,
                course_start_date=regimen.course_start_date,
                course_end_date=regimen.course_end_date,
            )
        )
    return MedicationListResponse(item_count=len(summaries), medications=summaries)


@router.get("/medications/drafts/{regimen_id}", response_model=DraftCreateResponse)
def resume_draft(
    regimen_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
) -> DraftCreateResponse:
    result = container.enrollment.resume_draft(principal.patient_id, regimen_id)
    return DraftCreateResponse(
        medication_id=result.medication.id,
        regimen_id=result.regimen.id,
        state=result.regimen.state.value,
        source_id=result.regimen.source_id,
        missing_instructions=[item.field.value for item in result.missing_instructions],
        reviewable_field_ids=[item.id for item in result.source_fields],
    )


@router.post("/medications/drafts", response_model=DraftCreateResponse)
def create_draft(
    payload: DraftCreateRequest,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
) -> DraftCreateResponse:
    """Create a draft. Missing required inputs keep it pending — never active."""
    patient_id = principal.patient_id

    frequency: FrequencyRuleDTO | None = None
    if payload.frequency_kind is not None:
        frequency = FrequencyRuleDTO(
            kind=payload.frequency_kind,
            local_times=list(payload.frequency_local_times),
            days_of_week=list(payload.frequency_days_of_week),
            every_hours=payload.frequency_every_hours,
        )

    result = container.enrollment.enroll_draft(
        extraction_evidence=payload.extraction_evidence,
        patient_id=patient_id,
        draft=RegimenDraftInput(
            medication_name=payload.medication_name,
            dose_amount=payload.dose_amount,
            dose_unit=payload.dose_unit,
            frequency_rule=frequency,
            is_prn=payload.is_prn,
            route=payload.route,
            food_instruction=payload.food_instruction,
            course_start_date=payload.course_start_date,
            course_end_date=payload.course_end_date,
        ),
    )
    return DraftCreateResponse(
        medication_id=result.medication.id,
        regimen_id=result.regimen.id,
        state=result.regimen.state.value,
        source_id=result.regimen.source_id,
        missing_instructions=[m.field.value for m in result.missing_instructions],
        reviewable_field_ids=[f.id for f in result.source_fields],
    )


@router.post("/medications/drafts/{source_id}/review", response_model=DraftReviewResponse)
def review_draft(
    source_id: UUID,
    payload: DraftReviewRequest,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
) -> DraftReviewResponse:
    """Patient confirms extracted fields; required for any activation."""
    patient_id = principal.patient_id
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
    principal: AuthenticatedPrincipal = Depends(get_principal),
    session_id: UUID = Query(),
    container: ApplicationContainer = Depends(get_container),
) -> ConfirmChallengeResponse:
    """Issue a single-use confirmation challenge bound to the session version.

    The session is first moved to ``awaiting_confirmation``; the version it
    returns is what the client must echo back on activation.
    """
    patient_id = principal.patient_id
    session = container.orchestrator.get_session(patient_id=patient_id, session_id=session_id)
    if session is None:
        raise NotFoundError(f"Agent session {session_id} not found for this patient")

    regimen = container.enrollment.get_regimen(patient_id, regimen_id)
    if regimen is None:
        raise NotFoundError(f"Regimen {regimen_id} not found")

    session = container.orchestrator.await_confirmation(patient_id=patient_id, session_id=session_id)
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
            "course_start_date": regimen.course_start_date,
            "food_instruction": regimen.food_instruction,
            "course_end_date": regimen.course_end_date,
        },
    )


@router.post("/medications/activate", response_model=ConfirmActivateResponse)
def activate(
    payload: ConfirmActivateRequest,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
) -> ConfirmActivateResponse:
    """Consume a confirmed challenge and activate the regimen version."""
    patient_id = principal.patient_id
    container.enrollment.confirm_challenge(patient_id=patient_id, challenge_id=payload.challenge_id)
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


def _medication_name(container: ApplicationContainer, patient_id: UUID, regimen) -> str:
    medication = container.enrollment.get_medication(patient_id, regimen.patient_medication_id)
    return medication.display_name if medication else "Unknown medication"
