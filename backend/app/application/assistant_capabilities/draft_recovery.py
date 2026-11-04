"""Recover owned unfinished regimens without replacing prior task authority."""

from uuid import UUID

from ...contracts.assistant_workflows import (
    AttachmentRef,
    BusinessRef,
    ChoiceAction,
    ChoiceOption,
    ControlRepository,
    OperationResult,
    Preparation,
    ResumeTaskAction,
    WorkflowContext,
    WorkflowRepository,
)
from ...contracts.enrollment_workflow import EnrollmentFields
from ...contracts.medication_management import ClinicalMutationGuard, MedicationDraftResumeFields
from ...domain.errors import NotFoundError, StaleVersionError, ValidationError
from ..enrollment import MedicationEnrollmentService
from ..enrollment_operations import EnrollmentOperationService
from .enrollment import EnrollmentAdapter


class DraftRecoveryAdapter:
    def __init__(
        self,
        enrollment: MedicationEnrollmentService,
        operations: EnrollmentOperationService,
        delegate: EnrollmentAdapter,
        tasks: WorkflowRepository,
        controls: ControlRepository,
        clinical: ClinicalMutationGuard,
        *,
        source_capabilities: frozenset[str] = frozenset(),
        plan_change_enabled: bool = False,
    ):
        self._enrollment, self._operations, self._delegate = enrollment, operations, delegate
        self._tasks, self._controls = tasks, controls
        self._clinical = clinical
        self._source_capabilities = source_capabilities & {"medication.source.add", "medication.source.review"}
        self._plan_capabilities = {"medication.plan.change"} if plan_change_enabled else set()

    def run_patient_action(self, context, result_ref, write):
        def checked():
            row = self._enrollment.resume_draft(context.owner, result_ref.id).regimen
            if row.version_no != result_ref.version:
                raise StaleVersionError("Reopen the current saved draft review")
            return write()

        return self._clinical.run(context.owner, self._clinical.revision(context.owner), checked)

    def _target(self, context: WorkflowContext, values: MedicationDraftResumeFields):
        if values.regimen_id is None:
            raise ValidationError("Choose a saved unfinished plan")
        result = self._enrollment.resume_draft(context.owner, values.regimen_id)
        if values.expected_version is not None and result.regimen.version_no != values.expected_version:
            raise StaleVersionError("The draft version changed; choose its current version")
        return result

    def resume_target(self, context: WorkflowContext, values: MedicationDraftResumeFields) -> UUID:
        row = self._target(context, values).regimen
        binding = self._operations.binding(context.owner, row.id)
        if binding is None or binding.workflow_task_id in {None, context.task_id}:
            raise ValidationError("This draft has no other saved task to resume")
        original = self._tasks.get(context.owner, binding.workflow_task_id)
        control = self._controls.get(context.owner, original.id)
        ref = BusinessRef(kind="regimen", id=row.id, version=row.version_no)
        if (
            original.save_mode != "allowed"
            or control.mode != "allowed"
            or control.revoked
            or original.state in {"completed", "cancelled"}
            or control.status in {"processing", "interrupted"}
            or original.capability_id
            not in {
                "medication.enroll",
                "medication.draft.resume",
                *self._source_capabilities,
                *self._plan_capabilities,
            }
            or not (
                ref in original.business_refs
                or original.capability_id in self._source_capabilities
                and row.evidence_task_id is not None
                and any(
                    item.kind == "enrollment_task" and item.id == row.evidence_task_id
                    for item in original.business_refs
                )
            )
        ):
            raise StaleVersionError("The original enrollment cannot be resumed with this draft")
        return original.id

    def _fields(self, context, values, result):
        fields = values.details or self._enrollment.review_inputs(context.owner, result.regimen.id)
        if (
            fields.method != "manual"
            or fields.source_attachment_id is not None
            or fields.distinct_product_confirmed
            or fields.existing_medication_id not in {None, result.medication.id}
            or fields.medication_name != result.medication.display_name
        ):
            raise ValidationError("Recovery cannot replace a saved product identity or its original evidence")
        return fields.model_copy(update={"existing_medication_id": result.medication.id})

    def prepare(self, context, values: MedicationDraftResumeFields, assets: tuple[AttachmentRef, ...], results=()):
        if assets:
            raise ValidationError("Supplementary sources use the source workflow")
        inputs = values.model_dump(mode="json", exclude_none=True)
        if results:
            if len(results) != 1 or results[0].kind != "regimen":
                raise ValidationError("Draft recovery requires one owned regimen")
            prepared = self._delegate.prepare(context, EnrollmentFields(), (), results)
            fields = self._enrollment.review_inputs(context.owner, results[0].id).model_dump(
                mode="json", exclude_none=True
            )
            return prepared.model_copy(
                update={"input_fields": inputs, "view_fields": {**prepared.view_fields, "recovery_inputs": fields}}
            )
        if values.regimen_id is None:
            if values.details is not None:
                raise ValidationError("Choose the draft before editing its details")
            choices = [
                (medication, row)
                for medication in self._enrollment.list_medications(context.owner)
                for row in self._enrollment.list_regimens(context.owner, medication.id)
                if row.state.value in {"draft", "pending_clarification"}
            ]
            pages = max(1, (len(choices) + 9) // 10)
            page = values.page if values.page < pages else 0
            actions = []
            current = choices[page * 10 : page * 10 + 10]
            if current:
                actions.append(
                    ChoiceAction(
                        action_id="medication.resume_target",
                        options=tuple(
                            ChoiceOption(
                                value=f"{row.id}:{row.version_no}",
                                label_key="assistant.medication.select_draft",
                                label_text=f"{medication.display_name[:170]} · v{row.version_no}",
                            )
                            for medication, row in current
                        ),
                    )
                )
            navigation = tuple(
                ChoiceOption(value=f"page:{number}", label_key=key)
                for number, key in (
                    (page - 1, "assistant.medication.previous"),
                    (page + 1, "assistant.medication.next"),
                )
                if 0 <= number < pages
            )
            if navigation:
                actions.append(ChoiceAction(action_id="medication.page", options=navigation))
            return Preparation(
                prompt_key="assistant.medication.choose_resume" if choices else "assistant.medication.no_drafts",
                input_fields={**inputs, "page": page},
                missing_fields=("regimen_id",),
                view_fields={"page": page, "page_count": pages},
                actions=tuple(actions),
            )
        current = self._enrollment.get_regimen(context.owner, values.regimen_id)
        if current is not None and current.state.value not in {"draft", "pending_clarification"}:
            try:
                prior = self._tasks.get(context.owner, context.task_id)
            except NotFoundError:
                raise ValidationError("Only an unfinished regimen can be resumed") from None
            if (
                prior.fields.get("regimen_id") != str(current.id)
                or prior.fields.get("expected_version") != values.expected_version
            ):
                raise ValidationError("Only an unfinished regimen can be resumed")
            return Preparation(
                workflow_state="failed_recoverable",
                prompt_key="assistant.enrollment.result_changed",
                input_fields=inputs,
            )
        result = self._target(context, values)
        binding = self._operations.binding(context.owner, result.regimen.id)
        if binding and binding.workflow_task_id not in {None, context.task_id}:
            try:
                self.resume_target(context, values)
            except (NotFoundError, StaleVersionError):
                return Preparation(
                    workflow_state="failed_recoverable",
                    input_fields=inputs,
                    prompt_key="assistant.medication.original_unavailable",
                )
            return Preparation(
                prompt_key="assistant.medication.resume_original",
                input_fields=inputs,
                view_fields={"medication_name": result.medication.display_name},
                actions=(
                    ResumeTaskAction(
                        owned_ref=BusinessRef(kind="regimen", id=result.regimen.id, version=result.regimen.version_no),
                        expected_version=result.regimen.version_no,
                    ),
                )
                if context.save_mode == "allowed"
                else (),
            )
        if result.regimen.evidence_task_id is not None:
            return Preparation(
                workflow_state="failed_recoverable",
                prompt_key="assistant.medication.resume_source",
                input_fields=inputs,
            )
        fields = self._fields(context, values, result)
        prepared = self._delegate.prepare(context, fields, ())
        return prepared.model_copy(
            update={
                "input_fields": inputs,
                "view_fields": {
                    **prepared.view_fields,
                    "recovery_inputs": fields.model_dump(mode="json", exclude_none=True),
                },
            }
        )

    def reconcile(self, context, action_key):
        return self._delegate.reconcile(context, action_key)

    def prepare_once(self, context, values: MedicationDraftResumeFields, assets, action_key):
        if context.save_mode != "allowed":
            raise ValidationError("Enable saving before recovering the draft")
        result = self._target(context, values)
        if result.regimen.evidence_task_id is not None:
            raise ValidationError("Continue the original source registration to reconcile its evidence")
        binding = self._operations.binding(context.owner, result.regimen.id)
        if binding and binding.workflow_task_id not in {None, context.task_id}:
            raise ValidationError("Resume the original saved enrollment instead")
        if values.details is not None:
            return self._delegate.prepare_once(context, self._fields(context, values, result), assets, action_key)
        receipt = self._operations.bind_existing_once(
            context.owner,
            result.regimen.id,
            result.regimen.version_no,
            action_key=action_key,
            workflow_task_id=context.task_id,
            workflow_revision=context.revision,
        )
        return BusinessRef(kind="regimen", id=receipt.regimen_id, version=receipt.version_no)

    def revise_inputs(self, context, ref):
        fields = self._delegate.revise_inputs(context, ref)
        return {"regimen_id": str(ref.id), "expected_version": ref.version, "details": fields}

    def observe(self, context, ref: BusinessRef) -> OperationResult:
        return self._delegate.observe(context, ref)
