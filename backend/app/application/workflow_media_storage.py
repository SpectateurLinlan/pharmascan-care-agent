"""Observe source normalization and actual native bytes, never a storage ACK."""

import hashlib
from uuid import uuid4

from ..contracts.workflow_media_storage import (
    MediaCopyTarget,
    MediaCopyTicketPort,
    MediaCopyVerificationPort,
    MediaStorageObservation,
)
from ..domain.errors import DomainError, ProviderUnavailableError, StaleVersionError
from .library_files import is_basic_pdf


class MediaCopyVerificationService:
    def __init__(
        self,
        *,
        tickets: MediaCopyTicketPort,
        originals,
        source_storage,
        target_storage,
        verifier: MediaCopyVerificationPort,
        clock,
        normalize,
        source_normalize=None,
    ):
        self._tickets, self._originals = tickets, originals
        self._source_storage, self._target_storage = source_storage, target_storage
        self._verifier, self._clock, self._normalize = verifier, clock, normalize
        self._source_normalize=source_normalize

    def copy(self, context, attachment_id, target, *, run_binding=None, writer_id=None):
        target = MediaCopyTarget.model_validate(target.model_dump())
        if self._target_storage.bucket_id != target.bucket_id:
            raise ProviderUnavailableError("Native copy storage bucket differs from its bound target")
        if target.media_kind=='source_image' and self._source_normalize is None:
            raise ProviderUnavailableError('Source image normalization is not composed')
        original = self._originals.get(context.owner, context.task_id, attachment_id)
        content = self._source_storage.read(context.owner, original.object_ref)
        if len(content) != original.byte_size or hashlib.sha256(content).hexdigest() != original.original_checksum:
            raise StaleVersionError("Actual source bytes differ from the saved original")
        if target.media_kind == "pdf":
            if not is_basic_pdf(content):
                raise StaleVersionError("Original PDF signature cannot be verified")
            native = content
        elif target.media_kind=='source_image':
            if original.source_kind!=target.source_kind:
                raise StaleVersionError('Source copy purpose differs from its actual saved original')
            native=self._source_normalize(content)
        else:
            native = self._normalize(content)
        if len(native) != target.byte_size or hashlib.sha256(native).hexdigest() != target.checksum:
            raise StaleVersionError("Native copy differs from the actual normalized original")
        ticket = self._tickets.reserve(context, attachment_id, writer_id or uuid4(), target, run_binding=run_binding)
        self._tickets.claim(context.owner, ticket)
        try:
            self._target_storage.put(target.object_ref, native)
            observed = self._target_storage.get(target.object_ref)
            if observed != native:
                raise ProviderUnavailableError("Native copy bytes could not be confirmed")
            observation = MediaStorageObservation(
                ticket_id=ticket.ticket_id,
                nonce=ticket.nonce,
                generation=ticket.generation,
                result="bytes_verified",
                source_checksum=hashlib.sha256(content).hexdigest(),
                checksum=hashlib.sha256(observed).hexdigest(),
                byte_size=len(observed),
                bucket_id=self._target_storage.bucket_id,
                observed_at=self._clock.now(),
            )
            return self._verifier.record_media_storage(observation, timeout_seconds=3)
        except Exception as error:
            try:
                self._verifier.record_media_storage(
                    MediaStorageObservation(
                        ticket_id=ticket.ticket_id,
                        nonce=ticket.nonce,
                        generation=ticket.generation,
                        result="outcome_unknown",
                        observed_at=self._clock.now(),
                    ),
                    timeout_seconds=3,
                )
            except Exception:
                pass  # Issued/inflight metadata remains unresolved; never infer no effect.
            if isinstance(error, DomainError):
                raise
            raise ProviderUnavailableError(
                "Native copy outcome is unresolved; inspect its ticket before retrying"
            ) from None
