"""Independent typed media commands; metadata deletion is not Storage evidence."""

from contextlib import AbstractContextManager
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import Field, TypeAdapter, field_validator, model_validator

from .assistant_workflows import WorkflowDTO
from .library_files import LibraryFileDTO, LibraryFileUploadResult, MedicationLibraryFileRepository
from .media_workflow import PdfChangeFields, PdfUploadFields, PhotoChangeFields, PhotoUploadFields
from .medication_evidence import EvidenceRepository, GalleryUploadResult, MedicationImage
from .workflow_media_storage import VerifiedMediaOperationRef
from .workflow_persistence import BusinessWriteReceipt, NativeWriteResult, WorkflowWriteBinding


class ConfirmedMediaWrite(WorkflowDTO):
    binding: WorkflowWriteBinding
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def independent_patient_confirmation(cls, value):
        if value is not True:
            raise ValueError("Independent patient confirmation is required")
        return value


class PhotoLifecycleWrite(ConfirmedMediaWrite):
    values: PhotoChangeFields

    @model_validator(mode="after")
    def actual_target(self):
        if self.values.image_id is None or self.values.expected_version is None or self.values.medication_id is None:
            raise ValueError("An owned photo and its current version are required")
        return self


class EditPhoto(PhotoLifecycleWrite):
    kind: Literal["edit_photo"] = "edit_photo"


class RemovePhoto(PhotoLifecycleWrite):
    kind: Literal["remove_photo"] = "remove_photo"


class DeletePhoto(PhotoLifecycleWrite):
    kind: Literal["delete_photo"] = "delete_photo"


class RetirePhoto(PhotoLifecycleWrite):
    kind: Literal["retire_photo"] = "retire_photo"


class PdfLifecycleWrite(ConfirmedMediaWrite):
    values: PdfChangeFields

    @model_validator(mode="after")
    def actual_target(self):
        if self.values.file_id is None or self.values.expected_version is None or self.values.medication_id is None:
            raise ValueError("An owned PDF and its current version are required")
        return self


class EditPdf(PdfLifecycleWrite):
    kind: Literal["edit_pdf"] = "edit_pdf"


class TombstonePdf(PdfLifecycleWrite):
    kind: Literal["tombstone_pdf"] = "tombstone_pdf"


class PrepareMediaReview(WorkflowDTO):
    kind: Literal["prepare_media"] = "prepare_media"
    binding: WorkflowWriteBinding

    @model_validator(mode="after")
    def technical_review_only(self):
        ref = self.binding.prepared_ref
        if ref.kind != "media_review" or ref.id != self.binding.action_key or ref.version != 1:
            raise ValueError("Media preparation must own its technical marker")
        return self


class RegisterPhoto(ConfirmedMediaWrite):
    kind: Literal["register_photo"] = "register_photo"
    values: PhotoUploadFields
    copy_proof: VerifiedMediaOperationRef
    reviewed: Literal[True]
    processing_consent: Literal[True]

    @field_validator("reviewed", "processing_consent", mode="before")
    @classmethod
    def explicit_photo_consent(cls, value):
        if value is not True:
            raise ValueError("Explicit photo review and processing consent are required")
        return value

    @model_validator(mode="after")
    def actual_original(self):
        if any(
            getattr(self.values, key) is None
            for key in ("source_attachment_id", "medication_id", "image_kind", "source_description")
        ):
            raise ValueError("An owned original and complete photo draft are required")
        return self


class RegisterPdf(ConfirmedMediaWrite):
    kind: Literal["register_pdf"] = "register_pdf"
    values: PdfUploadFields
    copy_proof: VerifiedMediaOperationRef

    @model_validator(mode="after")
    def actual_original(self):
        if any(
            getattr(self.values, key) is None
            for key in ("source_attachment_id", "medication_id", "filename", "category")
        ):
            raise ValueError("An owned original and complete PDF draft are required")
        return self


MediaWriteCommand = Annotated[
    EditPhoto | RemovePhoto | DeletePhoto | RetirePhoto | EditPdf | TombstonePdf | RegisterPhoto | RegisterPdf,
    Field(discriminator="kind"),
]
MEDIA_WRITE_COMMAND = TypeAdapter(MediaWriteCommand)
MediaNativeResult = MedicationImage | GalleryUploadResult | LibraryFileDTO | LibraryFileUploadResult | None


class MediaWorkflowWritePort(Protocol):
    def revision(self, owner: UUID) -> int: ...
    def lookup(self, owner: UUID, action_key: UUID) -> BusinessWriteReceipt | None: ...
    def prepare(self, owner: UUID, command: PrepareMediaReview) -> NativeWriteResult[None]: ...
    def apply(self, owner: UUID, command: MediaWriteCommand) -> NativeWriteResult[MediaNativeResult]: ...
    def read(self, owner: UUID, command: MediaWriteCommand) -> NativeWriteResult[MediaNativeResult]: ...


class LocalMediaImagePort(EvidenceRepository, Protocol):
    def local_transaction(self) -> AbstractContextManager[None]: ...
    def media_revision(self, owner: UUID) -> int: ...


class LocalMediaFilePort(MedicationLibraryFileRepository, Protocol):
    def local_transaction(self) -> AbstractContextManager[None]: ...
    def revision(self, owner: UUID) -> int: ...
    def references(self, owner: UUID, path: str) -> list[LibraryFileDTO]: ...
