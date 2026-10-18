"""The route cannot turn a delete into an unconfirmed/agent-proposed write."""

from uuid import UUID

from ..contracts.draft_deletion import DraftDeletionPort, DraftDeletionResult, DraftKind
from ..domain.errors import ConfirmationRequiredError


class DraftDeletionService:
    def __init__(self, repository: DraftDeletionPort):
        self._repository = repository

    def delete(self, owner: UUID, kind: DraftKind, target: UUID, confirmed: bool) -> DraftDeletionResult:
        if confirmed is not True:
            raise ConfirmationRequiredError("Confirm deletion of this draft first.")
        return self._repository.delete(owner, kind, target)
