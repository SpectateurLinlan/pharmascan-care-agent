"""Normal same-user JWT artifacts and private image storage; no admin fallback."""

from __future__ import annotations

from datetime import datetime
from threading import Lock
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
from ..timing import current_timing, timed_stage
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
        self._image_insert_lock = Lock()
        self.audit_records: list[dict[str, object]] = []

    def remove_draft_artifacts(self, owner, medication, whole, tasks, sources):
        images = [
            r
            for (kind, _), r in self._records.items()
            if kind == "images"
            and r.patient_id == owner
            and r.medication_id == medication
            and (whole or r.source_id in sources)
        ]
        paths = [
            r.storage_path
            for r in images
            if not any(
                k == "images" and other.id != r.id and other.storage_path == r.storage_path
                for (k, _), other in self._records.items()
            )
        ]
        for key, row in list(self._records.items()):
            if row.patient_id != owner:
                continue
            kind = key[0]
            remove = (
                row.id in tasks
                if kind == "tasks"
                else row.medication_id == medication and (whole or row.source_id in sources)
                if kind in {"sources", "images"}
                else whole and row.medication_id == medication
                if kind in {"sets", "embeddings"}
                else False
            )
            if remove:
                del self._records[key]
        return paths

    def list(self, patient_id: UUID, kind: RecordKind) -> list[EvidenceRecord]:
        return [row for (key, _), row in self._records.items() if key == kind and row.patient_id == patient_id]

    def get(self, patient_id: UUID, kind: RecordKind, record_id: UUID) -> EvidenceRecord | None:
        row = self._records.get((kind, record_id))
        return row if row and row.patient_id == patient_id else None

    def add(self, kind: RecordKind, record: EvidenceRecord) -> None:
        self._records.setdefault((kind, record.id), record)

    def add_image_if_absent(self, image: MedicationImage) -> bool:
        with self._image_insert_lock:
            key = ("images", image.id)
            if key in self._records:
                return False
            self._records[key] = image
            return True

    def add_reference(self, image: MedicationImage, reference: VisualReferenceSet, embedding: ImageEmbedding) -> None:
        self.add("sets", reference)
        self.add("images", image)
        self.add("embeddings", embedding)

    def retire_image(self, patient_id: UUID, image_id: UUID) -> MedicationImage:
        old = self.get(patient_id, "images", image_id)
        if not isinstance(old, MedicationImage):
            raise ValidationError("Owned reference not found")
        if old.eligibility == "ineligible" and old.eligibility_reason == "patient_retired_reference":
            return old
        retired = old.model_copy(
            update={
                "eligibility": "ineligible",
                "eligibility_reason": "patient_retired_reference",
                "metadata_version": old.metadata_version + 1,
            }
        )
        self._records[("images", image_id)] = retired
        self.audit_records.append(
            {
                "patient_id": patient_id,
                "image_id": image_id,
                "action": "stopped_comparison",
                "before": old.model_dump(mode="json"),
                "after": retired.model_dump(mode="json"),
            }
        )
        return retired

    def manage_image(
        self,
        patient_id: UUID,
        image_id: UUID,
        *,
        action: str,
        expected_version: int,
        occurred_at: datetime,
        image_kind: str | None = None,
        source_description: str | None = None,
        confirmed: bool = False,
    ) -> tuple[MedicationImage, str]:
        old = self.get(patient_id, "images", image_id)
        if not isinstance(old, MedicationImage) or old.deleted_at is not None:
            raise ValidationError("Photo not found")
        if action not in {"edit", "remove", "delete"}:
            raise ValidationError("Unsupported photo action")
        if action != "edit" and not confirmed:
            raise ValidationError("Explicit confirmation required")
        if old.source_id is not None and action in {"remove", "delete"}:
            raise ValidationError("Source-linked evidence cannot be removed or deleted")
        if old.metadata_version != expected_version:
            raise ValidationError("Photo changed. Reload before editing.")
        if action == "edit":
            if image_kind not in {"loose_pill", "package", "blister", "source"}:
                raise ValidationError("Invalid photo type")
            if not source_description or not source_description.strip() or len(source_description) > 200:
                raise ValidationError("Invalid photo description")
        if action == "delete":
            shared = any(
                row.id != old.id and row.storage_path == old.storage_path
                for row in self.list(patient_id, "images")
                if isinstance(row, MedicationImage)
            )
            if shared:
                raise ValidationError("Shared photo cannot be deleted")
        update: dict[str, object] = {"metadata_version": old.metadata_version + 1}
        if action == "edit":
            update.update(image_kind=image_kind, source_description=source_description)
            if image_kind != old.image_kind:
                update.update(eligibility="ineligible", eligibility_reason="patient_metadata_changed")
        elif action == "remove":
            update.update(
                gallery_removed=True, eligibility="ineligible", eligibility_reason="patient_removed_from_gallery"
            )
        else:
            update.update(
                deleted_at=occurred_at,
                cleanup_pending=True,
                eligibility="ineligible",
                eligibility_reason="patient_deleted_photo",
            )
        changed = old.model_copy(update=update)
        self._records[("images", image_id)] = changed
        if action in {"remove", "delete"} or image_kind != old.image_kind:
            self._records = {
                key: row
                for key, row in self._records.items()
                if not (key[0] == "embeddings" and getattr(row, "image_id", None) == image_id)
            }
        self.audit_records.append(
            {
                "patient_id": patient_id,
                "image_id": image_id,
                "action": action,
                "before": old.model_dump(mode="json"),
                "after": changed.model_dump(mode="json"),
            }
        )
        return changed, old.storage_path

    def acknowledge_image_cleanup(self, patient_id: UUID, image_id: UUID) -> None:
        row = self.get(patient_id, "images", image_id)
        if isinstance(row, MedicationImage) and row.deleted_at is not None and row.cleanup_pending:
            self._records[("images", image_id)] = row.model_copy(update={"cleanup_pending": False})

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

    def add_image_if_absent(self, image: MedicationImage) -> bool:
        self._client.check_patient(image.patient_id)
        payload = self._client.request(
            "POST",
            "/rest/v1/medication_images",
            params={"on_conflict": "patient_id,id"},
            body={
                "id": str(image.id),
                "patient_id": str(image.patient_id),
                "medication_id": str(image.medication_id),
                "data": image.model_dump(mode="json"),
            },
            prefer="resolution=ignore-duplicates,return=representation",
        )
        return isinstance(payload, list) and bool(payload)

    def retire_image(self, patient_id: UUID, image_id: UUID) -> MedicationImage:
        self._client.check_patient(patient_id)
        row = self._client.request("POST", "/rest/v1/rpc/retire_personal_reference", body={"p_image_id": str(image_id)})
        return MedicationImage.model_validate(row)

    def manage_image(
        self,
        patient_id: UUID,
        image_id: UUID,
        *,
        action: str,
        expected_version: int,
        occurred_at: datetime,
        image_kind: str | None = None,
        source_description: str | None = None,
        confirmed: bool = False,
    ) -> tuple[MedicationImage, str]:
        self._client.check_patient(patient_id)
        payload = self._client.request(
            "POST",
            "/rest/v1/rpc/manage_personal_gallery_image",
            body={
                "p_image_id": str(image_id),
                "p_action": action,
                "p_expected_version": expected_version,
                "p_image_kind": image_kind,
                "p_source_description": source_description,
                "p_confirmed": confirmed,
            },
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("image"), dict):
            raise ProviderUnavailableError("Photo management response was invalid")
        return MedicationImage.model_validate(payload["image"]), str(payload["storage_path"])

    def acknowledge_image_cleanup(self, patient_id: UUID, image_id: UUID) -> None:
        self._client.check_patient(patient_id)
        self._client.request(
            "POST", "/rest/v1/rpc/ack_personal_gallery_image_cleanup", body={"p_image_id": str(image_id)}
        )

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

    def delete(self, path: str) -> None:
        self._data.pop(path, None)


class SupabaseImageStore:
    def __init__(
        self,
        *,
        base_url: str,
        publishable_key: str,
        access_token: str,
        patient_id: UUID,
        client_factory=httpx.Client,
        bucket_id: str = "visual-references",
        content_type: str = "image/png",
    ):
        self._url, self._factory = base_url.rstrip("/"), client_factory
        self._headers = {"apikey": publishable_key, "Authorization": "Bearer " + access_token}
        self._patient = patient_id
        if bucket_id not in {"visual-references", "medication-sources"}:
            raise ValidationError("Unsupported private storage bucket")
        self._bucket_id, self._content_type = bucket_id, content_type

    def _request(self, method: str, path: str, data: bytes | None = None) -> bytes:
        if not path.startswith(f"{self._patient}/") or ".." in path:
            raise ValidationError("Invalid private object path")
        timing = current_timing.get()
        if timing is not None:
            timing.storage_requests += 1
        try:
            with timed_stage("storage"), self._factory() as client:
                response = client.request(
                    method,
                    self._url + f"/storage/v1/object/{self._bucket_id}/" + path,
                    headers={**self._headers, "Content-Type": self._content_type, "x-upsert": "false"},
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
        if method == "DELETE" and response.status_code == 404:
            return b""
        if response.status_code >= 400:
            raise ProviderUnavailableError("Private image operation rejected")
        return response.content

    def put(self, path: str, data: bytes) -> None:
        self._request("POST", path, data)

    def get(self, path: str) -> bytes:
        return self._request("GET", path)

    def delete(self, path: str) -> None:
        self._request("DELETE", path)
