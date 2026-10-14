"""Explicit preference operations with no regimen or intake authority."""

from uuid import UUID

from ..contracts.preferences import PreferenceRepository, Preferences, PreferenceUpdate


class PreferenceService:
    def __init__(self, repository: PreferenceRepository):
        self._repository = repository

    def get(self, patient_id: UUID) -> Preferences:
        return self._repository.get(patient_id)

    def save(self, patient_id: UUID, changes: PreferenceUpdate) -> Preferences:
        if changes.text_scale_percent is not None:
            changes = changes.model_copy(
                update={"text_size": "large" if changes.text_scale_percent >= 125 else "standard"}
            )
        elif changes.text_size is not None:
            changes = changes.model_copy(update={"text_scale_percent": 125 if changes.text_size == "large" else 100})
        return self._repository.save(patient_id, changes)
