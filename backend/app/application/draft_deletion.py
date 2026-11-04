"""The route cannot turn a delete into an unconfirmed/agent-proposed write."""

from uuid import UUID

from ..contracts.draft_deletion import DraftDeletionPort, DraftDeletionReceiptReader, DraftDeletionResult, DraftKind
from ..domain.errors import ConfirmationRequiredError, ProviderUnavailableError


class DraftDeletionService:
    def __init__(self, repository: DraftDeletionPort, *, receipts: DraftDeletionReceiptReader | None = None):
        self._repository = repository
        self._receipts = receipts

    def receipt(self, owner: UUID, kind: DraftKind, target: UUID) -> DraftDeletionResult | None:
        if self._receipts is None:
            raise ProviderUnavailableError("Deletion receipt lookup is unavailable for this environment")
        return self._receipts.receipt(owner, kind, target)

    def delete(self, owner: UUID, kind: DraftKind, target: UUID, confirmed: bool) -> DraftDeletionResult:
        if confirmed is not True:
            raise ConfirmationRequiredError("Confirm deletion of this draft first.")
        return self._repository.delete(owner, kind, target)
