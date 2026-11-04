"""Technical native-copy evidence, isolated from raw-original publication."""

from typing import Literal, Protocol
from uuid import UUID, uuid5

from pydantic import AwareDatetime, Field, model_validator

from .assistant_workflows import WorkflowContext, WorkflowDTO
from .workflow_persistence import PositiveRevision, RunWriteBinding
from .workflow_verification import ByteSize, Checksum, VerifiedOperationRef


class MediaCopyTarget(WorkflowDTO):
    owner: UUID
    medication_id: UUID
    native_id: UUID
    media_kind: Literal["photo", "pdf", "source_image"]
    source_kind: Literal["package", "pharmacy_label", "prescription"] | None = None
    checksum: Checksum
    content_type: Literal["image/png", "application/pdf"]
    byte_size: ByteSize

    @model_validator(mode="after")
    def native_identity(self):
        photo = self.media_kind != "pdf"
        native_id = (
            uuid5(
                self.medication_id,
                self.checksum + (self.source_kind or "") if self.media_kind == "source_image" else self.checksum,
            )
            if photo
            else uuid5(self.owner, f"medication-library-pdf:{self.medication_id}:{self.checksum}")
        )
        if (
            self.native_id != native_id
            or self.content_type != ("image/png" if photo else "application/pdf")
            or (photo and self.byte_size > 8_000_000)
            or (self.media_kind == "source_image") != (self.source_kind is not None)
        ):
            raise ValueError("Native media identity or size differs from the existing public upload policy")
        return self

    @property
    def bucket_id(self):
        return "visual-references" if self.media_kind != "pdf" else "medication-sources"

    @property
    def object_ref(self):
        if self.media_kind != "pdf":
            return f"{self.owner}/{self.medication_id}/{self.checksum}.png"
        return f"{self.owner}/library/{self.medication_id}/{self.checksum}.pdf"


class MediaStorageTicket(WorkflowDTO):
    ticket_id: UUID
    nonce: UUID = Field(repr=False)
    task_id: UUID
    task_revision: PositiveRevision
    capability_id: str
    attachment_id: UUID
    writer_id: UUID
    generation: PositiveRevision
    source_checksum: Checksum
    source_byte_size: ByteSize
    target: MediaCopyTarget
    expires_at: AwareDatetime


class MediaStorageObservation(WorkflowDTO):
    ticket_id: UUID
    nonce: UUID = Field(repr=False)
    generation: PositiveRevision
    result: Literal["bytes_verified", "definitely_not_started", "outcome_unknown"]
    source_checksum: Checksum | None = None
    checksum: Checksum | None = None
    byte_size: ByteSize | None = None
    bucket_id: Literal["visual-references", "medication-sources"] | None = None
    observed_at: AwareDatetime

    @model_validator(mode="after")
    def observed_transformation(self):
        actual = (self.source_checksum, self.checksum, self.byte_size, self.bucket_id)
        if (
            self.result == "bytes_verified"
            and any(value is None for value in actual)
            or self.result != "bytes_verified"
            and any(value is not None for value in actual)
        ):
            raise ValueError("Only actual source-to-native byte verification can assert checksums")
        return self


class VerifiedMediaOperationRef(VerifiedOperationRef):
    family: Literal["native_media"] = "native_media"


class MediaCopyVerificationPort(Protocol):
    def record_media_storage(
        self, observation: MediaStorageObservation, *, timeout_seconds: float
    ) -> VerifiedMediaOperationRef: ...


class MediaCopyTicketPort(Protocol):
    def recover(
        self, context: WorkflowContext, attachment_id: UUID, target: MediaCopyTarget,
    ) -> VerifiedMediaOperationRef | None: ...

    def reserve(
        self,
        context: WorkflowContext,
        attachment_id: UUID,
        writer_id: UUID,
        target: MediaCopyTarget,
        *,
        run_binding: RunWriteBinding | None = None,
    ) -> MediaStorageTicket: ...
    def claim(self, owner: UUID, ticket: MediaStorageTicket) -> None: ...
    def read_verified(self, owner: UUID, reference: VerifiedMediaOperationRef) -> MediaStorageTicket: ...
    def assert_current_copy(
        self, context: WorkflowContext, reference: VerifiedMediaOperationRef
    ) -> MediaStorageTicket: ...
