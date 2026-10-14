"""Owned contact management only. No notification, verification or sharing side effect."""

from uuid import UUID

from ..contracts.caregivers import CaregiverContact, CaregiverCreate, CaregiverDetails, CaregiverRepository
from ..contracts.ports import Clock
from ..domain.errors import NotFoundError, ValidationError


class CaregiverService:
    def __init__(self, repository: CaregiverRepository, clock: Clock):
        self._repository, self._clock = repository, clock

    def list(self, patient_id: UUID) -> list[CaregiverContact]:
        return self._repository.list(patient_id)

    def create(self, patient_id: UUID, details: CaregiverCreate) -> CaregiverContact:
        previous = self._repository.get(patient_id, details.id)
        fields = CaregiverDetails.model_validate(details.model_dump(exclude={"id"})).model_dump()
        if previous:
            if any(getattr(previous, name) != value for name, value in fields.items()):
                raise ValidationError("Contact retry differs from the saved details.")
            return previous
        self._check_duplicate(patient_id, details)
        if len(self.list(patient_id)) >= 20:
            raise ValidationError("Up to 20 caregiver contacts can be saved.")
        saved = self._repository.create(
            CaregiverContact(
                **details.model_dump(),
                patient_id=patient_id,
                created_at=self._clock.now(),
                updated_at=self._clock.now(),
            )
        )
        if any(getattr(saved, name) != value for name, value in fields.items()):
            raise ValidationError("Contact retry differs from the saved details.")
        return saved

    def update(self, patient_id: UUID, contact_id: UUID, details: CaregiverDetails) -> CaregiverContact:
        previous = self._repository.get(patient_id, contact_id)
        if previous is None:
            raise NotFoundError("Caregiver contact not found.")
        self._check_duplicate(patient_id, details, except_id=contact_id)
        return self._repository.update(
            previous.model_copy(update={**details.model_dump(), "updated_at": self._clock.now()})
        )

    def delete(self, patient_id: UUID, contact_id: UUID) -> None:
        if self._repository.get(patient_id, contact_id) is None:
            raise NotFoundError("Caregiver contact not found.")
        self._repository.delete(patient_id, contact_id)

    def _check_duplicate(self, patient_id: UUID, details: CaregiverDetails, except_id: UUID | None = None) -> None:
        if any(
            row.id != except_id
            and (row.contact_type, row.contact_value) == (details.contact_type, details.contact_value)
            for row in self.list(patient_id)
        ):
            raise ValidationError("This contact is already saved.")
