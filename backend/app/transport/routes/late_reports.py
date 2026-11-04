"""Patient-only late reports: explicit two-phase confirmation, never Agent replay."""

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query

from ...contracts.late_reports import (
    DoseFollowUps,
    DoseReportAudit,
    LateReportChallenge,
    LateReportConfirmation,
    LateReportInput,
    LateReportRecord,
)
from ...domain.errors import ProviderUnavailableError, ValidationError
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
    return care.audit(principal.patient_id, occurrence_id)


def _bound(container, owner, task, revision, occurrence_id, values, challenge_id, write):
    if task is None and revision is None:
        return write()
    if task is None or revision is None or container.assistant_late_reports is None:
        raise ValidationError("The historical review needs its current Assistant task and revision")
    return container.assistant_late_reports.run(owner, task, revision, occurrence_id, values, challenge_id, write)


@router.post("/doses/{occurrence_id}/late-report/challenge", response_model=LateReportChallenge)
def prepare(
    occurrence_id: UUID,
    values: LateReportInput,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
    assistant_task: UUID | None = Header(default=None, alias="X-Assistant-Task"),
    assistant_revision: int | None = Header(default=None, ge=1, alias="X-Assistant-Revision"),
):
    def write():
        care = service(container)
        care.validate(principal.patient_id, occurrence_id, values)
        session = container.orchestrator.start_session(patient_id=principal.patient_id)
        session = container.orchestrator.await_confirmation(patient_id=principal.patient_id, session_id=session.id)
        return care.prepare(principal.patient_id, occurrence_id, values, session)

    return _bound(
        container, principal.patient_id, assistant_task, assistant_revision, occurrence_id, values, None, write
    )


@router.post("/doses/{occurrence_id}/late-report", response_model=LateReportRecord)
def confirm(
    occurrence_id: UUID,
    values: LateReportConfirmation,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
    assistant_task: UUID | None = Header(default=None, alias="X-Assistant-Task"),
    assistant_revision: int | None = Header(default=None, ge=1, alias="X-Assistant-Revision"),
):
    return _bound(
        container,
        principal.patient_id,
        assistant_task,
        assistant_revision,
        occurrence_id,
        values.report,
        values.challenge_id,
        lambda: service(container).confirm(principal.patient_id, occurrence_id, values.report, values.challenge_id),
    )
