"""Explicit patient-confirmed health notes; no dose or regimen write port."""

from datetime import datetime, timedelta
from uuid import UUID

from ..contracts.observations import HealthNoteReview, Observation, ObservationInput, ObservationRepository
from ..contracts.ports import Clock, PatientMedicationRepository
from ..domain.errors import NotFoundError, ValidationError
from ..domain.health_safety import needs_urgent_help_notice


class ObservationService:
    def __init__(self, repository: ObservationRepository, medications: PatientMedicationRepository, clock: Clock):
        self._repository, self._medications, self._clock = repository, medications, clock

    def prepare_review(self, patient_text: str) -> HealthNoteReview:
        # Preserve the patient's words, never a model-created diagnosis or cause.
        if not patient_text.strip() or len(patient_text.strip()) > 1000:
            raise ValidationError("Please describe your experience in at most 1000 characters")
        # A conditional help notice, not a diagnosis or validated triage system.
        return HealthNoteReview(
            description=patient_text.strip(), urgent_help_advised=needs_urgent_help_notice(patient_text)
        )

    def list(self, patient_id: UUID, start: datetime, end: datetime) -> list[Observation]:
        return self._repository.list(patient_id, start, end)

    def save(self, patient_id: UUID, values: ObservationInput) -> Observation:
        if not values.confirmed:
            raise ValidationError("Confirm before saving your health note")
        now = self._clock.now()
        if values.occurred_at > now + timedelta(minutes=5):
            raise ValidationError("A health note cannot describe a future observation")
        if values.medication_id and not self._medications.get(patient_id, values.medication_id):
            raise NotFoundError("Medication not found for this patient")
        previous = self._repository.get(patient_id, values.id)
        return self._repository.save(
            Observation(
                **values.model_dump(exclude={"confirmed"}),
                patient_id=patient_id,
                created_at=previous.created_at if previous else now,
                updated_at=now,
            )
        )

    def delete(self, patient_id: UUID, observation_id: UUID) -> None:
        if not self._repository.get(patient_id, observation_id):
            raise NotFoundError("Health note not found for this patient")
        self._repository.delete(patient_id, observation_id)
