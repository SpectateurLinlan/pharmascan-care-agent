"""Public, explicitly confirmed unfinished-registration operation."""

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
