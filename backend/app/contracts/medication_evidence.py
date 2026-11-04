"""Patient-owned product evidence, progressive tasks and visual artifacts."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .dto import PatientMedicationDTO, RegimenDraftInput, SourceDocumentDTO, SourceFieldDTO
from .vision import EmbeddingResult, MatchOutcome, ModelMetadata
from .workflow_attachments import WorkflowEnrollmentSource


class EvidenceDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ProductEvidence(EvidenceDTO):
    name: str = Field(min_length=1, max_length=160)
    strength: str | None = Field(default=None, max_length=100)
    dose_form: str | None = Field(default=None, max_length=100)
    formulation: str | None = Field(default=None, max_length=100)
    brand: str | None = Field(default=None, max_length=100)
    manufacturer: str | None = Field(default=None, max_length=100)
    ingredients: list[str] = Field(default_factory=list, max_length=10)
    external_identifiers: dict[str, str] = Field(default_factory=dict, max_length=10)
    category: Literal["unknown", "POM", "P", "GSL", "supplement"] = "unknown"
    category_basis: Literal["unknown", "patient_entered"] = "unknown"
    verification: Literal["source_supplied", "patient_reviewed"] = "source_supplied"


class SourceLink(EvidenceDTO):
    id: UUID
    patient_id: UUID
    medication_id: UUID
    source_id: UUID
    recorded_at: datetime


class SourceEvidenceView(SourceDocumentDTO):
    recorded_at: datetime | None = None
    provided_by: Literal["patient"] = "patient"


class EnrollmentTask(EvidenceDTO):
    id: UUID
    patient_id: UUID
    medication_id: UUID
    version: int = Field(default=1, ge=1)
    status: Literal["pending_information", "conflict", "ready_for_review", "draft_created"] = "pending_information"
    product: ProductEvidence
    product_missing: list[str] = Field(default_factory=list, max_length=6)
    printed_course_days: int | None = Field(default=None, ge=1, le=365)
    source_ids: list[UUID] = Field(default_factory=list, max_length=10)
    missing: list[str] = Field(default_factory=list, max_length=15)
    conflicts: list[str] = Field(default_factory=list, max_length=20)
    possible_duplicate_ids: list[UUID] = Field(default_factory=list, max_length=10)
    suggested_regimen: RegimenDraftInput | None = None
    draft_regimen_id: UUID | None = None
    updated_at: datetime


ImageKind = Literal["loose_pill", "package", "blister", "source"]


class MedicationImage(EvidenceDTO):
    id: UUID
    patient_id: UUID
    medication_id: UUID
    image_kind: ImageKind
    storage_path: str = Field(max_length=400)
    checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_description: str = Field(min_length=1, max_length=200)
    source_id: UUID | None = None
    reviewed: bool = False
    eligibility: Literal["associated", "eligible", "ineligible"] = "associated"
    eligibility_reason: str = Field(max_length=200)
    created_at: datetime
    metadata_version: int = Field(default=1, ge=1)
    gallery_removed: bool = False
    deleted_at: datetime | None = None
    cleanup_pending: bool = False


class GalleryUploadResult(EvidenceDTO):
    photo: MedicationImage
    duplicate: bool


class VisualReferenceSet(EvidenceDTO):
    id: UUID
    patient_id: UUID
    medication_id: UUID
    model: ModelMetadata
    created_at: datetime


class ImageEmbedding(EvidenceDTO):
    id: UUID
    patient_id: UUID
    medication_id: UUID
    image_id: UUID
    reference_set_id: UUID
    result: EmbeddingResult


class RecognitionRun(EvidenceDTO):
    id: UUID
    patient_id: UUID
    task: Literal["check_dose", "identify"]
    selected_regimen_id: UUID | None
    reference_ids: list[UUID] = Field(max_length=50)
    outcome: MatchOutcome | None
    decision: Literal["match", "unknown", "ambiguous", "conflict", "missing_reference", "unavailable"]
    reason: str = Field(max_length=500)
    created_at: datetime
    safe_to_take: Literal[False] = False
    ingestion_proven: Literal[False] = False


RecordKind = Literal["tasks", "sources", "images", "sets", "embeddings", "runs"]
EvidenceRecord = EnrollmentTask | SourceLink | MedicationImage | VisualReferenceSet | ImageEmbedding | RecognitionRun


class EvidenceRepository(Protocol):
    def list(self, patient_id: UUID, kind: RecordKind) -> list[EvidenceRecord]: ...
    def get(self, patient_id: UUID, kind: RecordKind, record_id: UUID) -> EvidenceRecord | None: ...
    def add(self, kind: RecordKind, record: EvidenceRecord) -> None: ...
    def add_image_if_absent(self, image: MedicationImage) -> bool: ...
    def add_reference(
        self, image: MedicationImage, reference: VisualReferenceSet, embedding: ImageEmbedding
    ) -> None: ...
    def retire_image(self, patient_id: UUID, image_id: UUID) -> MedicationImage: ...
    def manage_image(
        self,
        patient_id: UUID,
        image_id: UUID,
        *,
        action: Literal["edit", "remove", "delete"],
        expected_version: int,
        occurred_at: datetime,
        image_kind: ImageKind | None = None,
        source_description: str | None = None,
        confirmed: bool = False,
    ) -> tuple[MedicationImage, str]: ...
    def acknowledge_image_cleanup(self, patient_id: UUID, image_id: UUID) -> None: ...
    def update_task(self, task: EnrollmentTask, expected_version: int) -> None: ...
    def medications(self, patient_id: UUID) -> list[PatientMedicationDTO]: ...


@dataclass(frozen=True, kw_only=True)
class EvidenceSourcePublication:
    """Request-memory proposal. Never an HTTP input or workflow/model payload."""

    source: SourceDocumentDTO
    fields: tuple[SourceFieldDTO, ...]
    medication: PatientMedicationDTO
    create_medication: bool
    prior_task: EnrollmentTask | None
    task: EnrollmentTask
    image: MedicationImage
    link: SourceLink
    derived_image: bytes = field(repr=False)
    expected_clinical_revision: int | None = None
    workflow_task_id: UUID | None = None
    attachment_id: UUID | None = None
    original_checksum: str | None = None


class EvidenceSourceSnapshot(EvidenceDTO):
    source: SourceDocumentDTO
    fields: tuple[SourceFieldDTO,...] = Field(max_length=20)
    medication: PatientMedicationDTO
    task: EnrollmentTask
    image: MedicationImage
    link: SourceLink
    derived_byte_size: int = Field(strict=True,ge=1,le=8_000_000)


class EvidenceOriginalReferences(Protocol):
    def original_sources(self, owner: UUID, attachment_id: UUID) -> tuple[UUID, ...]: ...


class EvidenceEnrollmentWritePort(Protocol):
    def revision(self, owner: UUID) -> int: ...
    def workflow_owner(self, owner: UUID, task_id: UUID) -> UUID | None: ...
    def lookup(self, owner: UUID, action_key: UUID) -> EnrollmentTask | None: ...
    def lookup_original(
        self,
        owner: UUID,
        action_key: UUID,
        workflow_task_id: UUID,
        attachment_id: UUID,
    ) -> EnrollmentTask | None: ...
    def publish_once(self, owner: UUID, action_key: UUID, prepared: EvidenceSourcePublication) -> EnrollmentTask: ...
    def bind_existing_original(
        self,
        owner: UUID,
        action_key: UUID,
        task: EnrollmentTask,
        source: WorkflowEnrollmentSource,
        checksum: str,
    ) -> EnrollmentTask: ...
    def review_unactivated(
        self,
        owner: UUID,
        task_id: UUID,
        expected_version: int,
        expected_clinical_revision: int,
        apply: Callable[[], EnrollmentTask],
    ) -> EnrollmentTask: ...


class LocalEvidenceEnrollmentWritePort(EvidenceEnrollmentWritePort, EvidenceOriginalReferences, Protocol):
    """Memory-only rollback scope; the remote implementation uses one domain RPC."""
    def local_transaction(self) -> AbstractContextManager[None]: ...


class PrivateImageStore(Protocol):
    def delete(self, path: str) -> None: ...
    def put(self, path: str, data: bytes) -> None: ...
    def get(self, path: str) -> bytes: ...


class PersonalVisionPort(Protocol):
    def encode(self, image: bytes) -> tuple[ModelMetadata, EmbeddingResult]: ...
    def compare(
        self, query: EmbeddingResult, references: list[ImageEmbedding], names: dict[str, str]
    ) -> MatchOutcome: ...
