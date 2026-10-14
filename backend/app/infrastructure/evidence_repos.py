"""Normal same-user JWT artifacts and private image storage; no admin fallback."""

from __future__ import annotations

from uuid import UUID

import httpx

from ..contracts.dto import PatientMedicationDTO
from ..contracts.medication_evidence import (
    EnrollmentTask,
    EvidenceRecord,
    ImageEmbedding,
    MedicationImage,
    RecognitionRun,
    RecordKind,
    SourceLink,
    VisualReferenceSet,
)
from ..domain.errors import ProviderUnavailableError, ValidationError
from .supabase_data import SupabaseDataClient

MODELS = {
    "tasks": EnrollmentTask,
    "sources": SourceLink,
    "images": MedicationImage,
    "sets": VisualReferenceSet,
    "embeddings": ImageEmbedding,
    "runs": RecognitionRun,
}
TABLES = {
    "tasks": "medication_evidence_tasks",
    "sources": "medication_source_links",
    "images": "medication_images",
    "sets": "visual_reference_sets",
    "embeddings": "image_embeddings",
    "runs": "recognition_runs",
}


class MemoryEvidenceRepository:
    def __init__(self, medications):
        self._medications = medications
        self._records: dict[tuple[str, UUID], EvidenceRecord] = {}

    def list(self, patient_id: UUID, kind: RecordKind) -> list[EvidenceRecord]:
        return [row for (key, _), row in self._records.items() if key == kind and row.patient_id == patient_id]

    def get(self, patient_id: UUID, kind: RecordKind, record_id: UUID) -> EvidenceRecord | None:
        row = self._records.get((kind, record_id))
        return row if row and row.patient_id == patient_id else None

    def add(self, kind: RecordKind, record: EvidenceRecord) -> None:
        self._records.setdefault((kind, record.id), record)

    def add_reference(self, image: MedicationImage, reference: VisualReferenceSet, embedding: ImageEmbedding) -> None:
        self.add("sets", reference)
        self.add("images", image)
        self.add("embeddings", embedding)

    def retire_image(self, patient_id: UUID, image_id: UUID) -> MedicationImage:
        old = self.get(patient_id, "images", image_id)
        if not isinstance(old, MedicationImage):
            raise ValidationError("Owned reference not found")
        retired = old.model_copy(
            update={"eligibility": "ineligible", "eligibility_reason": "patient_retired_reference"}
        )
        self._records[("images", image_id)] = retired
        return retired

    def update_task(self, task: EnrollmentTask, expected_version: int) -> None:
        old = self.get(task.patient_id, "tasks", task.id)
        if not isinstance(old, EnrollmentTask) or old.version != expected_version:
            raise ValidationError("Task changed. Reload before adding evidence.")
        self._records[("tasks", task.id)] = task

    def medications(self, patient_id: UUID) -> list[PatientMedicationDTO]:
        return self._medications.list_for_patient(patient_id)


class SupabaseEvidenceRepository:
    def __init__(self, client: SupabaseDataClient, medications):
        self._client, self._medications = client, medications

    def list(self, patient_id: UUID, kind: RecordKind) -> list[EvidenceRecord]:
        self._client.check_patient(patient_id)
        # Deliberately no patient WHERE. RLS is the ownership boundary.
        return [MODELS[kind].model_validate(row["data"]) for row in self._client.all_rows(TABLES[kind])]

    def get(self, patient_id: UUID, kind: RecordKind, record_id: UUID) -> EvidenceRecord | None:
        self._client.check_patient(patient_id)
        rows = self._client.rows(TABLES[kind], id=f"eq.{record_id}", limit="1")
        return MODELS[kind].model_validate(rows[0]["data"]) if rows else None

    def add(self, kind: RecordKind, record: EvidenceRecord) -> None:
        self._client.check_patient(record.patient_id)
        body = {"id": str(record.id), "patient_id": str(record.patient_id), "data": record.model_dump(mode="json")}
        for field in ("medication_id", "source_id", "image_id", "reference_set_id", "selected_regimen_id"):
            if hasattr(record, field):
                value = getattr(record, field)
                body[field] = str(value) if value is not None else None
        if isinstance(record, EnrollmentTask):
            body["version"] = record.version
        self._client.request(
            "POST",
            f"/rest/v1/{TABLES[kind]}",
            params={"on_conflict": "patient_id,id"},
            body=body,
            prefer="resolution=ignore-duplicates,return=minimal",
        )

    def retire_image(self, patient_id: UUID, image_id: UUID) -> MedicationImage:
        self._client.check_patient(patient_id)
        row = self._client.request("POST", "/rest/v1/rpc/retire_personal_reference", body={"p_image_id": str(image_id)})
        return MedicationImage.model_validate(row)

    def update_task(self, task: EnrollmentTask, expected_version: int) -> None:
        self._client.check_patient(task.patient_id)
        rows = self._client.request(
            "PATCH",
            "/rest/v1/medication_evidence_tasks",
            params={"id": f"eq.{task.id}", "version": f"eq.{expected_version}"},
            body={"version": task.version, "data": task.model_dump(mode="json")},
        )
        if not rows:
            raise ValidationError("Task changed. Reload before adding evidence.")

    def add_reference(self, image: MedicationImage, reference: VisualReferenceSet, embedding: ImageEmbedding) -> None:
        self._client.check_patient(image.patient_id)
        self._client.request(
            "POST",
            "/rest/v1/rpc/store_personal_reference",
            body={
                "p_image": image.model_dump(mode="json"),
                "p_set": reference.model_dump(mode="json"),
                "p_embedding": embedding.model_dump(mode="json"),
            },
        )

    def medications(self, patient_id: UUID) -> list[PatientMedicationDTO]:
        return self._medications.list_for_patient(patient_id)


class MemoryImageStore:
    def __init__(self):
        self._data: dict[str, bytes] = {}

    def put(self, path: str, data: bytes) -> None:
        self._data.setdefault(path, data)

    def get(self, path: str) -> bytes:
        return self._data[path]


class SupabaseImageStore:
    def __init__(
        self, *, base_url: str, publishable_key: str, access_token: str, patient_id: UUID, client_factory=httpx.Client
    ):
        self._url, self._factory = base_url.rstrip("/"), client_factory
        self._headers = {"apikey": publishable_key, "Authorization": "Bearer " + access_token}
        self._patient = patient_id

    def _request(self, method: str, path: str, data: bytes | None = None) -> bytes:
        if not path.startswith(f"{self._patient}/") or ".." in path:
            raise ValidationError("Invalid private object path")
        try:
            with self._factory() as client:
                response = client.request(
                    method,
                    self._url + "/storage/v1/object/visual-references/" + path,
                    headers={**self._headers, "Content-Type": "image/png", "x-upsert": "false"},
                    content=data,
                    timeout=15,
                )
        except httpx.HTTPError:
            raise ProviderUnavailableError("Private image storage unavailable") from None
        # Duplicate immutable upload is acceptable; it is never overwritten.
        if method == "POST" and response.status_code in (400, 409):
            try:
                duplicate = response.json().get("error") in {"Duplicate", "ResourceAlreadyExists"}
            except ValueError:
                duplicate = False
            if duplicate:
                return b""
        if response.status_code >= 400:
            raise ProviderUnavailableError("Private image operation rejected")
        return response.content

    def put(self, path: str, data: bytes) -> None:
        self._request("POST", path, data)

    def get(self, path: str) -> bytes:
        return self._request("GET", path)
