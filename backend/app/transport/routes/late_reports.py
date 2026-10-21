"""Patient-only late reports: explicit two-phase confirmation, never Agent replay."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from ...contracts.late_reports import (
    DoseFollowUps,
    DoseReportAudit,
    LateReportChallenge,
    LateReportConfirmation,
    LateReportInput,
    LateReportRecord,
)
from ...domain.errors import ProviderUnavailableError
from ...timing import timed_stage
from ..auth import AuthenticatedPrincipal
from ..deps import ApplicationContainer, get_container, get_principal

router = APIRouter(prefix="/api/me", tags=["dose-follow-ups"])


def service(container):
    if container.late_reports is None:
        raise ProviderUnavailableError("Dose report follow-ups are unavailable")
    return container.late_reports


@router.get("/dose-follow-ups", response_model=DoseFollowUps)
def recent(
    include_reported: bool = Query(default=False),
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    with timed_stage("business"):
        return service(container).recent(principal.patient_id, include_reported)


@router.get("/doses/{occurrence_id}/late-reports", response_model=DoseReportAudit)
def history(
    occurrence_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    care = service(container)
    care.occurrence(principal.patient_id, occurrence_id)
    return DoseReportAudit(
        original=care.repository.original(principal.patient_id, occurrence_id),
        corrections=care.repository.history(principal.patient_id, occurrence_id),
    )


@router.post("/doses/{occurrence_id}/late-report/challenge", response_model=LateReportChallenge)
def prepare(
    occurrence_id: UUID,
    values: LateReportInput,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    care = service(container)
    care.validate(principal.patient_id, occurrence_id, values)
    session = container.orchestrator.start_session(patient_id=principal.patient_id)
    session = container.orchestrator.await_confirmation(patient_id=principal.patient_id, session_id=session.id)
    return care.prepare(principal.patient_id, occurrence_id, values, session)


@router.post("/doses/{occurrence_id}/late-report", response_model=LateReportRecord)
def confirm(
    occurrence_id: UUID,
    values: LateReportConfirmation,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    return service(container).confirm(principal.patient_id, occurrence_id, values.report, values.challenge_id)
