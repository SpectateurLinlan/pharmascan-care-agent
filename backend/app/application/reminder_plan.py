"""One deterministic projection for in-app reminders, calendar and push workers."""

from datetime import date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from ..contracts.enums import OccurrenceStatus, RegimenState
from ..contracts.ports import Clock, DoseEventRepository, PatientMedicationRepository, RegimenVersionRepository
from ..domain.errors import ValidationError
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

    def calendar_export_rows(
        self,
        patient_id: UUID,
        *,
        lead_minutes: int,
        start_date: date,
        end_date: date | None,
        full_remaining_course: bool = False,
        include_medications: bool = True,
    ) -> tuple[list[PlannedReminder], date]:
        """Read-only projection of future medication events for a calendar file."""
        if not 0 <= lead_minutes <= 120:
            raise ValidationError("Reminder lead time is outside supported bounds.")
        if not full_remaining_course and (end_date is None or end_date < start_date):
            raise ValidationError("The calendar end date must be on or after the start date.")

        now = self._clock.now()
        zone = ZoneInfo(self._schedule.local_timezone(patient_id))
        today = now.astimezone(zone).date()
        if start_date < today:
            raise ValidationError("Calendar exports can only include today or future dates.")
        start_at = max(now, datetime.combine(start_date, time.min, tzinfo=zone))
        snoozes = {row.occurrence_id: row for row in self._reminders.list_current(patient_id)}
        result: list[PlannedReminder] = []
        latest_end = None if full_remaining_course else end_date

        for medication in self._medications.list_for_patient(patient_id):
            for regimen in self._regimens.list_for_medication(patient_id, medication.id):
                if regimen.state != RegimenState.ACTIVE or regimen.is_prn:
                    continue
                if full_remaining_course:
                    course_end = regimen.course_end_date or (start_date + timedelta(days=89))
                    if course_end < start_date:
                        continue
                    effective_end = course_end
                    latest_end = max(latest_end or effective_end, effective_end)
                else:
                    effective_end = end_date
                assert effective_end is not None
                if not include_medications:
                    continue
                course_start = max(start_date, regimen.course_start_date or start_date)
                if course_start > effective_end:
                    continue
                lower = max(start_at, datetime.combine(course_start, time.min, tzinfo=zone))
                upper = datetime.combine(effective_end + timedelta(days=1), time.min, tzinfo=zone)
                if lower >= upper:
                    continue
                occurrences = self._schedule.calendar_occurrences(
                    patient_id=patient_id,
                    regimen_id=regimen.id,
                    start=lower,
                    end=upper,
                    limit=max(0, 500 - len(result)),
                )
                for occurrence in occurrences:
                    if occurrence.status == OccurrenceStatus.CLOSED or self._events.find_by_occurrence(
                        patient_id, occurrence.id
                    ):
                        continue
                    snooze = snoozes.get(occurrence.id)
                    remind_at = snooze.remind_at if snooze else occurrence.due_at - timedelta(minutes=lead_minutes)
                    if remind_at < now - timedelta(minutes=15):
                        continue
                    result.append(
                        PlannedReminder(
                            occurrence_id=occurrence.id,
                            regimen_id=regimen.id,
                            rule_id=occurrence.rule_id,
                            medication_name=medication.display_name,
                            due_at=occurrence.due_at,
                            remind_at=remind_at,
                            expires_at=None,
                            slot=snooze.remind_at.isoformat() if snooze else "scheduled",
                        )
                    )
                    if len(result) > 500:
                        raise ValidationError(
                            "Calendar export exceeds 500 events. Choose a shorter date range "
                            "or remove an export category."
                        )
        if full_remaining_course and latest_end is None:
            latest_end = start_date + timedelta(days=89)
        ordered = sorted(result, key=lambda row: (row.due_at, str(row.regimen_id), str(row.rule_id)))
        return ordered, latest_end or start_date
