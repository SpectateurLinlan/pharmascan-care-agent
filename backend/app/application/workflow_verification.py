"""Actual Storage I/O and narrow technical proof are distinct from patient publication."""

import hashlib
from uuid import UUID

from ..contracts.agent_execution import current_execution
from ..contracts.assistant_workflows import WorkflowContext
from ..contracts.ports import Clock
from ..contracts.workflow_attachments import AttachmentView, CleanupReceipt, WorkflowAttachmentStore
from ..contracts.workflow_verification import (
    EvidenceVerificationPort,
    StorageObservation,
    StorageOperationTicket,
    VerifiedOperationRef,
    VerifiedOriginalPort,
)
from ..domain.errors import DomainError, NotFoundError, ProviderUnavailableError, ValidationError


class WorkflowVerificationService:
    def __init__(
        self,
        *,
        repository: VerifiedOriginalPort,
        storage: WorkflowAttachmentStore,
        verifier: EvidenceVerificationPort,
        clock: Clock,
    ):
        self._repository, self._storage, self._verifier, self._clock = repository, storage, verifier, clock

    def _observation(self, ticket, result, *, content=None):
        return StorageObservation(
            ticket_id=ticket.ticket_id,
            nonce=ticket.nonce,
            generation=ticket.generation,
            result=result,
            observed_at=self._clock.now(),
            checksum=hashlib.sha256(content).hexdigest() if content is not None else None,
            byte_size=len(content) if content is not None else None,
        )

    def settle(self, observation: StorageObservation) -> VerifiedOperationRef:
        return self._verifier.record_storage(observation, timeout_seconds=3)

    def _unknown(self, ticket):
        try:
            self.settle(self._observation(ticket, "outcome_unknown"))
        except DomainError:
            pass  # Failure to record uncertainty cannot become a success receipt.

    def save(self, context: WorkflowContext, attachment_id: UUID, writer_id: UUID, content: bytes) -> AttachmentView:
        row = self._repository.get(context.owner, context.task_id, attachment_id)
        if len(content) != row.byte_size or hashlib.sha256(content).hexdigest() != row.original_checksum:
            raise ValidationError("Original bytes differ from the reserved upload")
        execution = current_execution.get()
        if execution is not None:
            execution.check()
            if not hasattr(execution, "write_binding"):
                raise ProviderUnavailableError("A durable run binding is required")
        binding = execution.write_binding if execution is not None else None
        ticket = self._repository.reserve_ticket(context, attachment_id, writer_id, run_binding=binding)
        self._repository.claim_ticket(context.owner, ticket)
        try:
            # A storage acknowledgement is not an observation. Read independently.
            self._storage.put_original(
                context.owner, context.task_id, writer_id, content, row.content_type, object_ref=ticket.object_ref
            )
            observed = self._storage.read(context.owner, ticket.object_ref)
            if observed != content:
                raise ProviderUnavailableError("Original bytes could not be confirmed")
            proof = self.settle(self._observation(ticket, "bytes_verified", content=observed))
        except DomainError:
            self._unknown(ticket)
            raise
        # Even a cancelled upload settles its own writer; publication rechecks consent/run.
        self._repository.settle_writer(context.owner, proof)
        saved = self._repository.publish_verified(context, attachment_id, proof, run_binding=binding)
        return AttachmentView(**saved.model_dump(include=set(AttachmentView.model_fields)))

    def cleanup(self, owner: UUID, attachment_id: UUID) -> CleanupReceipt:
        decision = self._repository.start_deleting(owner, attachment_id)
        if isinstance(decision, CleanupReceipt):
            return decision
        ticket: StorageOperationTicket = decision
        self._repository.claim_ticket(owner, ticket)
        try:
            result = self._storage.delete(owner, ticket.object_ref)
            if result.state != "deleted":
                raise ProviderUnavailableError("Deletion is unresolved")
            try:
                self._storage.read(owner, ticket.object_ref)
            except NotFoundError:
                pass  # Only after this particular synchronous delete ended.
            else:
                raise ProviderUnavailableError("The original still exists")
            proof = self.settle(self._observation(ticket, "absent_after_delete"))
        except DomainError:
            self._unknown(ticket)
            raise
        return self._repository.settle_cleanup(owner, proof)
