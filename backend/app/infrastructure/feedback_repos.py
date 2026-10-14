"""In-memory tests and user-JWT/RLS feedback persistence. No admin fallback."""

from uuid import UUID

from ..contracts.patient_feedback import PatientFeedback
from ..domain.errors import ValidationError
from .supabase_data import SupabaseDataClient


class MemoryFeedback:
    def __init__(self, rows: dict[tuple[UUID, UUID], PatientFeedback]):
        self._rows = rows

    def save(self, row: PatientFeedback) -> PatientFeedback:
        existing = self._rows.get((row.patient_id, row.id))
        if existing and (existing.category, existing.message) != (row.category, row.message):
            raise ValidationError("Feedback retry differs from the submitted message")
        self._rows.setdefault((row.patient_id, row.id), row)
        return self._rows[(row.patient_id, row.id)]


class SupabaseFeedback:
    def __init__(self, client: SupabaseDataClient):
        self._client = client

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
