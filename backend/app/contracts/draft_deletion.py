"""Public, explicitly confirmed unfinished-registration operation."""

from contextlib import AbstractContextManager
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

DraftKind = Literal["draft", "source"]


class DraftDeletionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    deleted: Literal[True] = True
    medication_deleted: bool
    cleanup_pending: bool = False


class DraftDeletionPort(Protocol):
    def delete(self, owner: UUID, kind: DraftKind, target: UUID) -> DraftDeletionResult: ...


class DraftDeletionReceiptReader(Protocol):
    def receipt(self, owner: UUID, kind: DraftKind, target: UUID) -> DraftDeletionResult | None: ...


class LocalDraftDeletionMetadataPort(DraftDeletionReceiptReader, Protocol):
    """Explicit local adapter scope; remote coupling must use one fixed SQL command."""
    def local_transaction(self) -> AbstractContextManager[None]: ...
    def current_version(self, owner: UUID, kind: DraftKind, target: UUID) -> int | None: ...
    def delete_metadata(self, owner: UUID, kind: DraftKind, target: UUID) -> DraftDeletionResult: ...
