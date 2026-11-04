"""Correlated native deletion, distinct from a tombstone or raw-original proof."""

from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime, Field, TypeAdapter, model_validator

from .assistant_workflows import BusinessRef, WorkflowDTO
from .workflow_media_writes import MediaNativeResult
from .workflow_persistence import NativeWriteResult, PositiveRevision
from .workflow_verification import Checksum


class MediaDeleteTicket(WorkflowDTO):
    ticket_id: UUID
    nonce: UUID = Field(repr=False)
    generation: PositiveRevision
    owner: UUID
    task_id: UUID
    task_revision: PositiveRevision
    action_key: UUID
    media_kind: Literal["photo", "pdf"]
    medication_id: UUID
    native_ref: BusinessRef
    object_ref: str = Field(max_length=400, repr=False)
    checksum: Checksum
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def native_object_only(self):
        expected = (
            f"{self.owner}/{self.medication_id}/{self.checksum}.png"
            if self.media_kind == "photo"
            else f"{self.owner}/library/{self.medication_id}/{self.checksum}.pdf"
        )
        if self.object_ref != expected or self.native_ref.kind != "file" or self.native_ref.version is None:
            raise ValueError("Native deletion requires the actual canonical owned media reference")
        return self

    @property
    def bucket_id(self):
        return "visual-references" if self.media_kind == "photo" else "medication-sources"


class MediaDeleteObservation(WorkflowDTO):
    ticket_id: UUID
    nonce: UUID = Field(repr=False)
    generation: PositiveRevision
    result: Literal["absent_after_delete", "outcome_unknown"]
    observed_at: AwareDatetime
    bucket_id: Literal["visual-references", "medication-sources"] | None = None

    @model_validator(mode="after")
    def actual_storage_namespace(self):
        if (self.result == "absent_after_delete") != (self.bucket_id is not None):
            raise ValueError("Only actual correlated absence can assert the observed storage bucket")
        return self


class VerifiedMediaDeleteRef(WorkflowDTO):
    family: Literal["native_media_delete"] = "native_media_delete"
    ticket_id: UUID
    verification_id: UUID
    generation: PositiveRevision
    result: Literal["absent_after_delete", "outcome_unknown"]


class MediaCleanupSettlement(WorkflowDTO):
    owner: UUID
    action_key: UUID
    native_ref: BusinessRef
    proof: VerifiedMediaDeleteRef
    recorded_at: AwareDatetime


class MediaDeleteReady(WorkflowDTO):
    kind: Literal["ticket"] = "ticket"
    ticket: MediaDeleteTicket


class MediaDeleteVerified(WorkflowDTO):
    kind: Literal["verified"] = "verified"
    ticket: MediaDeleteTicket
    proof: VerifiedMediaDeleteRef

    @model_validator(mode="after")
    def exact_proof(self):
        if (
            self.proof.ticket_id != self.ticket.ticket_id
            or self.proof.generation != self.ticket.generation
            or self.proof.result != "absent_after_delete"
        ):
            raise ValueError("Actual native deletion proof must match its ticket")
        return self


class MediaDeleteSettled(WorkflowDTO):
    kind: Literal["settled"] = "settled"
    result: NativeWriteResult[MediaNativeResult]


MEDIA_CLEANUP_DECISION = TypeAdapter(
    Annotated[MediaDeleteReady | MediaDeleteVerified | MediaDeleteSettled, Field(discriminator="kind")]
)


class MediaDeleteVerificationPort(Protocol):
    def record_media_delete(
        self, observation: MediaDeleteObservation, *, timeout_seconds: float
    ) -> VerifiedMediaDeleteRef: ...


class MediaCleanupTicketPort(Protocol):
    def start(
        self, owner: UUID, action_key: UUID
    ) -> MediaDeleteTicket | VerifiedMediaDeleteRef | NativeWriteResult[MediaNativeResult]: ...
    def claim(self, owner: UUID, ticket: MediaDeleteTicket) -> None: ...
    def settle(self, owner: UUID, proof: VerifiedMediaDeleteRef) -> NativeWriteResult[MediaNativeResult]: ...


class NativeMediaDeleteStore(Protocol):
    @property
    def bucket_id(self) -> str: ...
    def delete(self, path: str) -> None: ...
    def observe(self, path: str) -> bytes | None:
        """None means an independently observed absence, never an I/O error."""
        ...
