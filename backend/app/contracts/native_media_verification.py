"""Task-independent native file facts. Never source identity or clinical authority."""

import re
from typing import Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from .assistant_workflows import BusinessRef, WorkflowDTO
from .workflow_verification import ByteSize, Checksum


class NativeMediaTarget(WorkflowDTO):
    owner: UUID
    bucket_id: Literal["visual-references", "medication-sources"]
    object_ref: str = Field(min_length=1, max_length=400, repr=False)
    checksum: Checksum
    content_type: Literal["image/png", "application/pdf"]
    byte_size: ByteSize | None = None

    @classmethod
    def from_path(cls, owner: UUID, bucket_id: str, path: str, *, byte_size: int | None = None):
        parts = path.split("/")
        pdf = bucket_id == "medication-sources"
        if len(parts) != (4 if pdf else 3) or parts[0] != str(owner) or pdf and parts[1] != "library":
            raise ValueError("Canonical owned native file path required")
        medication_id = UUID(parts[-2])
        suffix = ".pdf" if pdf else ".png"
        digest = parts[-1].removesuffix(suffix)
        expected = f"{owner}/" + ("library/" if pdf else "") + f"{medication_id}/{digest}{suffix}"
        if path != expected or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("Canonical native file checksum required")
        return cls(
            owner=owner,
            bucket_id=bucket_id,
            object_ref=path,
            checksum=digest,
            content_type="application/pdf" if pdf else "image/png",
            byte_size=byte_size,
        )

    @model_validator(mode="after")
    def exact_namespace(self):
        pdf = self.bucket_id == "medication-sources"
        parts = self.object_ref.split("/")
        if len(parts) != (4 if pdf else 3):
            raise ValueError("Canonical owned native file path required")
        medication_id = UUID(parts[-2])
        expected = f"{self.owner}/" + ("library/" if pdf else "") + f"{medication_id}/{self.checksum}"
        expected += ".pdf" if pdf else ".png"
        if (
            self.object_ref != expected
            or self.content_type != ("application/pdf" if pdf else "image/png")
            or not pdf
            and self.byte_size is not None
            and self.byte_size > 8_000_000
        ):
            raise ValueError("Native file namespace, MIME or size differs")
        return self


class NativeMediaUploadIntent(WorkflowDTO):
    operation_id: UUID
    target: NativeMediaTarget

    @model_validator(mode="after")
    def known_bytes(self):
        if self.target.byte_size is None:
            raise ValueError("Native upload needs exact byte size")
        return self


class NativeMediaDeleteIntent(WorkflowDTO):
    operation_id: UUID
    owner: UUID
    bucket_id: Literal["visual-references", "medication-sources"]
    object_ref: str = Field(max_length=400, repr=False)

    @model_validator(mode="after")
    def owned_target(self):
        NativeMediaTarget.from_path(self.owner, self.bucket_id, self.object_ref)
        return self


class NativeMediaTicket(WorkflowDTO):
    ticket_id: UUID
    nonce: UUID = Field(repr=False)
    generation: int = Field(strict=True, ge=1)
    operation: Literal["upload", "delete"]
    target: NativeMediaTarget
    expires_at: AwareDatetime
    native_ref: BusinessRef | None = None


class NativeMediaObservation(WorkflowDTO):
    ticket_id: UUID
    nonce: UUID = Field(repr=False)
    generation: int = Field(strict=True, ge=1)
    result: Literal["bytes_verified", "absent_after_delete", "outcome_unknown"]
    observed_at: AwareDatetime
    checksum: Checksum | None = None
    byte_size: ByteSize | None = None
    bucket_id: Literal["visual-references", "medication-sources"] | None = None

    @model_validator(mode="after")
    def actual_observation(self):
        if self.result == "bytes_verified":
            valid = self.checksum is not None and self.byte_size is not None and self.bucket_id is not None
        elif self.result == "absent_after_delete":
            valid = self.checksum is None and self.byte_size is None and self.bucket_id is not None
        else:
            valid = self.checksum is None and self.byte_size is None and self.bucket_id is None
        if not valid:
            raise ValueError("Only actual correlated bytes or absence can assert native facts")
        return self


class VerifiedNativeMediaRef(WorkflowDTO):
    family: Literal["native_object"] = "native_object"
    ticket_id: UUID
    verification_id: UUID
    generation: int = Field(strict=True, ge=1)
    result: Literal["bytes_verified", "absent_after_delete", "outcome_unknown"]


class NativeMediaIntentPort(Protocol):
    def prepare_upload(
        self, owner: UUID, intent: NativeMediaUploadIntent
    ) -> NativeMediaTicket | VerifiedNativeMediaRef: ...
    def prepare_delete(
        self, owner: UUID, intent: NativeMediaDeleteIntent
    ) -> NativeMediaTicket | VerifiedNativeMediaRef: ...
    def claim(self, owner: UUID, ticket: NativeMediaTicket) -> None: ...
    def settle_delete(self, owner: UUID, proof: VerifiedNativeMediaRef) -> None: ...


class NativeMediaObserver(Protocol):
    def record_native_media(
        self, observation: NativeMediaObservation, *, timeout_seconds: float
    ) -> VerifiedNativeMediaRef: ...


class NativeMediaStore(Protocol):
    @property
    def bucket_id(self) -> str: ...
    def put(self, path: str, data: bytes) -> None: ...
    def get(self, path: str) -> bytes: ...
    def observe(self, path: str) -> bytes | None: ...
    def delete(self, path: str) -> None: ...
