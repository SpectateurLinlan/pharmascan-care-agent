"""Private originals and extraction state are distinct from reviewed sources."""

from typing import Literal, Protocol, get_args
from uuid import UUID

from pydantic import Field, model_validator

from .assistant_workflows import BusinessRef, WorkflowContext, WorkflowDTO
from .enrollment_workflow import EnrollmentFields
from .source_extraction import MedicationSourceExtractionDTO

SourceKind = Literal["package", "pharmacy_label", "prescription"]
OriginalKind = Literal[
    "package", "pharmacy_label", "prescription", "reference_photo", "library_pdf", "comparison_photo",
    "source_preview_photo"
]
STORE_ONLY_KINDS = frozenset({"reference_photo", "library_pdf", "comparison_photo", "source_preview_photo"})
ImageMime = Literal["image/png", "image/jpeg"]
OriginalMime = Literal["image/png", "image/jpeg", "application/pdf"]
ExtractionState = Literal["pending", "consent_required", "succeeded", "failed", "interrupted", "not_requested"]


def validate_original_metadata(kind: OriginalKind, mime: OriginalMime, size: int) -> None:
    """Use native purpose limits; a declaration alone never verifies file bytes."""
    if kind not in get_args(OriginalKind) or type(size) is not int or size <= 0:
        raise ValueError("Invalid original metadata")
    if kind == "library_pdf":
        if mime != "application/pdf" or size > 10 * 1024 * 1024:
            raise ValueError("Invalid PDF metadata")
    elif mime not in get_args(ImageMime) or size > 8_000_000:
        raise ValueError("Invalid original image metadata")


class OriginalAttachment(WorkflowDTO):
    id: UUID
    owner: UUID
    task_id: UUID
    upload_id: UUID
    binding_revision: int = Field(ge=1)
    operation_event_id: UUID | None = None
    pending_writer_ids: tuple[UUID, ...] = Field(default=(), max_length=64)
    multiple_writers: bool = False
    object_ref: str = Field(min_length=1, max_length=300, exclude=True)
    original_checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    content_type: OriginalMime
    source_kind: OriginalKind
    byte_size: int = Field(strict=True, gt=0, le=10 * 1024 * 1024)
    state: Literal["reserved", "saved"] = "reserved"
    extraction_status: ExtractionState = "pending"
    extraction: MedicationSourceExtractionDTO | None = None
    reason: (
        Literal["provider_unavailable", "processing_consent_required", "extraction_rejected", "extraction_interrupted"]
        | None
    ) = None
    source_ref: BusinessRef | None = None
    cleanup_pending: bool = False
    object_written: bool = False

    @model_validator(mode="after")
    def native_original_limits(self):
        validate_original_metadata(self.source_kind, self.content_type, self.byte_size)
        return self


class AttachmentView(WorkflowDTO):
    id: UUID
    task_id: UUID
    original_checksum: str
    content_type: OriginalMime
    byte_size: int
    state: Literal["reserved", "saved"]
    extraction_status: ExtractionState
    reason: str | None = None
    cleanup_pending: bool = False


class EphemeralImagePreview(WorkflowDTO):
    task_id: UUID
    revision: int = Field(ge=1)
    capability_id: str
    save_mode: Literal["ephemeral"] = "ephemeral"
    storage_state: Literal["ephemeral"] = "ephemeral"
    outcome: Literal["success", "failed"]
    reason: Literal["provider_unavailable", "extraction_rejected"] | None = None
    preview: MedicationSourceExtractionDTO | None = None
    fields: EnrollmentFields | None = None


class WorkflowEnrollmentSource(WorkflowDTO):
    owner: UUID
    task_id: UUID
    attachment_id: UUID
    original_checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_kind: SourceKind
    extraction: MedicationSourceExtractionDTO


class StoredObject(WorkflowDTO):
    object_ref: str
    checksum: str
    byte_size: int


class DeleteReceipt(WorkflowDTO):
    state: Literal["deleted", "pending"]


class ProtectionResult(WorkflowDTO):
    protected: bool
    reason: Literal[
        "exclusive", "formal_source", "shared_reference", "reference_unresolved", "operation_unknown", "business_record"
    ]


class CleanupReceipt(WorkflowDTO):
    id: UUID
    owner: UUID
    task_id: UUID
    object_ref: str = Field(exclude=True)
    content_type: OriginalMime
    source_ref: BusinessRef | None = None
    state: Literal["pending", "deleted", "protected", "failed"] = "pending"
    writer_pending: bool = False
    pending_writer_ids: tuple[UUID, ...] = Field(default=(), max_length=64)
    multiple_writers: bool = False
    reason: (
        Literal[
            "upload_inflight",
            "storage_unavailable",
            "protection_unavailable",
            "formal_source",
            "reference_unresolved",
            "shared_reference",
            "operation_unknown",
            "business_record",
            "removed",
        ]
        | None
    ) = None


class CleanupStatus(WorkflowDTO):
    pending: bool = False
    protected: bool = False


class CleanupItem(WorkflowDTO):
    attachment_id: UUID
    state: Literal["pending", "deleted", "protected", "failed"]
    reason: str | None = None
    writer_pending: bool = False


class CleanupRepository(Protocol):
    def get(self, owner: UUID, attachment_id: UUID) -> CleanupReceipt: ...
    def list(self, owner: UUID, task_id: UUID) -> tuple[CleanupReceipt, ...]: ...
    def mark_written(self, owner: UUID, task_id: UUID, attachment_id: UUID, writer_id: UUID | None = None) -> None: ...
    def update(self, receipt: CleanupReceipt) -> None: ...


class AttachmentProtectionPort(Protocol):
    def references(self, owner: UUID, attachment_id: UUID) -> ProtectionResult: ...


class WorkflowAttachmentStore(Protocol):
    def put_original(
        self,
        owner: UUID,
        task_id: UUID,
        upload_id: UUID,
        content: bytes,
        content_type: OriginalMime,
        *,
        object_ref: str,
    ) -> StoredObject: ...
    def read(self, owner: UUID, key: str) -> bytes: ...
    def delete(self, owner: UUID, key: str) -> DeleteReceipt: ...


class OriginalRepository(Protocol):
    def begin_extraction(self, context: WorkflowContext, attachment_id: UUID, event_id: UUID) -> OriginalAttachment: ...
    def retry_reservation(
        self, context: WorkflowContext, attachment_id: UUID, event_id: UUID, *, starts_writer: bool = True
    ) -> OriginalAttachment: ...
    def protect_source(
        self,
        context: WorkflowContext,
        attachment_id: UUID,
        source_ref: BusinessRef,
        event_id: UUID,
    ) -> OriginalAttachment: ...
    def note_written(self, owner: UUID, task_id: UUID, attachment_id: UUID, writer_id: UUID | None = None) -> bool: ...
    def reserve(self, context: WorkflowContext, attachment: OriginalAttachment) -> OriginalAttachment: ...
    def find_upload(self, owner: UUID, task_id: UUID, upload_id: UUID) -> OriginalAttachment | None: ...
    def get(self, owner: UUID, task_id: UUID, attachment_id: UUID) -> OriginalAttachment: ...
    def list(self, owner: UUID, task_id: UUID | None = None) -> tuple[OriginalAttachment, ...]: ...
    def publish(
        self,
        context: WorkflowContext,
        attachment: OriginalAttachment,
        *,
        event_id: UUID | None = None,
    ) -> OriginalAttachment: ...
    def finish_extraction(
        self,
        context: WorkflowContext,
        attachment: OriginalAttachment,
        event_id: UUID,
    ) -> OriginalAttachment: ...
