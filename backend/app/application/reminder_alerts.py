"""Scheduled/snoozed alerts from reviewed occurrences and injected server time."""

from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from ..contracts.enums import OccurrenceStatus
from ..contracts.ports import Clock, DoseEventRepository, DoseOccurrenceRepository
from .dosing import DoseScheduleService
from .enrollment import MedicationEnrollmentService
from .reminders import ReminderService


class DoseReminderAlert(BaseModel):
    key: str
    occurrence_id: UUID
    regimen_id: UUID
    medication_name: str
    dose_amount: float | None
    dose_unit: str | None
    food_instruction: str | None
    due_at: datetime
    remind_at: datetime
    expires_at: datetime


class ReminderAlertService:
    def __init__(
        self,
        *,
        enrollment: MedicationEnrollmentService,
        schedule: DoseScheduleService,
        occurrences: DoseOccurrenceRepository,
        events: DoseEventRepository,
        reminders: ReminderService,
        clock: Clock,
    ):
        self._enrollment, self._schedule, self._occurrences, self._events, self._reminders, self._clock = (
            enrollment,
            schedule,
            occurrences,
            events,
            reminders,
            clock,
        )

    def current(self, patient_id: UUID, *, lead_minutes: int, timezone: str) -> list[DoseReminderAlert]:
        now = self._clock.now()
        start = now.astimezone(ZoneInfo(timezone)).replace(hour=0, minute=0, second=0, microsecond=0)
        snoozes = {row.occurrence_id: row for row in self._reminders.list_current(patient_id)}
        alerts = []
        for medication in self._enrollment.list_medications(patient_id):
            regimen = self._enrollment.find_active_regimen(patient_id, medication.id)
            if regimen is None or regimen.is_prn:
                continue
            if regimen.course_end_date and now.astimezone(ZoneInfo(timezone)).date() > regimen.course_end_date:
                continue
            self._schedule.materialize(patient_id=patient_id, regimen_id=regimen.id, days=2)
            rows = {
                row.id: row
                for row in self._occurrences.list_for_regimen(
                    patient_id, regimen.id, start, now + timedelta(minutes=lead_minutes, seconds=1)
                )
            }
            for snooze in snoozes.values():
                if snooze.is_due:
                    occurrence = self._occurrences.get(patient_id, snooze.occurrence_id)
                    if occurrence and occurrence.regimen_id == regimen.id:
                        rows[occurrence.id] = occurrence
            for occurrence in rows.values():
                if occurrence.status == OccurrenceStatus.CLOSED or self._events.find_by_occurrence(
                    patient_id, occurrence.id
                ):
                    continue
                snooze = snoozes.get(occurrence.id)
                if snooze and not snooze.is_due:
                    continue
                reminder_time = snooze.remind_at if snooze else occurrence.due_at - timedelta(minutes=lead_minutes)
                deadline = self._reminders.deadline(patient_id, occurrence)
                if now >= deadline or reminder_time >= deadline or reminder_time > now:
                    continue
                alerts.append(
                    DoseReminderAlert(
                        key=f"{occurrence.id}:{reminder_time.isoformat()}",
                        occurrence_id=occurrence.id,
                        regimen_id=regimen.id,
                        medication_name=medication.display_name,
                        dose_amount=regimen.dose_amount,
                        dose_unit=regimen.dose_unit,
                        food_instruction=regimen.food_instruction,
                        due_at=occurrence.due_at,
                        remind_at=reminder_time,
                        expires_at=deadline,
                    )
                )
        return sorted(alerts, key=lambda row: row.remind_at)
