"""Request-triggered cleanup; object completion and metadata revocation stay distinct."""

from uuid import UUID

from ..contracts.assistant_workflows import ActionRepository, ControlRepository, WorkflowRepository, WorkflowView
from ..contracts.enrollment_operations import EnrollmentWritePort
from ..contracts.medication_evidence import EvidenceOriginalReferences
from ..contracts.ports import IdGenerator
from ..contracts.workflow_attachments import (
    AttachmentProtectionPort,
    CleanupReceipt,
    CleanupRepository,
    CleanupStatus,
    OriginalRepository,
    ProtectionResult,
    WorkflowAttachmentStore,
)
from ..domain.errors import DomainError, ProviderUnavailableError
from .enrollment import MedicationEnrollmentService
from .workflow_verification import WorkflowVerificationService


class ExistingSourceProtection:
    def __init__(
        self,
        *,
        receipts: CleanupRepository,
        enrollment: MedicationEnrollmentService,
        tasks: WorkflowRepository,
        actions: ActionRepository,
        enrollments: EnrollmentWritePort | None = None,
        evidence: EvidenceOriginalReferences | None = None,
    ):
        self._receipts, self._enrollment = receipts, enrollment
        self._tasks = tasks
        self._actions = actions
        self._enrollments = enrollments
        self._evidence = evidence

    def references(self, owner: UUID, attachment_id: UUID) -> ProtectionResult:
        receipt = self._receipts.get(owner, attachment_id)
        source_ids = self._evidence.original_sources(owner, attachment_id) if self._evidence else ()
        if source_ids:
            return ProtectionResult(
                protected=True,
                reason="formal_source"
                if all(self._enrollment.get_source(owner, source_id) for source_id in source_ids)
                else "reference_unresolved",
            )
        binding = self._enrollments.for_attachment(owner, attachment_id) if self._enrollments else None
        if binding:
            return ProtectionResult(
                protected=True,
                reason="formal_source"
                if self._enrollment.get_source(owner, binding.source_id)
                else "reference_unresolved",
            )
        # Gallery uploads materialize bytes into a different native object. No
        # copy-operation receipt references this raw draft object's private key.
        # Formal-source and shared-reference protection still applies.
        actions = tuple(action for action in self._actions.list(owner, receipt.task_id)
                        if action.capability_id not in {"gallery.photo.add", "library.pdf.add"})
        if any(action.state in {"pending", "outcome_unknown"} for action in actions):
            return ProtectionResult(protected=True, reason="operation_unknown")
        if any(action.business_ref is not None for action in actions):
            return ProtectionResult(protected=True, reason="business_record")
        if any(
            task.id != receipt.task_id
            and (
                attachment_id in task.attachment_ids
                or any(ref.kind == "file" and ref.id == attachment_id for ref in task.business_refs)
            )
            for task in self._tasks.list(owner)
        ):
            return ProtectionResult(protected=True, reason="shared_reference")
        if receipt.source_ref is None:
            return ProtectionResult(protected=False, reason="exclusive")
        if (
            receipt.source_ref.kind == "source"
            and self._enrollment.get_source(owner, receipt.source_ref.id) is not None
        ):
            return ProtectionResult(protected=True, reason="formal_source")
        return ProtectionResult(protected=True, reason="reference_unresolved")


class WorkflowCleanupService:
    def __init__(
        self,
        *,
        controls: ControlRepository,
        repository: CleanupRepository,
        originals: OriginalRepository,
        storage: WorkflowAttachmentStore | None,
        protection: AttachmentProtectionPort,
        ids: IdGenerator,
        verification: WorkflowVerificationService | None = None,
    ):
        self._controls, self._repository, self._originals = controls, repository, originals
        self._storage, self._protection, self._ids = storage, protection, ids
        self._verification = verification

    def revoke(self, owner: UUID, task_id: UUID, revision: int, event_id: UUID):
        control = self._controls.revoke(owner, task_id, revision, event_id)
        self.retry_cleanup(owner, task_id)
        return control

    def written(self, owner: UUID, task_id: UUID, attachment_id: UUID, writer_id: UUID | None = None) -> bool:
        if self._verification is not None:
            raise ProviderUnavailableError("A matching independently verified writer observation is required")
        if self._originals.note_written(owner, task_id, attachment_id, writer_id):
            return True
        # A late object write must reactivate its receipt, never its cancelled task.
        self._repository.mark_written(owner, task_id, attachment_id, writer_id)
        self.retry_cleanup(owner, task_id)
        return False

    def status(self, owner: UUID, task_id: UUID) -> CleanupStatus:
        self._controls.get(owner, task_id)
        rows = self._repository.list(owner, task_id)
        return CleanupStatus(
            pending=any(
                row.writer_pending or row.state in {"pending", "failed"} or row.reason == "operation_unknown"
                for row in rows
            ),
            protected=any(row.state == "protected" for row in rows),
        )

    def retry_cleanup(self, owner: UUID, task_id: UUID) -> tuple[CleanupReceipt, ...]:
        self._controls.get(owner, task_id)
        if self._verification is not None:
            for row in self._repository.list(owner, task_id):
                if row.state in {"deleted", "protected"}:
                    continue
                try:
                    self._verification.cleanup(owner, row.id)
                except DomainError:
                    continue  # Retain pending exclusion/proof; never infer that I/O ended.
            return self._repository.list(owner, task_id)
        for row in self._repository.list(owner, task_id):
            if row.state == "deleted":
                continue
            if row.writer_pending:
                if self._storage is None:
                    continue
                try:
                    self._storage.read(owner, row.object_ref)
                except DomainError:
                    continue  # Absence cannot establish that an in-flight write has finished.
                self._repository.mark_written(owner, task_id, row.id)
                row = self._repository.get(owner, row.id)
                if row.writer_pending:
                    continue  # A newer same-key object does not acknowledge an older writer.
            try:
                protection = self._protection.references(owner, row.id)
            except DomainError:
                self._repository.update(row.model_copy(update={"state": "pending", "reason": "protection_unavailable"}))
                continue
            if protection.protected:
                self._repository.update(row.model_copy(update={"state": "protected", "reason": protection.reason}))
                continue
            try:
                if self._storage is None:
                    raise ProviderUnavailableError("Original image storage is unavailable")
                deleted = self._storage.delete(owner, row.object_ref)
            except DomainError:
                self._repository.update(row.model_copy(update={"state": "pending", "reason": "storage_unavailable"}))
            else:
                self._repository.update(
                    row.model_copy(
                        update={
                            "state": "deleted" if deleted.state == "deleted" else "pending",
                            "reason": "removed" if deleted.state == "deleted" else "storage_unavailable",
                        }
                    )
                )
        return self._repository.list(owner, task_id)

    def cancel_save(self, owner: UUID, task_id: UUID, expected_revision: int) -> WorkflowView:
        control = self.revoke(owner, task_id, expected_revision, self._ids.new_id())
        status = self.status(owner, task_id)
        return WorkflowView(
            task_id=task_id,
            revision=control.revision,
            capability_id=control.capability_id,
            state=control.status if control.status in {"cancelled", "completed", "suspended"} else "failed_recoverable",
            save_mode="ephemeral",
            storage_state="cleanup_pending" if status.pending else "ephemeral",
            cleanup_pending=status.pending,
            protected_originals=status.protected,
            prompt_key="assistant.workflow.cleanup_pending"
            if status.pending
            else ("assistant.workflow.source_retained" if status.protected else "assistant.workflow.ephemeral_lost"),
        )
