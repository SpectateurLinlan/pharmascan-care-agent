"""Patient-owned binary files attached to an existing medication record."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LibraryFileDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    patient_id: UUID
    medication_id: UUID
    source_document_id: UUID | None = None
    regimen_version_id: UUID | None = None
    storage_path: str = Field(max_length=400)
    checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    original_filename: str = Field(min_length=1, max_length=240)
    display_title: str = Field(min_length=1, max_length=160)
    category: Literal["prescription", "pharmacy_document", "medication_instructions", "other"]
    description: str = Field(default="", max_length=500)
    content_type: Literal["application/pdf"] = "application/pdf"
    byte_size: int = Field(ge=1, le=10_485_760)
    uploaded_at: datetime
    version: int = Field(default=1, ge=1)
    deleted_at: datetime | None = None
    cleanup_pending: bool = False
    demo_only: bool = False


class LibraryFileUploadResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    file: LibraryFileDTO
    duplicate: bool


class MedicationLibraryFileRepository(Protocol):
    def list_for_medication(self, patient_id: UUID, medication_id: UUID) -> list[LibraryFileDTO]: ...
    def get(self, patient_id: UUID, file_id: UUID) -> LibraryFileDTO | None: ...
    def add_if_absent(self, file: LibraryFileDTO) -> tuple[LibraryFileDTO, bool]: ...
    def update(
        self, patient_id: UUID, file_id: UUID, expected_version: int, *, title: str, category: str, description: str
    ) -> LibraryFileDTO: ...
    def tombstone(
        self, patient_id: UUID, file_id: UUID, confirmed: bool, occurred_at: datetime
    ) -> tuple[str, bool]: ...
    def acknowledge_cleanup(self, patient_id: UUID, file_id: UUID) -> None: ...


class PrivateFileStore(Protocol):
    def put(self, path: str, data: bytes) -> None: ...
    def get(self, path: str) -> bytes: ...
    def delete(self, path: str) -> None: ...
