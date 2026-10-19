"""Medication-associated original PDF storage; never extracts clinical instructions."""

from __future__ import annotations

import hashlib
import logging
import re
from uuid import UUID, uuid5

from ..contracts.library_files import LibraryFileDTO, MedicationLibraryFileRepository, PrivateFileStore
from ..contracts.ports import Clock
from ..domain.errors import NotFoundError, ValidationError
from .enrollment import MedicationEnrollmentService

PDF_LIMIT = 10 * 1024 * 1024
PDF_CATEGORIES = {"prescription", "pharmacy_document", "medication_instructions", "other"}
LOGGER = logging.getLogger(__name__)


class MedicationLibraryFileService:
    def __init__(
        self,
        *,
        repository: MedicationLibraryFileRepository,
        storage: PrivateFileStore,
        enrollment: MedicationEnrollmentService,
        clock: Clock,
        demo_only: bool = False,
    ):
        self._repo, self._storage, self._enrollment, self._clock = repository, storage, enrollment, clock
        self._demo_only = demo_only

    def list(self, patient_id: UUID, medication_id: UUID) -> list[LibraryFileDTO]:
        if self._enrollment.get_medication(patient_id, medication_id) is None:
            raise NotFoundError("Medication not found")
        return self._repo.list_for_medication(patient_id, medication_id)

    def upload(
        self,
        *,
        patient_id: UUID,
        medication_id: UUID,
        filename: str,
        content_type: str,
        data: bytes,
        category: str,
        description: str = "",
    ) -> tuple[LibraryFileDTO, bool]:
        if self._enrollment.get_medication(patient_id, medication_id) is None:
            raise NotFoundError("Medication not found")
        if content_type != "application/pdf" or not filename.casefold().endswith(".pdf"):
            raise ValidationError("Choose a PDF file")
        if not data or len(data) > PDF_LIMIT:
            raise ValidationError("PDF must be no larger than 10 MB")
        if not is_basic_pdf(data):
            raise ValidationError("The selected file is not a valid PDF")
        if category not in PDF_CATEGORIES or len(description) > 500:
            raise ValidationError("Invalid file information")
        safe_filename = clean_filename(filename)
        digest = hashlib.sha256(data).hexdigest()
        file_id = uuid5(patient_id, f"medication-library-pdf:{medication_id}:{digest}")
        path = f"{patient_id}/library/{medication_id}/{digest}.pdf"
        existing = self._repo.get(patient_id, file_id)
        if existing is not None:
            if existing.deleted_at is not None:
                raise ValidationError("This PDF was previously removed. Choose a different file.")
            return existing, True
        row = LibraryFileDTO(
            id=file_id,
            patient_id=patient_id,
            medication_id=medication_id,
            storage_path=path,
            checksum=digest,
            original_filename=safe_filename,
            display_title=safe_filename[:-4][:160] or "Medication document",
            category=category,
            description=description.strip(),
            byte_size=len(data),
            uploaded_at=self._clock.now(),
            demo_only=self._demo_only,
        )
        # The deterministic private path makes retries idempotent; Storage's
        # no-upsert contract prevents replacement of bytes at an existing key.
        self._storage.put(path, data)
        try:
            result, duplicate = self._repo.add_if_absent(row)
        except Exception:
            # A timeout may have committed the registration. Never delete an
            # object that another successful request could now reference.
            LOGGER.warning("private_file_registration_unconfirmed", extra={"file_id": str(file_id)})
            raise
        if result.deleted_at is not None:
            raise ValidationError("This PDF was previously removed. Choose a different file.")
        return result, duplicate

    def content(self, patient_id: UUID, file_id: UUID) -> tuple[LibraryFileDTO, bytes]:
        file = self._repo.get(patient_id, file_id)
        if file is None or file.deleted_at is not None:
            raise NotFoundError("File not found")
        return file, self._storage.get(file.storage_path)

    def update(
        self, patient_id: UUID, file_id: UUID, *, expected_version: int, title: str, category: str, description: str
    ) -> LibraryFileDTO:
        if not title.strip() or len(title.strip()) > 160 or category not in PDF_CATEGORIES or len(description) > 500:
            raise ValidationError("Invalid file information")
        return self._repo.update(
            patient_id,
            file_id,
            expected_version,
            title=title.strip(),
            category=category,
            description=description.strip(),
        )

    def delete(self, patient_id: UUID, file_id: UUID, *, confirmed: bool) -> None:
        path, pending = self._repo.tombstone(patient_id, file_id, confirmed, self._clock.now())
        if pending:
            self._storage.delete(path)
            self._repo.acknowledge_cleanup(patient_id, file_id)


def is_basic_pdf(data: bytes) -> bool:
    """Check the PDF signature and terminal marker without parsing/extracting text."""
    return data.startswith(b"%PDF-") and data.rstrip().endswith(b"%%EOF")


def clean_filename(value: str) -> str:
    leaf = re.split(r"[/\\]", value)[-1]
    cleaned = "".join(char for char in leaf if char.isprintable() and char not in '<>:"|?*').strip().strip(".")
    if not cleaned or not cleaned.casefold().endswith(".pdf"):
        raise ValidationError("Choose a PDF file")
    return cleaned[:-4][:236] + ".pdf"
