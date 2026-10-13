"""Due-dose lookup, self-report and dose history endpoints.

Invariants surfaced to the client explicitly:
- a self report is never proof of ingestion;
- ``visual_status`` stays ``not_checked`` in this build (no photo path);
- an unreported dose is not a missed dose.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from ...contracts.dto import DoseEventInput
from ...domain.errors import NotFoundError
from ...domain.policy import intake_status_from_patient_choice
from ..container import demo_patient_id
from ..deps import ApplicationContainer, get_container
from ..schemas import (
    DoseHistoryEntryResponse,
    DoseHistoryResponse,
    DueDoseResponse,
    SelfReportRequest,
    SelfReportResponse,
)

router = APIRouter(prefix="/api", tags=["doses"])


@router.get("/doses/due", response_model=DueDoseResponse)
def due_dose(
    regimen_id: UUID = Query(),
    client_id: str = Query(min_length=1, max_length=128),
    container: ApplicationContainer = Depends(get_container),
) -> DueDoseResponse:
    """Return the currently due occurrence for a regimen, if any.

    No dose being due is a normal answer, not an error.
    """
    patient_id = demo_patient_id(client_id)
    regimen = container.enrollment._regimens.get(patient_id, regimen_id)
    if regimen is None:
        raise NotFoundError(f"Regimen {regimen_id} not found")

    if regimen.is_prn:
        return DueDoseResponse(
            occurrence_id=None,
            regimen_id=regimen_id,
            medication_display_name=_display_name(container, patient_id, regimen.patient_medication_id),
            dose_description=None,
            due_at=None,
            is_prn=True,
        )

    container.schedule.materialize(patient_id=patient_id, regimen_id=regimen_id, days=2)
    due = container.schedule.find_due(patient_id=patient_id, regimen_id=regimen_id)
    occurrence = due.occurrence
    # find_due returns the schedule facts only; the display name is resolved
    # here from the medication record so the UI never renders a blank name.
    display_name = due.medication_display_name or _display_name(
        container, patient_id, regimen.patient_medication_id
    )
    return DueDoseResponse(
        occurrence_id=occurrence.id if occurrence else None,
        regimen_id=regimen_id,
        medication_display_name=display_name,
        dose_description=due.dose_description,
        due_at=occurrence.due_at if occurrence else None,
        is_prn=False,
    )


@router.post("/doses/{occurrence_id}/report", response_model=SelfReportResponse)
def report_dose(
    occurrence_id: UUID,
    payload: SelfReportRequest,
    client_id: str = Query(min_length=1, max_length=128),
    container: ApplicationContainer = Depends(get_container),
) -> SelfReportResponse:
    """Record what the patient said. Idempotent on the idempotency key."""
    patient_id = demo_patient_id(client_id)
    # Reject an unmappable patient choice instead of silently defaulting.
    intake = intake_status_from_patient_choice(payload.intake_status)
    outcome = container.self_report.report(
        patient_id=patient_id,
        payload=DoseEventInput(
            regimen_id=payload.regimen_id,
            occurrence_id=occurrence_id,
            intake_status=intake,
            event_time=container.clock.now(),
            idempotency_key=payload.idempotency_key,
        ),
    )
    event_id = outcome.event.id if outcome.event else outcome.existing_event_id
    return SelfReportResponse(
        event_id=event_id,
        intake_status=intake.value,
        visual_status="not_checked",
        already_recorded=outcome.already_recorded,
    )


@router.get("/me/dose-history", response_model=DoseHistoryResponse)
def dose_history(
    regimen_id: UUID = Query(),
    client_id: str = Query(min_length=1, max_length=128),
    days: int = Query(default=7, ge=1, le=90),
    container: ApplicationContainer = Depends(get_container),
) -> DoseHistoryResponse:
    patient_id = demo_patient_id(client_id)
    # Materialise first: a freshly activated regimen has occurrences only after
    # materialisation, and without this the history would render as an empty
    # list even though the patient has a real schedule. This is a read-side
    # materialisation of the *existing* rule set — it invents nothing.
    regimen = container.enrollment._regimens.get(patient_id, regimen_id)
    if regimen is None:
        raise NotFoundError(f"Regimen {regimen_id} not found")
    if not regimen.is_prn:
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
        )
        for entry in entries
    ]
    return DoseHistoryResponse(item_count=len(serialised), entries=serialised)


def _display_name(
    container: ApplicationContainer, patient_id: UUID, medication_id: UUID
) -> str:
    medication = container.enrollment._medications.get(patient_id, medication_id)
    return medication.display_name if medication else "Unknown medication"
