"""Store explicitly submitted feedback through an owned repository port."""

from uuid import UUID

from ..contracts.patient_feedback import FeedbackInput, FeedbackRepository, PatientFeedback
from ..contracts.ports import Clock
from ..domain.errors import ValidationError


class FeedbackService:
    def __init__(self, repository: FeedbackRepository, clock: Clock):
        self._repository, self._clock = repository, clock

    def submit(self, patient_id: UUID, payload: FeedbackInput) -> PatientFeedback:
        if len(payload.message.strip()) < 5:
            raise ValidationError("Please enter at least five characters")
        return self._repository.save(
            PatientFeedback(**payload.model_dump(), patient_id=patient_id, created_at=self._clock.now())
        )
