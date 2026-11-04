"""Delete only a claimed immutable native key; settle facts separately from I/O."""

from ..contracts.workflow_media_cleanup import (
    MediaCleanupTicketPort,
    MediaDeleteObservation,
    MediaDeleteVerificationPort,
    NativeMediaDeleteStore,
    VerifiedMediaDeleteRef,
)
from ..contracts.workflow_persistence import NativeWriteResult
from ..domain.errors import DomainError, ProviderUnavailableError


class MediaCleanupVerificationService:
    def __init__(
        self,
        *,
        tickets: MediaCleanupTicketPort,
        storage: NativeMediaDeleteStore,
        verifier: MediaDeleteVerificationPort,
        clock,
    ):
        self._tickets, self._storage, self._verifier, self._clock = tickets, storage, verifier, clock

    def cleanup(self, owner, action_key):
        decision = self._tickets.start(owner, action_key)
        if isinstance(decision, NativeWriteResult):
            return decision
        if isinstance(decision, VerifiedMediaDeleteRef):
            return self._tickets.settle(owner, decision)
        ticket = decision
        if self._storage.bucket_id != ticket.bucket_id:
            raise ProviderUnavailableError("Native delete storage bucket differs from its bound target")
        self._tickets.claim(owner, ticket)
        try:
            self._storage.delete(ticket.object_ref)
            if self._storage.observe(ticket.object_ref) is not None:
                raise ProviderUnavailableError("Native file absence could not be confirmed")
            proof = self._verifier.record_media_delete(
                MediaDeleteObservation(
                    ticket_id=ticket.ticket_id,
                    nonce=ticket.nonce,
                    generation=ticket.generation,
                    result="absent_after_delete",
                    observed_at=self._clock.now(),
                    bucket_id=self._storage.bucket_id,
                ),
                timeout_seconds=3,
            )
        except Exception as error:
            try:
                self._verifier.record_media_delete(
                    MediaDeleteObservation(
                        ticket_id=ticket.ticket_id,
                        nonce=ticket.nonce,
                        generation=ticket.generation,
                        result="outcome_unknown",
                        observed_at=self._clock.now(),
                    ),
                    timeout_seconds=3,
                )
            except Exception:
                pass  # Persistent exclusion and unresolved ticket survive failed observation.
            if isinstance(error, DomainError):
                raise
            raise ProviderUnavailableError(
                "Native deletion is unresolved; inspect its ticket before retrying"
            ) from None
        # Settlement rollback cannot undo the external DELETE or erase its proof.
        return self._tickets.settle(owner, proof)
