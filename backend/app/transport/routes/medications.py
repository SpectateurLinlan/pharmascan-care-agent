"""Medication endpoints: list, draft, review, confirm, activate.

Every route is scoped to the identity resolved by ``get_principal``: a
verified Supabase JWT in ``AUTH_MODE=supabase``, or the explicitly
unauthenticated demo principal otherwise. Routes call application services
only — they never touch a repository or the DB.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from ...contracts.dose_display import DoseDisplay, DoseDisplayInput
from ...contracts.draft_deletion import DraftDeletionResult, DraftKind
from ...contracts.dto import FrequencyRuleDTO, RegimenDraftInput
from ...domain.dose_display import dose_display
from ...domain.errors import NotFoundError, ProviderUnavailableError
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


@router.post("/medications/dose-display", response_model=DoseDisplay)
def display_total(payload: DoseDisplayInput, principal: AuthenticatedPrincipal = Depends(get_principal)):
    """Read-only arithmetic, never selects a count or changes a regimen."""
    return dose_display(payload)


class RegimenHistoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    regimen_id: UUID
    display_name: str
    patient_edited: bool = False
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
    frequency_rule: FrequencyRuleDTO | None = None


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
                    patient_edited=regimen.patient_edited,
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
                    frequency_rule=regimen.frequency_rule,
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
                dose_basis=(
                    source.dose_basis
                    if regimen.source_id and (source := container.enrollment.get_source(patient_id, regimen.source_id))
                    else None
                ),
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
    medication_id: UUID | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
) -> DraftCreateResponse:
    """Create a draft. Missing required inputs keep it pending — never active."""
    patient_id = principal.patient_id
    if medication_id is not None:
        from ...domain.errors import ValidationError

        medication = container.enrollment.get_medication(patient_id, medication_id)
        if medication is None:
            raise NotFoundError("Medication not found")
        if medication.display_name != payload.medication_name:
            raise ValidationError("A changed product identity needs separate source reconciliation")

    frequency: FrequencyRuleDTO | None = None
    if payload.frequency_kind is not None:
        frequency = FrequencyRuleDTO(
            kind="interval" if payload.frequency_kind == "interval_hours" else payload.frequency_kind,
            local_times=list(payload.frequency_local_times),
            days_of_week=list(payload.frequency_days_of_week),
            every_hours=payload.frequency_every_hours,
        )

    result = container.enrollment.enroll_draft(
        dose_basis=payload.dose_basis,
        existing_medication_id=medication_id,
        extraction_evidence=payload.extraction_evidence,
        patient_id=patient_id,
        draft=RegimenDraftInput(
            patient_edited=payload.patient_edited,
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


class EndPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: Literal[True]


@router.post("/medications/{regimen_id}/end")
def end_plan(
    regimen_id: UUID,
    payload: EndPlanRequest,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    row = container.enrollment.end_regimen(patient_id=principal.patient_id, regimen_id=regimen_id)
    return {"regimen_id": row.id, "state": row.state}


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
            "local_timezone": container.schedule.local_timezone(patient_id),
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


class DeleteDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: Literal[True]


@router.delete("/medications/unfinished/{kind}/{target}", response_model=DraftDeletionResult)
def delete_unfinished(
    kind: DraftKind,
    target: UUID,
    payload: DeleteDraftRequest,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    if container.draft_deletion is None:
        raise ProviderUnavailableError("Draft deletion unavailable")
    return container.draft_deletion.delete(principal.patient_id, kind, target, payload.confirmed)
