"""Explicit preference operations with no regimen or intake authority."""

from uuid import UUID

from ..contracts.preferences import PreferenceRepository, Preferences, PreferenceUpdate


class PreferenceService:
    def __init__(self, repository: PreferenceRepository):
        self._repository = repository

    def get(self, patient_id: UUID) -> Preferences:
        return self._repository.get(patient_id)

    def save(self, patient_id: UUID, changes: PreferenceUpdate) -> Preferences:
        return self._repository.save(patient_id, changes)
