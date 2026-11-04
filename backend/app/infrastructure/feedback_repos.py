"""In-memory tests and user-JWT/RLS feedback persistence. No admin fallback."""

from contextlib import contextmanager
from copy import deepcopy
from threading import RLock
from uuid import UUID

from ..contracts.patient_feedback import PatientFeedback
from ..domain.errors import ValidationError
from .supabase_data import SupabaseDataClient


class MemoryFeedback:
    def __init__(self, rows: dict[tuple[UUID, UUID], PatientFeedback]):
        self._rows = rows
        self._lock, self._revisions = RLock(), {}

    def revision(self, owner):
        with self._lock:
            return self._revisions.get(owner, 0)

    @contextmanager
    def local_transaction(self):
        with self._lock:
            rows, revisions = deepcopy(self._rows), dict(self._revisions)
            try:
                yield
            except BaseException:
                self._rows.clear()
                self._rows.update(rows)
                self._revisions.clear()
                self._revisions.update(revisions)
                raise

    def save(self, row: PatientFeedback) -> PatientFeedback:
        with self._lock:
            key = row.patient_id, row.id
            existing = self._rows.get(key)
            if existing and (existing.category, existing.message) != (row.category, row.message):
                raise ValidationError("Feedback retry differs from the submitted message")
            if existing is None:
                self._rows[key] = row
                self._revisions[row.patient_id] = self._revisions.get(row.patient_id, 0) + 1
            return self._rows[key]

    def get(self, patient_id: UUID, feedback_id: UUID) -> PatientFeedback | None:
        with self._lock:
            return self._rows.get((patient_id, feedback_id))


class SupabaseFeedback:
    def __init__(self, client: SupabaseDataClient):
        self._client = client

    def get(self, patient_id: UUID, feedback_id: UUID) -> PatientFeedback | None:
        self._client.check_patient(patient_id)
        rows = self._client.rows("patient_feedback", patient_id=f"eq.{patient_id}", id=f"eq.{feedback_id}")
        return PatientFeedback.model_validate(rows[0]) if rows else None

    def save(self, row: PatientFeedback) -> PatientFeedback:
        self._client.check_patient(row.patient_id)
        self._client.request(
            "POST",
            "/rest/v1/patient_feedback",
            params={"on_conflict": "patient_id,id"},
            body=row.model_dump(mode="json"),
            prefer="resolution=ignore-duplicates,return=minimal",
        )
        result = PatientFeedback.model_validate(self._client.rows("patient_feedback", id=f"eq.{row.id}")[0])
        if (result.category, result.message) != (row.category, row.message):
            raise ValidationError("Feedback retry differs from the submitted message")
        return result
