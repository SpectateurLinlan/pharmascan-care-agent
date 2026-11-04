"""Patient-only source saves from the current owned, verified raw original."""

from dataclasses import dataclass, field
from uuid import UUID, uuid5

from ..contracts.assistant_workflows import BusinessRef, ControlRepository, WorkflowContext, WorkflowRepository
from ..contracts.dto import RegimenDraftInput
from ..contracts.medication_evidence import EnrollmentTask, EvidenceSourcePublication, EvidenceSourceSnapshot
from ..domain.errors import StaleVersionError, ValidationError
from .enrollment_operations import EnrollmentOperationService
from .evidence_enrollment import EvidenceEnrollmentService
from .workflow_attachments import WorkflowAttachmentService


@dataclass(frozen=True)
class PreparedSourceOperation:
    workflow_task_id: UUID
    workflow_revision: int
    attachment_id: UUID
    publication: EvidenceSourcePublication | EnrollmentTask
    duplicate_snapshot: EvidenceSourceSnapshot | None = field(default=None,repr=False)


class SourceEnrollmentOperationService:
    def __init__(
        self,
        *,
        evidence: EvidenceEnrollmentService,
        originals: WorkflowAttachmentService,
        tasks: WorkflowRepository,
        controls: ControlRepository,
        operations: EnrollmentOperationService | None = None,
    ):
        self._evidence, self._originals = evidence, originals
        self._tasks, self._controls = tasks, controls
        self._operations = operations

    def save(self, context: WorkflowContext, target: UUID, attachment_id: UUID, action_key: UUID) -> EnrollmentTask:
        output = []

        def reconcile():
            self._checked(context, target)
            actual = self._evidence.saved_original_receipt(context.owner, action_key, context.task_id, attachment_id)
            if actual is not None and actual.id != target:
                raise ValidationError("Source receipt belongs to another registration")
            output.append(actual)

        if not self._controls.guarded_write(context.owner, context.task_id, context.revision, reconcile):
            raise StaleVersionError("Saving permission changed; the old source action cannot continue")
        return output[0] or self.publish(context, self.prepare(context, target, attachment_id), action_key)

    def resume_source(self, context: WorkflowContext, target: UUID, version: int) -> UUID:
        actual = self._evidence.get(context.owner, target)
        if actual.version != version:
            raise StaleVersionError("The source registration changed; choose its current version")
        authority = self._evidence.workflow_owner(context.owner, target)
        if authority is None and actual.draft_regimen_id and self._operations:
            binding = self._operations.binding(context.owner, actual.draft_regimen_id)
            authority = binding.workflow_task_id if binding else None
        if authority is None or authority == context.task_id:
            raise ValidationError("This source has no other saved task to resume")
        original = self._tasks.get(context.owner, authority)
        control = self._controls.get(context.owner, authority)
        if (
            original.capability_id not in {"medication.source.add", "medication.source.review"}
            or original.save_mode != "allowed"
            or control.mode != "allowed"
            or control.revoked
            or control.status not in {"idle", "suspended"}
            or original.state in {"cancelled", "completed"}
            or not any(
                (ref.kind == "enrollment_task" and ref.id == target)
                or (ref.kind == "regimen" and ref.id == actual.draft_regimen_id)
                for ref in original.business_refs
            )
        ):
            raise StaleVersionError("The original source task is unavailable; check its saving permission")
        return original.id

    def _checked(self, context: WorkflowContext, target: UUID, version: int | None = None, *, reviewing=False):
        task = self._tasks.get(context.owner, context.task_id)
        control = self._controls.get(context.owner, context.task_id)
        ref = next((row for row in task.business_refs if row.kind == "enrollment_task" and row.id == target), None)
        if (ref is None and not reviewing and context.capability_id == "medication.source.add"
            and target == uuid5(context.task_id, "source-registration")
            and BusinessRef(kind="media_review", id=context.task_id, version=context.revision) in task.business_refs):
            # Derived proposal ID only; not a persisted claim that a native row exists.
            ref = BusinessRef(kind="enrollment_task", id=target, version=1)
        if (
            context.capability_id
            not in ({"medication.source.add", "medication.source.review"} if reviewing else {"medication.source.add"})
            or task.capability_id != context.capability_id
            or task.save_mode != "allowed"
            or context.save_mode != "allowed"
            or task.revision != context.revision
            or control.status != "idle"
            or task.state != "awaiting_confirmation"
            or ref is None
            or (version is not None and ref.version != version)
        ):
            raise StaleVersionError("Reopen the current source-save review before continuing")
        return task, ref

    def review(
        self,
        context: WorkflowContext,
        target: UUID,
        *,
        draft: RegimenDraftInput,
        patient_reviewed: bool,
        distinct_product_confirmed: bool,
        product_category: str = "unknown",
        replace_active_plan: bool = False,
    ) -> EnrollmentTask:
        if self._operations is None:
            raise ValidationError("Source plan binding is unavailable")
        output = []

        def review():
            _task, ref = self._checked(context, target, reviewing=True)
            actual = self._evidence.get(context.owner, target)
            binding = (
                self._operations.binding(context.owner, actual.draft_regimen_id) if actual.draft_regimen_id else None
            )
            if actual.version != ref.version and not (
                actual.version == ref.version + 1
                and binding is not None
                and binding.workflow_task_id == context.task_id
            ):
                raise StaleVersionError("The source registration changed; reopen its current review")
            if binding is not None and binding.workflow_task_id != context.task_id:
                raise StaleVersionError("Continue the original saved source review")

            def bind(result: EnrollmentTask):
                self._operations.bind_source_once(
                    context.owner,
                    result,
                    action_key=uuid5(context.task_id, f"source-review:{target}"),
                    workflow_task_id=context.task_id,
                    workflow_revision=context.revision,
                )

            output.append(
                self._evidence.prepare_review(
                    patient_id=context.owner,
                    task_id=target,
                    draft=draft,
                    patient_reviewed=patient_reviewed,
                    distinct_product_confirmed=distinct_product_confirmed,
                    product_category=product_category,
                    replace_active_plan=replace_active_plan,
                    on_prepared=bind,
                    workflow_task_id=context.task_id,
                    expected_version=actual.version,
                )
            )

        if not self._controls.guarded_write(context.owner, context.task_id, context.revision, review):
            raise StaleVersionError("Saving permission changed; the old source review cannot continue")
        return output[0]

    def prepare(self, context: WorkflowContext, target: UUID, attachment_id: UUID) -> PreparedSourceOperation:
        output = []

        def prepare():
            output.append(self.prepare_request(context,target,attachment_id))

        if not self._controls.guarded_write(context.owner, context.task_id, context.revision, prepare):
            raise StaleVersionError("Saving permission changed before source preparation")
        return output[0]

    def prepare_request(self,context: WorkflowContext,target: UUID,attachment_id: UUID,
                        *, allocation_key: UUID | None = None, include_duplicate_snapshot: bool = False
                        ) -> PreparedSourceOperation:
        """Read-only current-source preparation, usable without a remote callback writer."""
        task,ref=self._checked(context,target)
        source=self._originals.enrollment_source(context.owner,context.task_id,attachment_id)
        original,_mime=self._originals.read(context.owner,context.task_id,attachment_id)
        medication=task.fields.get('medication_id')
        if medication is not None and not isinstance(medication,str):
            raise ValidationError('The selected medication reference is invalid')
        publication=self._evidence.prepare_source_proposal(context=context,source=source,original=original,
            task_id=target,medication_id=UUID(medication) if medication else None,allocation_key=allocation_key)
        version=((publication.prior_task.version if publication.prior_task else 1)
            if isinstance(publication,EvidenceSourcePublication) else publication.version)
        if ref.version!=version:
            raise StaleVersionError('The source registration changed; check its current version')
        snapshot=(self._evidence.duplicate_source_snapshot(context.owner,target,original,source.source_kind)
            if include_duplicate_snapshot and isinstance(publication,EnrollmentTask) else None)
        return PreparedSourceOperation(context.task_id,context.revision,attachment_id,publication,snapshot)

    def publish(self, context: WorkflowContext, prepared: PreparedSourceOperation, action_key: UUID) -> EnrollmentTask:
        output = []

        def save():
            if prepared.workflow_task_id != context.task_id or prepared.workflow_revision != context.revision:
                raise StaleVersionError("The source proposal belongs to another review")
            proposal = prepared.publication
            target = proposal.task.id if isinstance(proposal, EvidenceSourcePublication) else proposal.id
            version = (
                (proposal.prior_task.version if proposal.prior_task else 1)
                if isinstance(proposal, EvidenceSourcePublication)
                else proposal.version
            )
            self._checked(context, target, version)
            source = self._originals.enrollment_source(context.owner, context.task_id, prepared.attachment_id)
            original, _mime = self._originals.read(context.owner, context.task_id, prepared.attachment_id)
            if isinstance(proposal, EvidenceSourcePublication):
                actual = self._evidence.publish_verified_attachment(
                    context.owner, proposal, source, original, action_key
                )
            else:
                actual = self._evidence.bind_duplicate_original(context.owner, proposal, source, original, action_key)
            output.append(actual)

        if not self._controls.guarded_write(context.owner, context.task_id, context.revision, save):
            raise StaleVersionError("Saving permission changed; this source action cannot continue")
        return output[0]
