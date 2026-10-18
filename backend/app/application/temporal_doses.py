"""Calendar reads through public services; preserve original occurrence ownership."""

from datetime import date, datetime
from uuid import UUID

from ..contracts.dto import DoseHistoryEntryDTO, RegimenVersionDTO
from ..contracts.enums import RegimenState
from ..contracts.ports import Clock
from ..contracts.temporal import local_day_window
from ..domain.errors import ValidationError
from .dosing import DoseScheduleService, SelfReportService
from .enrollment import MedicationEnrollmentService


class TemporalDoseReader:
    def __init__(
        self,
        *,
        enrollment: MedicationEnrollmentService,
        schedule: DoseScheduleService,
        reports: SelfReportService,
        clock: Clock,
    ) -> None:
        self._enrollment = enrollment
        self._schedule = schedule
        self._reports = reports
        self._clock = clock

    def read_day(
        self, patient_id: UUID, medication_id: UUID, day: date
    ) -> tuple[list[RegimenVersionDTO], list[DoseHistoryEntryDTO]]:
        start, end = local_day_window(day, self._schedule.local_timezone(patient_id))
        if start > self._clock.now():
            raise ValidationError("A future date is not dose history")
        plans, entries = [], []
        versions = self._enrollment.list_regimens(patient_id, medication_id)
        if len(versions) > 100:
            raise ValidationError("Too many plan versions for this calendar read; select a plan in Records")
        for plan in versions:
            if plan.state in {RegimenState.DRAFT, RegimenState.PENDING_CLARIFICATION}:
                continue
            applicable = self.applies(plan, day, start, end)
            if applicable:
                plans.append(plan)
                if start <= self._clock.now() < end and plan.state == RegimenState.ACTIVE and not plan.is_prn:
                    self._schedule.materialize(patient_id=patient_id, regimen_id=plan.id, days=1)
            rows = self._reports.history(patient_id=patient_id, regimen_id=plan.id, window_start=start, window_end=end)
            for row in rows:
                instant = row.occurrence.due_at if row.occurrence else row.event.event_time if row.event else None
                if instant and (row.event or (applicable and self.at_instant(plan, instant))):
                    entries.append(row)
        entries.sort(
            key=lambda row: (row.occurrence.due_at if row.occurrence else row.event.event_time, str(row.regimen_id)),
            reverse=True,
        )
        plans.sort(key=lambda plan: (plan.effective_from, str(plan.id)), reverse=True)
        return plans, entries

    @staticmethod
    def applies(plan: RegimenVersionDTO, day: date, start: datetime, end: datetime) -> bool:
        return bool(
            plan.effective_from is not None
            and plan.effective_from < end
            and (plan.effective_to is None or plan.effective_to > start)
            and (plan.course_start_date is None or plan.course_start_date <= day)
            and (plan.course_end_date is None or day <= plan.course_end_date)
        )

    @staticmethod
    def at_instant(plan: RegimenVersionDTO, instant: datetime) -> bool:
        return bool(
            plan.effective_from is not None
            and plan.effective_from <= instant
            and (plan.effective_to is None or instant < plan.effective_to)
        )
