"""One deterministic projection for in-app reminders, calendar and push workers."""

from datetime import datetime, timedelta
from uuid import UUID

from pydantic import BaseModel

from ..contracts.enums import OccurrenceStatus, RegimenState
from ..contracts.ports import Clock, DoseEventRepository, PatientMedicationRepository, RegimenVersionRepository
from .dosing import DoseScheduleService
from .reminders import ReminderService


class PlannedReminder(BaseModel):
    occurrence_id: UUID
    regimen_id: UUID
    rule_id: UUID
    medication_name: str
    due_at: datetime
    remind_at: datetime
    slot: str = "scheduled"
    expires_at: datetime | None = None


class ReminderPlanService:
    def __init__(
        self,
        *,
        medications: PatientMedicationRepository,
        regimens: RegimenVersionRepository,
        schedule: DoseScheduleService,
        events: DoseEventRepository,
        reminders: ReminderService,
        clock: Clock,
    ):
        self._medications, self._regimens = medications, regimens
        self._schedule, self._events, self._reminders, self._clock = schedule, events, reminders, clock

    def upcoming(self, patient_id: UUID, *, lead_minutes: int, days: int = 7) -> list[PlannedReminder]:
        if not 1 <= days <= 31 or not 0 <= lead_minutes <= 120:
            raise ValueError("Reminder window or lead is outside supported bounds")
        now = self._clock.now()
        snoozes = {row.occurrence_id: row for row in self._reminders.list_current(patient_id)}
        result = []
        for medication in self._medications.list_for_patient(patient_id):
            for regimen in self._regimens.list_for_medication(patient_id, medication.id):
                if regimen.state != RegimenState.ACTIVE or regimen.is_prn:
                    continue
                for occurrence in self._schedule.materialize(patient_id=patient_id, regimen_id=regimen.id, days=days):
                    if occurrence.status == OccurrenceStatus.CLOSED or self._events.find_by_occurrence(
                        patient_id, occurrence.id
                    ):
                        continue
                    snooze = snoozes.get(occurrence.id)
                    remind_at = snooze.remind_at if snooze else occurrence.due_at - timedelta(minutes=lead_minutes)
                    # Expired notifications must not be replayed after a long outage.
                    deadline = self._reminders.deadline(patient_id, occurrence)
                    if now >= deadline or remind_at >= deadline or remind_at < now - timedelta(minutes=15):
                        continue
                    result.append(
                        PlannedReminder(
                            occurrence_id=occurrence.id,
                            regimen_id=regimen.id,
                            rule_id=occurrence.rule_id,
                            medication_name=medication.display_name,
                            due_at=occurrence.due_at,
                            remind_at=remind_at,
                            expires_at=deadline,
                            slot=snooze.remind_at.isoformat() if snooze else "scheduled",
                        )
                    )
        return sorted(result, key=lambda row: row.remind_at)
