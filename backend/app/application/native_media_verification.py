"""Verified storage for existing native APIs, without tasks, extra originals or callbacks."""

import hashlib
from uuid import UUID, uuid5

from ..contracts.agent_execution import current_execution
from ..contracts.native_media_verification import (
    NativeMediaDeleteIntent,
    NativeMediaIntentPort,
    NativeMediaObservation,
    NativeMediaObserver,
    NativeMediaStore,
    NativeMediaTarget,
    NativeMediaTicket,
    NativeMediaUploadIntent,
    VerifiedNativeMediaRef,
)
from ..contracts.ports import Clock
from ..domain.errors import DomainError, ProviderUnavailableError, ValidationError


class VerifiedNativeMediaStore:
    def __init__(
        self,
        *,
        owner: UUID,
        storage: NativeMediaStore,
        intents: NativeMediaIntentPort,
        verifier: NativeMediaObserver | None,
        clock: Clock,
    ):
        self._owner, self._storage, self._intents = owner, storage, intents
        self._verifier, self._clock = verifier, clock

    @property
    def bucket_id(self):
        return self._storage.bucket_id

    def _require_verifier(self):
        if current_execution.get() is not None:
            raise ProviderUnavailableError("Agent file writes require the existing bound media transaction")
        if self._verifier is None:
            raise ProviderUnavailableError("Native file verification is unavailable")

    def _observe(self, ticket: NativeMediaTicket, result, *, content=None):
        observation = NativeMediaObservation(
            ticket_id=ticket.ticket_id,
            nonce=ticket.nonce,
            generation=ticket.generation,
            result=result,
            observed_at=self._clock.now(),
            checksum=hashlib.sha256(content).hexdigest() if content is not None else None,
            byte_size=len(content) if content is not None else None,
            bucket_id=ticket.target.bucket_id if result != "outcome_unknown" else None,
        )
        proof = self._verifier.record_native_media(observation, timeout_seconds=3)
        if proof.ticket_id != ticket.ticket_id or proof.generation != ticket.generation or proof.result != result:
            raise ProviderUnavailableError("Native observation differs from its claimed ticket")
        return proof

    def _unknown(self, ticket):
        try:
            self._observe(ticket, "outcome_unknown")
        except Exception:
            pass  # An unrecorded/unknown external outcome cannot become a success or release an exclusion.

    def put(self, path: str, data: bytes) -> None:
        self._require_verifier()
        target = NativeMediaTarget.from_path(self._owner, self.bucket_id, path, byte_size=len(data))
        if hashlib.sha256(data).hexdigest() != target.checksum:
            raise ValidationError("Native bytes differ from their immutable file key")
        operation = uuid5(self._owner, f"native-upload:{self.bucket_id}:{path}")
        decision = self._intents.prepare_upload(
            self._owner, NativeMediaUploadIntent(operation_id=operation, target=target)
        )
        if isinstance(decision, VerifiedNativeMediaRef):
            if decision.result != "bytes_verified":
                raise ProviderUnavailableError("Native upload remains unresolved")
            return  # Actual proof recovered; never issue another writer after response loss.
        if decision.target != target or decision.operation != "upload":
            raise ProviderUnavailableError("Native upload ticket binding differs")
        self._intents.claim(self._owner, decision)
        try:
            self._storage.put(path, data)
            actual = self._storage.get(path)
            if actual != data:
                raise ProviderUnavailableError("Native stored bytes could not be verified")
            self._observe(decision, "bytes_verified", content=actual)
        except Exception as error:
            self._unknown(decision)
            if isinstance(error, DomainError):
                raise
            raise ProviderUnavailableError("Native upload outcome is unknown; inspect its intent") from None

    def get(self, path: str) -> bytes:
        self._owned_read(path)
        return self._storage.get(path)

    def observe(self, path: str) -> bytes | None:
        self._owned_read(path)
        return self._storage.observe(path)

    def _owned_read(self, path: str):
        # Retained pre-upgrade filenames remain readable; only new mutation
        # intents require canonical content keys. Reads never manufacture proof.
        if (
            not path.startswith(f"{self._owner}/")
            or len(path) > 400
            or ".." in path
            or any(char in path for char in "?%#\\")
            or any(not part for part in path.split("/"))
        ):
            raise ValidationError("Owned private file path required")

    def delete(self, path: str) -> None:
        self._require_verifier()
        self._owned_read(path)
        try:
            NativeMediaTarget.from_path(self._owner, self.bucket_id, path)
        except ValueError:
            raise ProviderUnavailableError("Historical native file requires verified writer reconciliation") from None
        operation = uuid5(self._owner, f"native-delete:{self.bucket_id}:{path}")
        decision = self._intents.prepare_delete(
            self._owner,
            NativeMediaDeleteIntent(
                operation_id=operation,
                owner=self._owner,
                bucket_id=self.bucket_id,
                object_ref=path,
            ),
        )
        if isinstance(decision, VerifiedNativeMediaRef):
            if decision.result != "absent_after_delete":
                raise ProviderUnavailableError("Native deletion remains unresolved")
            self._intents.settle_delete(self._owner, decision)
            return
        if (
            decision.operation != "delete"
            or decision.target.owner != self._owner
            or decision.target.bucket_id != self.bucket_id
            or decision.target.object_ref != path
        ):
            raise ProviderUnavailableError("Native delete ticket binding differs")
        self._intents.claim(self._owner, decision)
        try:
            self._storage.delete(path)
            if self._storage.observe(path) is not None:
                raise ProviderUnavailableError("Native file absence could not be verified")
            proof = self._observe(decision, "absent_after_delete")
        except Exception as error:
            self._unknown(decision)
            if isinstance(error, DomainError):
                raise
            raise ProviderUnavailableError("Native delete outcome is unknown; inspect its intent") from None
        self._intents.settle_delete(self._owner, proof)
