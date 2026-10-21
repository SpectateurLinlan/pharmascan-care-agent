"""Due-dose lookup, self-report confirmation and dose history endpoints.

Invariants surfaced to the client explicitly:
- a self report is never proof of ingestion;
- ``visual_status`` stays ``not_checked`` in this build (no photo path);
- an unreported dose is not a missed dose.

Recording a report is a **two-phase** flow (Session 3D, resolves B14):

1. ``POST /api/doses/{occurrence_id}/report/challenge`` issues a single-use
   ``record_self_report`` challenge and returns a human-readable summary of
   exactly what would be recorded. Nothing is written.
2. ``POST /api/doses/{occurrence_id}/report`` carries that ``challenge_id``:
   the server records the explicit confirmation, verifies the challenge, and
   writes the dose event citing it. The database consumes the challenge
   atomically with the insert.

The single-phase shortcut the build previously exposed could not work against
the real schema (``dose_events.confirmation_challenge_id`` is ``NOT NULL`` and
``core_guard_dose_event`` calls ``core_consume_confirmation``), and the fix was
to complete the lifecycle rather than to weaken the database.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from ...contracts.dto import DoseEventInput
from ...domain.errors import DuplicateEventError, NotFoundError
from ...domain.policy import intake_status_from_patient_choice
from ..auth import AuthenticatedPrincipal
from ..deps import ApplicationContainer, get_container, get_principal
from ..schemas import (
    DoseHistoryEntryResponse,
    DoseHistoryResponse,
    DueDoseResponse,
    ReportChallengeRequest,
    ReportChallengeResponse,
    ReportSummaryResponse,
    SelfReportRequest,
    SelfReportResponse,
)

router = APIRouter(prefix="/api", tags=["doses"])


@router.get("/doses/due", response_model=DueDoseResponse)
def due_dose(
    regimen_id: UUID = Query(),
    attention_only: bool = False,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
) -> DueDoseResponse:
    """Return the currently due occurrence for a regimen, if any.

    No dose being due is a normal answer, not an error.
    """
    patient_id = principal.patient_id
    regimen, due = container.schedule.read_due(
        patient_id=patient_id, regimen_id=regimen_id, attention_only=attention_only
    )

    if regimen.is_prn:
        return DueDoseResponse(
            occurrence_id=None,
            regimen_id=regimen_id,
            medication_display_name=_display_name(container, patient_id, regimen.patient_medication_id),
            dose_description=f"{regimen.dose_amount:g} {regimen.dose_unit or ''}"
            if regimen.dose_amount is not None
            else None,
            due_at=None,
            is_prn=True,
        )

    occurrence = due.occurrence
    # find_due returns the schedule facts only; the display name is resolved
    # here from the medication record so the UI never renders a blank name.
    display_name = due.medication_display_name or _display_name(container, patient_id, regimen.patient_medication_id)
    return DueDoseResponse(
        occurrence_id=occurrence.id if occurrence else None,
        regimen_id=regimen_id,
        medication_display_name=display_name,
        dose_description=f"{regimen.dose_amount:g} {regimen.dose_unit}" if regimen.dose_amount is not None else None,
        next_due_at=due.next_due_at,
        due_at=occurrence.due_at if occurrence else None,
        is_prn=False,
    )


@router.post(
    "/doses/{occurrence_id}/report/challenge",
    response_model=ReportChallengeResponse,
)
def request_report_challenge(
    occurrence_id: UUID | None,
    payload: ReportChallengeRequest,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    session_id: UUID | None = Query(default=None),
    container: ApplicationContainer = Depends(get_container),
) -> ReportChallengeResponse:
    """Phase 1: issue the confirmation challenge and show the summary.

    Writes nothing. An unmappable patient choice is rejected here rather than
    being defaulted, and a report that is already recorded is reported back as
    such instead of asking the patient to confirm it again.
    """
    patient_id = principal.patient_id
    intake = intake_status_from_patient_choice(payload.intake_status)

    existing = container.self_report.find_existing_report(
        patient_id=patient_id, idempotency_key=payload.idempotency_key
    )
    if existing is not None:
        if (
            existing.regimen_id != payload.regimen_id
            or existing.occurrence_id != occurrence_id
            or existing.intake_status != intake
        ):
            raise DuplicateEventError("Idempotency key belongs to a different report")
        return ReportChallengeResponse(
            challenge_id=None,
            occurrence_id=existing.occurrence_id,
            regimen_id=existing.regimen_id,
            session_id=session_id,
            session_state="completed",
            session_state_version=0,
            expires_at=None,
            summary=_summary_response(
                container.self_report.confirmation_summary(
                    patient_id=patient_id,
                    regimen_id=existing.regimen_id,
                    occurrence_id=existing.occurrence_id,
                    intake_status=existing.intake_status,
                )
            ),
            already_recorded=True,
            note=("This report was already recorded; the existing event is returned and nothing new was written."),
        )

    # The database requires the agent session to be in 'awaiting_confirmation'
    # with a version matching the challenge when the write consumes it, so the
    # session is moved there before the challenge is issued.
    prior_challenge = container.self_report.find_confirmation(
        patient_id=patient_id, idempotency_key=payload.idempotency_key
    )
    if prior_challenge is not None:
        session_id = prior_challenge.session_id
    session = (
        container.orchestrator.get_session(patient_id=patient_id, session_id=session_id)
        if session_id is not None
        else None
    )
    if session is None:
        session = container.orchestrator.start_session(patient_id=patient_id)
    if prior_challenge is None:
        session = container.orchestrator.await_confirmation(patient_id=patient_id, session_id=session.id)

    result = container.self_report.request_confirmation(
        patient_id=patient_id,
        regimen_id=payload.regimen_id,
        occurrence_id=occurrence_id,
        intake_status=intake,
        idempotency_key=payload.idempotency_key,
        session_id=session.id,
        session_state_version=session.state_version,
    )
    return ReportChallengeResponse(
        challenge_id=result.challenge.id,
        occurrence_id=result.challenge.occurrence_id,
        regimen_id=result.challenge.regimen_id,
        session_id=session.id,
        session_state=session.state,
        session_state_version=session.state_version,
        expires_at=result.challenge.expires_at,
        summary=_summary_response(result.summary),
    )


@router.post("/doses/{occurrence_id}/report", response_model=SelfReportResponse)
def report_dose(
    occurrence_id: UUID | None,
    payload: SelfReportRequest,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
) -> SelfReportResponse:
    """Phase 2: the patient's confirmation. Records the report.

    Idempotent on the idempotency key: replaying an already-saved report
    returns the existing event rather than failing for want of a fresh
    confirmation.
    """
    patient_id = principal.patient_id
    # Reject an unmappable patient choice instead of silently defaulting.
    intake = intake_status_from_patient_choice(payload.intake_status)

    # An idempotent replay is answered *before* any confirmation is required:
    # replaying a report that is already saved must not fail for want of a
    # fresh challenge. The stored event is returned verbatim.
    existing = container.self_report.find_existing_report(
        patient_id=patient_id, idempotency_key=payload.idempotency_key
    )
    if existing is not None:
        if (
            existing.regimen_id != payload.regimen_id
            or existing.occurrence_id != occurrence_id
            or existing.intake_status != intake
        ):
            raise DuplicateEventError("This idempotency key was already used for a different dose report")
        return SelfReportResponse(
            event_id=existing.id,
            intake_status=existing.intake_status.value,
            visual_status=existing.visual_status.value,
            already_recorded=True,
        )

    # An explicit confirmation of the summary the patient was shown. Refused
    # when the challenge is expired, consumed or bound to a different report.
    report = DoseEventInput(
        regimen_id=payload.regimen_id,
        occurrence_id=occurrence_id,
        intake_status=intake,
        event_time=container.clock.now(),
        idempotency_key=payload.idempotency_key,
    )
    container.self_report.confirm_report(patient_id=patient_id, payload=report, challenge_id=payload.challenge_id)
    outcome = container.self_report.report(
        patient_id=patient_id,
        payload=report,
        challenge_id=payload.challenge_id,
    )
    event_id = outcome.event.id if outcome.event else outcome.existing_event_id
    return SelfReportResponse(
        event_id=event_id,
        intake_status=intake.value,
        visual_status="not_checked",
        already_recorded=outcome.already_recorded,
    )


@router.post("/prn/report/challenge", response_model=ReportChallengeResponse)
def request_prn_report_challenge(
    payload: ReportChallengeRequest,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    session_id: UUID | None = Query(default=None),
    container: ApplicationContainer = Depends(get_container),
) -> ReportChallengeResponse:
    return request_report_challenge(None, payload, principal, session_id, container)


@router.post("/prn/report", response_model=SelfReportResponse)
def report_prn_dose(
    payload: SelfReportRequest,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
) -> SelfReportResponse:
    return report_dose(None, payload, principal, container)


@router.get("/me/dose-history", response_model=DoseHistoryResponse)
def dose_history(
    regimen_id: UUID = Query(),
    principal: AuthenticatedPrincipal = Depends(get_principal),
    days: int = Query(default=7, ge=1, le=90),
    container: ApplicationContainer = Depends(get_container),
) -> DoseHistoryResponse:
    patient_id = principal.patient_id
    # Materialise first: a freshly activated regimen has occurrences only after
    # materialisation, and without this the history would render as an empty
    # list even though the patient has a real schedule. This is a read-side
    # materialisation of the *existing* rule set — it invents nothing.
    regimen = container.enrollment.get_regimen(patient_id, regimen_id)
    if regimen is None:
        raise NotFoundError(f"Regimen {regimen_id} not found")
    if not regimen.is_prn and str(regimen.state) == "active":
        container.schedule.materialize(patient_id=patient_id, regimen_id=regimen_id, days=days)
    now = container.clock.now()
    entries = container.self_report.history(
        patient_id=patient_id,
        regimen_id=regimen_id,
        window_start=now - timedelta(days=days),
        window_end=now + timedelta(days=1),
    )
    serialised = [
        DoseHistoryEntryResponse(
            occurrence_id=entry.occurrence.id if entry.occurrence else None,
            due_at=entry.occurrence.due_at if entry.occurrence else None,
            intake_status=entry.event.intake_status.value if entry.event else None,
            visual_status=entry.event.visual_status.value if entry.event else None,
            reported=entry.event is not None,
            event_time=entry.event.event_time if entry.event else None,
        )
        for entry in entries
    ]
    return DoseHistoryResponse(item_count=len(serialised), entries=serialised)


def _display_name(container: ApplicationContainer, patient_id: UUID, medication_id: UUID) -> str:
    medication = container.enrollment.get_medication(patient_id, medication_id)
    return medication.display_name if medication else "Unknown medication"


def _summary_response(summary) -> ReportSummaryResponse:
    """Adapt the application DTO to the transport schema.

    Explicit rather than implicit: the transport must not start accepting the
    application DTO as a response type, or a change to the DTO would silently
    change the public API.
    """
    return ReportSummaryResponse(**summary.model_dump())
