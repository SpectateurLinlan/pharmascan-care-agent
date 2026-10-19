"""Patient-scoped PDF metadata persistence through the caller's Supabase JWT."""

from __future__ import annotations

from threading import Lock
from uuid import UUID

from ..contracts.library_files import LibraryFileDTO
from ..domain.errors import NotFoundError, ProviderUnavailableError, ValidationError
from .supabase_data import SupabaseDataClient


class MemoryMedicationLibraryFiles:
    def __init__(self) -> None:
        self._files: dict[tuple[UUID, UUID], LibraryFileDTO] = {}
        self._lock = Lock()
        self.audit: list[dict[str, object]] = []

    def list_for_medication(self, patient_id: UUID, medication_id: UUID) -> list[LibraryFileDTO]:
        return [
            file
            for (owner, _), file in self._files.items()
            if owner == patient_id and file.medication_id == medication_id and file.deleted_at is None
        ]

    def get(self, patient_id: UUID, file_id: UUID) -> LibraryFileDTO | None:
        return self._files.get((patient_id, file_id))

    def add_if_absent(self, file: LibraryFileDTO) -> tuple[LibraryFileDTO, bool]:
        with self._lock:
            existing = next(
                (
                    row
                    for (owner, _), row in self._files.items()
                    if owner == file.patient_id
                    and row.medication_id == file.medication_id
                    and row.checksum == file.checksum
                ),
                None,
            )
            if existing:
                return existing, True
            self._files[(file.patient_id, file.id)] = file
            self.audit.append({"action": "uploaded", "file_id": file.id, "actor_id": file.patient_id})
            return file, False

    def update(
        self, patient_id: UUID, file_id: UUID, expected_version: int, *, title: str, category: str, description: str
    ) -> LibraryFileDTO:
        old = self.get(patient_id, file_id)
        if old is None or old.deleted_at is not None:
            raise NotFoundError("File not found")
        if old.version != expected_version:
            raise ValidationError("File changed. Reload before editing.")
        new = old.model_copy(
            update={
                "display_title": title,
                "category": category,
                "description": description,
                "version": old.version + 1,
            }
        )
        self._files[(patient_id, file_id)] = new
        self.audit.append(
            {
                "action": "metadata_updated",
                "file_id": file_id,
                "actor_id": patient_id,
                "before": old.model_dump(mode="json"),
                "after": new.model_dump(mode="json"),
            }
        )
        return new

    def tombstone(self, patient_id: UUID, file_id: UUID, confirmed: bool, occurred_at) -> tuple[str, bool]:
        old = self.get(patient_id, file_id)
        if old is None:
            raise NotFoundError("File not found")
        if not confirmed:
            raise ValidationError("Explicit confirmation required")
        if old.source_document_id or old.regimen_version_id:
            raise ValidationError("File is linked to a protected source or regimen")
        if old.deleted_at is None:
            new = old.model_copy(
                update={"deleted_at": occurred_at, "cleanup_pending": True, "version": old.version + 1}
            )
            self._files[(patient_id, file_id)] = new
            self.audit.append(
                {
                    "action": "deleted",
                    "file_id": file_id,
                    "actor_id": patient_id,
                    "before": old.model_dump(mode="json"),
                    "after": new.model_dump(mode="json"),
                }
            )
            return old.storage_path, True
        return old.storage_path, old.cleanup_pending

    def acknowledge_cleanup(self, patient_id: UUID, file_id: UUID) -> None:
        old = self.get(patient_id, file_id)
        if old and old.deleted_at is not None and old.cleanup_pending:
            self._files[(patient_id, file_id)] = old.model_copy(update={"cleanup_pending": False})


class SupabaseMedicationLibraryFiles:
    def __init__(self, client: SupabaseDataClient):
        self._client = client

    def list_for_medication(self, patient_id: UUID, medication_id: UUID) -> list[LibraryFileDTO]:
        self._client.check_patient(patient_id)
        rows = self._client.rows(
            "medication_library_files",
            medication_id=f"eq.{medication_id}",
            deleted_at="is.null",
            order="uploaded_at.desc",
        )
        return [LibraryFileDTO.model_validate(row) for row in rows]

    def get(self, patient_id: UUID, file_id: UUID) -> LibraryFileDTO | None:
        self._client.check_patient(patient_id)
        rows = self._client.rows("medication_library_files", id=f"eq.{file_id}", limit="1")
        return LibraryFileDTO.model_validate(rows[0]) if rows else None

    def add_if_absent(self, file: LibraryFileDTO) -> tuple[LibraryFileDTO, bool]:
        self._client.check_patient(file.patient_id)
        response = self._client.request(
            "POST", "/rest/v1/rpc/register_medication_library_pdf", body={"p_file": file.model_dump(mode="json")}
        )
        if not isinstance(response, dict) or not isinstance(response.get("file"), dict):
            raise ProviderUnavailableError("File registration response was invalid")
        return LibraryFileDTO.model_validate(response["file"]), bool(response.get("duplicate"))

    def update(
        self, patient_id: UUID, file_id: UUID, expected_version: int, *, title: str, category: str, description: str
    ) -> LibraryFileDTO:
        self._client.check_patient(patient_id)
        row = self._client.request(
            "POST",
            "/rest/v1/rpc/update_medication_library_pdf",
            body={
                "p_id": str(file_id),
                "p_expected_version": expected_version,
                "p_title": title,
                "p_category": category,
                "p_description": description,
            },
        )
        if not isinstance(row, dict):
            raise ProviderUnavailableError("File update response was invalid")
        return LibraryFileDTO.model_validate(row)

    def tombstone(self, patient_id: UUID, file_id: UUID, confirmed: bool, occurred_at) -> tuple[str, bool]:
        self._client.check_patient(patient_id)
        response = self._client.request(
            "POST",
            "/rest/v1/rpc/tombstone_medication_library_pdf",
            body={"p_id": str(file_id), "p_confirmed": confirmed},
        )
        if not isinstance(response, dict) or not isinstance(response.get("storage_path"), str):
            raise ProviderUnavailableError("File deletion response was invalid")
        return response["storage_path"], bool(response.get("cleanup_pending"))

    def acknowledge_cleanup(self, patient_id: UUID, file_id: UUID) -> None:
        self._client.check_patient(patient_id)
        self._client.request("POST", "/rest/v1/rpc/ack_medication_library_pdf_cleanup", body={"p_id": str(file_id)})
