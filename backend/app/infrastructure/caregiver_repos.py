"""Injected deterministic memory and same-user JWT/RLS contact adapters."""

from contextlib import contextmanager
from copy import deepcopy
from threading import RLock
from uuid import UUID

from ..contracts.caregivers import CaregiverContact
from ..domain.errors import NotFoundError, ValidationError
from .supabase_data import SupabaseDataClient


class MemoryCaregivers:
    def __init__(self):
        self._rows: dict[tuple[UUID, UUID], CaregiverContact] = {}
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

    def list(self, patient_id: UUID) -> list[CaregiverContact]:
        with self._lock:
            return [row for row in self._rows.values() if row.patient_id == patient_id]

    def get(self, patient_id: UUID, contact_id: UUID) -> CaregiverContact | None:
        with self._lock:
            return self._rows.get((patient_id, contact_id))

    def create(self, row: CaregiverContact) -> CaregiverContact:
        with self._lock:
            key = row.patient_id, row.id
            if key not in self._rows:
                self._rows[key] = row
                self._revisions[row.patient_id] = self._revisions.get(row.patient_id, 0) + 1
            return self._rows[key]

    def update(self, row: CaregiverContact) -> CaregiverContact:
        with self._lock:
            self._rows[(row.patient_id, row.id)] = row
            self._revisions[row.patient_id] = self._revisions.get(row.patient_id, 0) + 1
            return row

    def delete(self, patient_id: UUID, contact_id: UUID) -> None:
        with self._lock:
            if self._rows.pop((patient_id, contact_id), None) is not None:
                self._revisions[patient_id] = self._revisions.get(patient_id, 0) + 1


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
