"""Injected deterministic memory and same-user JWT/RLS contact adapters."""

from uuid import UUID

from ..contracts.caregivers import CaregiverContact
from ..domain.errors import NotFoundError, ValidationError
from .supabase_data import SupabaseDataClient


class MemoryCaregivers:
    def __init__(self):
        self._rows: dict[tuple[UUID, UUID], CaregiverContact] = {}

    def list(self, patient_id: UUID) -> list[CaregiverContact]:
        return [row for row in self._rows.values() if row.patient_id == patient_id]

    def get(self, patient_id: UUID, contact_id: UUID) -> CaregiverContact | None:
        return self._rows.get((patient_id, contact_id))

    def create(self, row: CaregiverContact) -> CaregiverContact:
        self._rows.setdefault((row.patient_id, row.id), row)
        return self._rows[(row.patient_id, row.id)]

    def update(self, row: CaregiverContact) -> CaregiverContact:
        self._rows[(row.patient_id, row.id)] = row
        return row

    def delete(self, patient_id: UUID, contact_id: UUID) -> None:
        self._rows.pop((patient_id, contact_id), None)


class SupabaseCaregivers:
    def __init__(self, client: SupabaseDataClient):
        self._client = client

    def list(self, patient_id: UUID) -> list[CaregiverContact]:
        self._client.check_patient(patient_id)
        return [
            CaregiverContact.model_validate(row)
            for row in self._client.rows("caregiver_contacts", order="created_at.asc")
        ]

    def get(self, patient_id: UUID, contact_id: UUID) -> CaregiverContact | None:
        self._client.check_patient(patient_id)
        rows = self._client.rows("caregiver_contacts", id=f"eq.{contact_id}")
        return CaregiverContact.model_validate(rows[0]) if rows else None

    def create(self, row: CaregiverContact) -> CaregiverContact:
        self._client.check_patient(row.patient_id)
        self._client.request(
            "POST",
            "/rest/v1/caregiver_contacts",
            params={"on_conflict": "patient_id,id"},
            body=row.model_dump(mode="json"),
            prefer="resolution=ignore-duplicates,return=minimal",
        )
        saved = self.get(row.patient_id, row.id)
        if saved is None:
            raise ValidationError("Could not verify the saved caregiver contact.")
        return saved

    def update(self, row: CaregiverContact) -> CaregiverContact:
        self._client.check_patient(row.patient_id)
        rows = self._client.request(
            "PATCH",
            "/rest/v1/caregiver_contacts",
            params={"id": f"eq.{row.id}"},
            body=row.model_dump(mode="json", exclude={"patient_id", "id", "created_at"}),
            prefer="return=representation",
        )
        if not rows:
            raise NotFoundError("Caregiver contact not found.")
        return CaregiverContact.model_validate(rows[0])

    def delete(self, patient_id: UUID, contact_id: UUID) -> None:
        self._client.check_patient(patient_id)
        self._client.request("DELETE", "/rest/v1/caregiver_contacts", params={"id": f"eq.{contact_id}"})
