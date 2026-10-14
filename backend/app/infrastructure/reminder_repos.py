"""Implementations of the reminder preference port."""

from uuid import UUID

from ..contracts.reminders import ReminderDTO
from .memory_repos import InMemoryStore
from .supabase_data import SupabaseDataClient


class MemoryReminderRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    def save(self, reminder: ReminderDTO) -> ReminderDTO:
        self._store.reminders[(reminder.patient_id, reminder.occurrence_id)] = reminder
        return reminder

    def list_for_patient(self, patient_id: UUID) -> list[ReminderDTO]:
        return [row for (owner, _), row in self._store.reminders.items() if owner == patient_id]


class SupabaseReminderRepository:
    def __init__(self, client: SupabaseDataClient) -> None:
        self._client = client

    def save(self, reminder: ReminderDTO) -> ReminderDTO:
        self._client.check_patient(reminder.patient_id)
        rows = self._client.request(
            "POST",
            "/rest/v1/dose_reminders",
            params={"on_conflict": "patient_id,occurrence_id"},
            body=reminder.model_dump(mode="json"),
            prefer="resolution=merge-duplicates,return=representation",
        )
        return ReminderDTO.model_validate(rows[0])

    def list_for_patient(self, patient_id: UUID) -> list[ReminderDTO]:
        self._client.check_patient(patient_id)
        return [ReminderDTO.model_validate(row) for row in self._client.rows("dose_reminders", order="remind_at")]
