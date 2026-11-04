"""Source preparation and actual patient-result capture; no clinical write executor."""

from uuid import UUID, uuid5

from ...contracts.assistant_workflows import (
    ActionRepository,
    AttachmentRef,
    BusinessRef,
    ChoiceAction,
    ChoiceOption,
    ExistingReviewAction,
    OperationResult,
    Preparation,
    ResumeTaskAction,
    UploadAction,
    WorkflowContext,
)
from ...contracts.enrollment_workflow import EnrollmentFields
from ...contracts.medication_sources import SOURCE_SCHEMAS, SourceAddFields, SourceReviewFields
from ...domain.errors import NotFoundError, StaleVersionError, ValidationError
from ..enrollment import MedicationEnrollmentService
from ..enrollment_operations import EnrollmentOperationService
from ..evidence_enrollment import EvidenceEnrollmentService
from ..source_operations import SourceEnrollmentOperationService
from .enrollment import EnrollmentAdapter


class SourceAdapter:
    capability_ids = frozenset(SOURCE_SCHEMAS)

    def __init__(
        self,
        *,
        evidence: EvidenceEnrollmentService,
        enrollment: MedicationEnrollmentService,
        enrollment_adapter: EnrollmentAdapter,
        operations: EnrollmentOperationService,
        actions: ActionRepository,
        source_operations: SourceEnrollmentOperationService | None = None,
    ):
        self._evidence, self._enrollment = evidence, enrollment_adapter
        self._medications = enrollment
        self._operations, self._actions = operations, actions
        self._source_operations = source_operations

    def resume_target(self, context: WorkflowContext, values: SourceAddFields | SourceReviewFields) -> UUID:
        if self._source_operations is None or values.source_task_id is None or values.expected_version is None:
            raise ValidationError("Choose the source registration to continue")
        return self._source_operations.resume_source(context, values.source_task_id, values.expected_version)

    def prepare(
        self,
        context: WorkflowContext,
        values: SourceAddFields | SourceReviewFields,
        assets: tuple[AttachmentRef, ...],
        results: tuple[BusinessRef, ...] = (),
    ) -> Preparation:
        prepared = self._prepare(context, values, assets, results)
        inputs = values.model_dump(mode="json", exclude_none=True)
        if len(results) == 1:
            ref = results[0]
            target = ref.id if ref.kind == "enrollment_task" else None
            if ref.kind == "regimen":
                regimen = self._medications.get_regimen(context.owner, ref.id)
                target = regimen.evidence_task_id if regimen else None
            if target is not None:
                try:
                    actual = self._evidence.get(context.owner, target)
                except NotFoundError:
                    pass
                else:
                    inputs.update(source_task_id=str(actual.id), expected_version=actual.version)
        return prepared.model_copy(update={"input_fields": inputs})

    def _prepare(
        self,
        context: WorkflowContext,
        values: SourceAddFields | SourceReviewFields,
        assets: tuple[AttachmentRef, ...],
        results: tuple[BusinessRef, ...] = (),
    ) -> Preparation:
        if context.capability_id not in self.capability_ids:
            raise ValidationError("This is not a source workflow")
        visible = values.model_dump(mode="json", exclude_none=True)
        if isinstance(values, SourceAddFields) and values.medication_id is not None:
            if self._medications.get_medication(context.owner, values.medication_id) is None:
                raise NotFoundError("Medication not found")
        if results:
            if len(results) != 1:
                raise ValidationError("Source review needs one owned reference")
            ref = results[0]
            if ref.kind == "media_review":
                if context.capability_id != "medication.source.add" or ref.id != context.task_id:
                    raise StaleVersionError("The source preparation marker changed")
                if ref.version != context.revision:
                    # Control/attachment changes invalidate a review, without
                    # making the retained source task unreadable or implying a save.
                    return self._prepare(context, values, assets)
                return Preparation(
                    workflow_state="awaiting_confirmation", prompt_key="assistant.source.patient_review",
                    view_fields={**visible, "source_saved": False,
                        "source_task_id": str(uuid5(context.task_id, "source-registration"))},
                    result_ref=ref,
                    actions=(ExistingReviewAction(
                        component_key="existing_source_review", owned_ref=ref, expected_version=ref.version,
                    ),),
                )
            if ref.kind == "regimen":
                binding = self._operations.binding(context.owner, ref.id)
                if binding is None or binding.workflow_task_id != context.task_id or binding.version_no != ref.version:
                    raise StaleVersionError("Continue the original saved source review")
                return self._enrollment.prepare(context, EnrollmentFields(), (), results)
            if ref.kind != "enrollment_task":
                raise ValidationError("This is not a source registration")
            try:
                actual = self._evidence.get(context.owner, ref.id)
            except NotFoundError:
                if context.capability_id != "medication.source.add" or ref.id != uuid5(
                    context.task_id, "source-registration"
                ):
                    return Preparation(
                        workflow_state="outcome_unknown", prompt_key="assistant.source.changed", result_ref=ref
                    )
                actual = None
            if actual and (actual.version != ref.version or actual.draft_regimen_id is not None):
                return Preparation(
                    workflow_state="failed_recoverable", prompt_key="assistant.source.changed", result_ref=ref
                )
            return Preparation(
                workflow_state="awaiting_confirmation",
                prompt_key="assistant.source.patient_review",
                view_fields={**visible, "source_saved": actual is not None, "source_task_id": str(ref.id)},
                result_ref=ref,
                actions=(
                    ExistingReviewAction(
                        component_key="existing_source_review", owned_ref=ref, expected_version=ref.version
                    ),
                ),
            )
        if isinstance(values, SourceReviewFields) and values.source_task_id is None:
            rows = self._evidence.list(context.owner)
            count = max(1, (len(rows) + 9) // 10)
            page = values.page if values.page < count else 0
            choices = tuple(
                ChoiceOption(
                    value=f"{row.id}:{row.version}",
                    label_key="assistant.source.select",
                    label_text=f"{row.product.name} {row.product.strength or ''}"[:200],
                )
                for row in rows[page * 10 : page * 10 + 10]
            )
            actions = [ChoiceAction(action_id="source.target", options=choices)] if choices else []
            pages = tuple(
                ChoiceOption(value=f"page:{number}", label_key=key)
                for number, key in (
                    (page - 1, "assistant.medication.previous"),
                    (page + 1, "assistant.medication.next"),
                )
                if 0 <= number < count
            )
            if pages:
                actions.append(ChoiceAction(action_id="source.page", options=pages))
            return Preparation(
                prompt_key="assistant.source.choose",
                missing_fields=("source_task_id",),
                view_fields={**visible, "page": page, "page_count": count},
                actions=tuple(actions),
            )
        if values.source_task_id is not None:
            actual = self._evidence.get(context.owner, values.source_task_id)
            authority = self._evidence.workflow_owner(context.owner, actual.id)
            if authority is None and actual.draft_regimen_id is not None:
                binding = self._operations.binding(context.owner, actual.draft_regimen_id)
                authority = binding.workflow_task_id if binding else None
            if authority is not None and authority != context.task_id:
                try:
                    self.resume_target(context, values)
                except (NotFoundError, StaleVersionError, ValidationError):
                    return Preparation(
                        workflow_state="failed_recoverable",
                        prompt_key="assistant.source.changed",
                        view_fields=visible,
                    )
                return Preparation(
                    prompt_key="assistant.source.resume_original",
                    view_fields=visible,
                    actions=(
                        ResumeTaskAction(
                            owned_ref=BusinessRef(kind="enrollment_task", id=actual.id, version=actual.version),
                            expected_version=actual.version,
                        ),
                    )
                    if context.save_mode == "allowed"
                    else (),
                )
            if values.expected_version != actual.version:
                return Preparation(
                    workflow_state="failed_recoverable",
                    prompt_key="assistant.source.changed",
                    view_fields=visible,
                )
            if actual.draft_regimen_id is not None:
                binding = self._operations.binding(context.owner, actual.draft_regimen_id)
                if binding is None or binding.workflow_task_id != context.task_id:
                    raise StaleVersionError("Continue the original saved source task")
                return Preparation(
                    workflow_state="ready_for_review", prompt_key="assistant.source.ready", view_fields=visible
                )
        if isinstance(values, SourceAddFields):
            ready = [row for row in assets if row.extraction_status == "succeeded"]
            if values.source_attachment_id is not None and not any(
                row.id == values.source_attachment_id for row in ready
            ):
                raise ValidationError("Choose a successful original from this task")
            if not ready:
                return Preparation(
                    prompt_key="assistant.enrollment.upload_source",
                    missing_fields=("source_image",),
                    view_fields=visible,
                    actions=(UploadAction(action_id="source_image"),),
                )
        return Preparation(workflow_state="ready_for_review", prompt_key="assistant.source.ready", view_fields=visible)

    def reconcile(self, context: WorkflowContext, action_key: UUID) -> BusinessRef | None:
        try:
            receipt = self._actions.read(context.owner, action_key)
        except NotFoundError:
            return None
        if receipt.task_id != context.task_id or receipt.capability_id != context.capability_id:
            raise ValidationError("The source preparation belongs to another task")
        return receipt.business_ref

    def prepare_once(self, context: WorkflowContext, values, assets, action_key: UUID) -> BusinessRef:
        prior = self.reconcile(context, action_key)
        if prior:
            return prior
        if context.save_mode != "allowed" or self.prepare(context, values, assets).workflow_state != "ready_for_review":
            raise ValidationError("Complete the source preparation first")
        ref = BusinessRef(
            kind="enrollment_task",
            id=values.source_task_id or uuid5(context.task_id, "source-registration"),
            version=values.expected_version or 1,
        )
        if values.source_task_id is not None:
            actual = self._evidence.get(context.owner, values.source_task_id)
            if actual.draft_regimen_id is not None:
                binding = self._operations.binding(context.owner, actual.draft_regimen_id)
                if binding is None or binding.workflow_task_id != context.task_id:
                    raise StaleVersionError("Continue the original saved source task")
                ref = BusinessRef(kind="regimen", id=binding.regimen_id, version=binding.version_no)
        receipt = self._actions.reserve(context, action_key)
        self._actions.complete(context, receipt.model_copy(update={"business_ref": ref}))
        return ref

    def read_patient_result(self, context: WorkflowContext, result_ref: BusinessRef, values=None) -> BusinessRef:
        if result_ref.kind == "regimen":
            return result_ref
        if result_ref.kind != "enrollment_task":
            raise ValidationError("Source results need a source registration reference")
        try:
            actual = self._evidence.get(context.owner, result_ref.id)
        except NotFoundError:
            return result_ref  # Missing data is never proof of success.
        if actual.draft_regimen_id is not None:
            binding = self._operations.binding(context.owner, actual.draft_regimen_id)
            if (
                binding
                and binding.workflow_task_id == context.task_id
                and binding.medication_id == actual.medication_id
            ):
                return BusinessRef(kind="regimen", id=binding.regimen_id, version=binding.version_no)
        elif self._evidence.workflow_owner(context.owner, actual.id) == context.task_id:
            return BusinessRef(kind="enrollment_task", id=actual.id, version=actual.version)
        return result_ref

    def revise_inputs(self, context: WorkflowContext, result_ref: BusinessRef):
        raise ValidationError("Continue the prepared source review or start a separate task")

    def observe(self, context: WorkflowContext, result_ref: BusinessRef) -> OperationResult:
        if result_ref.kind == "regimen":
            return self._enrollment.observe(context, result_ref)
        return OperationResult(state="pending", business_ref=result_ref)
