"""Injected in-memory and same-JWT profile adapters. No admin fallback."""

from contextlib import contextmanager
from copy import deepcopy
from threading import RLock
from uuid import UUID

from ..contracts.ports import Clock
from ..contracts.preferences import Preferences, PreferenceUpdate
from ..domain.errors import NotFoundError, ProviderUnavailableError
from .clinical_memory import ClinicalMemory
from .supabase_data import SupabaseDataClient


class MemoryPreferences:
    def __init__(self, *, rows: dict[UUID, Preferences], clock: Clock, coordination: ClinicalMemory | None = None):
        self._rows, self._clock = rows, clock
        self._coordination = coordination
        self._lock, self._revisions = coordination.lock if coordination is not None else RLock(), {}

    def revision(self, owner):
        with self._lock:
            return self._revisions.get(owner, 0)

    @contextmanager
    def history_fence(self):
        with self._lock:
            yield

    @contextmanager
    def local_transaction(self):
        with self._lock:
            rows, revisions = deepcopy(self._rows), dict(self._revisions)
            clinical = dict(self._coordination.revisions) if self._coordination is not None else None
            try:
                yield
            except BaseException:
                self._rows.clear()
                self._rows.update(rows)
                self._revisions.clear()
                self._revisions.update(revisions)
                if clinical is not None:
                    self._coordination.revisions.clear()
                    self._coordination.revisions.update(clinical)
                raise

    def get(self, patient_id: UUID) -> Preferences:
        with self._lock:
            if patient_id not in self._rows:
                self._rows[patient_id] = Preferences(
                    patient_id=patient_id, created_at=self._clock.now(), updated_at=self._clock.now()
                )
            return self._rows[patient_id]

    def save(self, patient_id: UUID, changes: PreferenceUpdate) -> Preferences:
        with self._lock:
            values = changes.model_dump(exclude_none=True)
            language = values.get("preferred_language", self.get(patient_id).preferred_language)
            row = self.get(patient_id).model_copy(
                update={
                    **values,
                    "speech_locale": "zh-CN" if language == "zh" else "en-SG",
                    "updated_at": self._clock.now(),
                }
            )
            self._rows[patient_id] = row
            self._revisions[patient_id] = self._revisions.get(patient_id, 0) + 1
            if self._coordination is not None:
                self._coordination.revisions[patient_id] = self._coordination.revisions.get(patient_id, 0) + 1
            return row


class SupabasePreferences:
    def __init__(self, client: SupabaseDataClient):
        self._client = client
        self._value: Preferences | None = None

    def history_fence(self):
        raise ProviderUnavailableError("Remote history retention requires the fixed database message transaction")

    def get(self, patient_id: UUID) -> Preferences:
        self._client.check_patient(patient_id)
        if self._value is not None:
            return self._value
        rows = self._client.rows("patient_profiles", user_id=f"eq.{patient_id}")
        if not rows:
            raise NotFoundError("Patient preferences not found")
        row = rows[0]
        self._value = Preferences(
            patient_id=row["user_id"],
            display_name=row.get("display_name"),
            preferred_language=row["language"],
            speech_locale=row["speech_locale"],
            text_size=row["text_size"],
            text_scale_percent=row.get("text_scale_percent", 125 if row["text_size"] == "large" else 100),
            voice_enabled=row["voice_enabled"],
            tts_autoplay=row["tts_autoplay"],
            conversation_history_enabled=row.get("conversation_history_enabled", False),
            reminder_lead_minutes=row["reminder_lead_minutes"],
            reminders_enabled=row.get("reminders_enabled", True),
            timezone=row["timezone"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        return self._value

    def save(self, patient_id: UUID, changes: PreferenceUpdate) -> Preferences:
        self._client.check_patient(patient_id)
        self._value = None
        values = changes.model_dump(exclude_none=True)
        if "preferred_language" in values:
            values["language"] = values.pop("preferred_language")
        if values:
            self._client.request(
                "PATCH", "/rest/v1/patient_profiles", params={"user_id": f"eq.{patient_id}"}, body=values
            )
        return self.get(patient_id)
