"""Persist an occurrence-bound snooze preference; never modify regimen/intake."""

from datetime import timedelta
from uuid import UUID

from ..contracts.enums import OccurrenceStatus, RegimenState
from ..contracts.ports import Clock, DoseOccurrenceRepository, RegimenVersionRepository
from ..contracts.reminders import ReminderDTO, ReminderRepository, ReminderStatusDTO
from ..domain.errors import NotFoundError, ValidationError


class ReminderService:
    def __init__(
        self,
        *,
        repository: ReminderRepository,
        occurrences: DoseOccurrenceRepository,
        regimens: RegimenVersionRepository,
        clock: Clock,
    ) -> None:
        self._repository, self._occurrences, self._regimens, self._clock = repository, occurrences, regimens, clock

    def snooze(self, *, patient_id: UUID, occurrence_id: UUID, minutes: int) -> ReminderDTO:
        if not 1 <= minutes <= 1440:
            raise ValidationError("Reminder delay must be 1 to 1440 minutes")
        occurrence = self._occurrences.get(patient_id, occurrence_id)
        if occurrence is None:
            raise NotFoundError("Dose occurrence not found")
        regimen = self._regimens.get(patient_id, occurrence.regimen_id)
        if regimen is None or regimen.state != RegimenState.ACTIVE or occurrence.status == OccurrenceStatus.CLOSED:
            raise ValidationError("Only an open dose of a reviewed active regimen can be reminded")
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
                    current.append(ReminderStatusDTO(**row.model_dump(), is_due=row.remind_at <= self._clock.now()))
        return current
