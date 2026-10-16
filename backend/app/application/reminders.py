"""Persist an occurrence-bound snooze preference; never modify regimen/intake."""

from datetime import timedelta
from uuid import UUID

from ..contracts.enums import OccurrenceStatus, RegimenState
from ..contracts.ports import Clock, DoseOccurrenceRepository, RegimenVersionRepository
from ..contracts.reminders import ReminderDTO, ReminderRepository, ReminderStatusDTO
from ..domain.errors import NotFoundError, ValidationError
from .timezone import LOCAL_TZ_PROVIDER, LocalTzProvider


class ReminderService:
    def __init__(
        self,
        *,
        repository: ReminderRepository,
        occurrences: DoseOccurrenceRepository,
        regimens: RegimenVersionRepository,
        clock: Clock,
        tz_provider: LocalTzProvider | None = None,
    ) -> None:
        self._repository, self._occurrences, self._regimens, self._clock = repository, occurrences, regimens, clock
        self._tz = tz_provider or LOCAL_TZ_PROVIDER

    def snooze(self, *, patient_id: UUID, occurrence_id: UUID, minutes: int) -> ReminderDTO:
        if not 1 <= minutes <= 1440:
            raise ValidationError("Reminder delay must be 1 to 1440 minutes")
        occurrence = self._occurrences.get(patient_id, occurrence_id)
        if occurrence is None:
            raise NotFoundError("Dose occurrence not found")
        regimen = self._regimens.get(patient_id, occurrence.regimen_id)
        if regimen is None or regimen.state != RegimenState.ACTIVE or occurrence.status == OccurrenceStatus.CLOSED:
            raise ValidationError("Only an open dose of a reviewed active regimen can be reminded")
        if (
            regimen.course_end_date
            and self._clock.now().astimezone(self._tz.local_tz(patient_id)).date() > regimen.course_end_date
        ):
            raise ValidationError("This recorded course has ended; review the current plan")
        return self._repository.save(
            ReminderDTO(
                patient_id=patient_id,
                occurrence_id=occurrence_id,
                remind_at=self._clock.now() + timedelta(minutes=minutes),
            )
        )

    def list_current(self, patient_id: UUID) -> list[ReminderStatusDTO]:
        rows = self._repository.list_for_patient(patient_id)
        current = []
        for row in rows:
            occurrence = self._occurrences.get(patient_id, row.occurrence_id)
            if occurrence is not None and occurrence.status != OccurrenceStatus.CLOSED:
                regimen = self._regimens.get(patient_id, occurrence.regimen_id)
                if regimen is not None and regimen.state == RegimenState.ACTIVE:
                    if (
                        regimen.course_end_date
                        and self._clock.now().astimezone(self._tz.local_tz(patient_id)).date() > regimen.course_end_date
                    ):
                        continue
                    current.append(ReminderStatusDTO(**row.model_dump(), is_due=row.remind_at <= self._clock.now()))
        return current
