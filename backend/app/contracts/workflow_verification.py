"""Ticket-bound external observations; no clinical data or owner authority."""

from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from .assistant_workflows import WorkflowContext, WorkflowDTO
from .workflow_attachments import CleanupReceipt, OriginalAttachment, OriginalMime, validate_original_metadata
from .workflow_persistence import PositiveRevision, RunWriteBinding
from .workflow_run_control import RunControlState, RunWorkerCommand

Checksum = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
ByteSize = Annotated[int, Field(strict=True, gt=0, le=10 * 1024 * 1024)]
ObservationResult = Literal["bytes_verified", "absent_after_delete", "definitely_not_started", "outcome_unknown"]


class StorageOperationTicket(WorkflowDTO):
    ticket_id: UUID
    nonce: UUID = Field(repr=False)
    task_id: UUID
    attachment_id: UUID
    writer_id: UUID | None
    operation: Literal["upload", "delete"]
    generation: PositiveRevision
    object_ref: str = Field(min_length=1, max_length=300, repr=False)
    expected_checksum: Checksum
    content_type: OriginalMime
    byte_size: ByteSize
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def bound_operation(self):
        parts = self.object_ref.split("/")
        if len(parts) != 4 or parts[1] != "workflow-originals":
            raise ValueError("Invalid original operation binding")
        try:
            owner = UUID(parts[0])
        except ValueError:
            raise ValueError("Invalid original operation binding") from None
        if parts != [str(owner), "workflow-originals", str(self.task_id), str(self.attachment_id)]:
            raise ValueError("Invalid original operation binding")
        if (self.operation == "upload") != (self.writer_id is not None):
            raise ValueError("Each upload needs one writer; deletion cannot be a writer")
        kind = "library_pdf" if self.content_type == "application/pdf" else "package"
        validate_original_metadata(kind, self.content_type, self.byte_size)
        return self


class StorageObservation(WorkflowDTO):
    ticket_id: UUID
    nonce: UUID = Field(repr=False)
    generation: PositiveRevision
    result: ObservationResult
    checksum: Checksum | None = None
    byte_size: ByteSize | None = None
    observed_at: AwareDatetime

    @model_validator(mode="after")
    def observed_bytes(self):
        if self.result == "bytes_verified":
            if self.checksum is None or self.byte_size is None:
                raise ValueError("Actual byte verification requires checksum and size")
        elif self.checksum is not None or self.byte_size is not None:
            raise ValueError("This observation cannot assert saved bytes")
        return self


class VerifiedOperationRef(WorkflowDTO):
    ticket_id: UUID
    verification_id: UUID
    generation: PositiveRevision
    result: ObservationResult


class EvidenceVerificationPort(Protocol):
    def record_storage(self, observation: StorageObservation, *, timeout_seconds: float) -> VerifiedOperationRef: ...
    def record_run(self, command: RunWorkerCommand, *, timeout_seconds: float) -> RunControlState: ...


class VerifiedOriginalPort(Protocol):
    def get(self, owner: UUID, task_id: UUID, attachment_id: UUID) -> OriginalAttachment: ...
    def verification_for(self,owner: UUID,task_id: UUID,attachment_id: UUID) -> VerifiedOperationRef: ...
    def reserve_ticket(self, context: WorkflowContext, attachment_id: UUID, writer_id: UUID,
                       *, run_binding: RunWriteBinding | None = None) -> StorageOperationTicket: ...
    def claim_ticket(self, owner: UUID, ticket: StorageOperationTicket) -> None: ...
    def read_verified(self, owner: UUID, reference: VerifiedOperationRef) -> StorageOperationTicket: ...
    def settle_writer(self, owner: UUID, reference: VerifiedOperationRef) -> None: ...
    def publish_verified(self, context: WorkflowContext, attachment_id: UUID, reference: VerifiedOperationRef,
                         *, run_binding: RunWriteBinding | None = None) -> OriginalAttachment: ...
    def start_deleting(self, owner: UUID, attachment_id: UUID) -> StorageOperationTicket | CleanupReceipt: ...
    def settle_cleanup(self, owner: UUID, reference: VerifiedOperationRef) -> CleanupReceipt: ...
