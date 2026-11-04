"""Change recorded instructions through the existing independent review flow."""

from uuid import UUID

from pydantic import JsonValue

from ...contracts.assistant_workflows import (
    AttachmentRef,
    BusinessRef,
    ChoiceAction,
    ChoiceOption,
    FieldFormAction,
    OperationResult,
    Preparation,
    WorkflowContext,
    WorkflowRepository,
)
from ...contracts.enrollment_operations import PlanChangeOperationInput
from ...contracts.enrollment_workflow import EnrollmentFields
from ...contracts.medication_plan_changes import PlanChangeDetails, PlanChangeFields
from ...domain.errors import NotFoundError, StaleVersionError, ValidationError
from ..enrollment import MedicationEnrollmentService
from ..enrollment_operations import EnrollmentOperationService
from .enrollment import EnrollmentAdapter


class PlanChangeAdapter:
    def __init__(
        self,
        enrollment: MedicationEnrollmentService,
        operations: EnrollmentOperationService,
        delegate: EnrollmentAdapter,
        tasks: WorkflowRepository,
    ):
        self._enrollment, self._operations = enrollment, operations
        self._delegate, self._tasks = delegate, tasks

    @staticmethod
    def _original(row):
        return {
            "regimen_id": str(row.id),
            "version_no": row.version_no,
            "state": row.state.value,
            "frequency_rule": row.frequency_rule,
            "dose_amount": row.dose_amount,
            "dose_unit": row.dose_unit,
            "is_prn": row.is_prn,
            "course_start_date": str(row.course_start_date) if row.course_start_date else None,
            "course_end_date": str(row.course_end_date) if row.course_end_date else None,
        }

    def prepare(
        self,
        context: WorkflowContext,
        values: PlanChangeFields,
        assets: tuple[AttachmentRef, ...],
        results: tuple[BusinessRef, ...] = (),
    ) -> Preparation:
        if assets:
            raise ValidationError("Use the source workflow to change product evidence")
        inputs = values.model_dump(mode="json", exclude_none=True)
        if results:
            if len(results) != 1 or results[0].kind != "regimen":
                raise ValidationError("Plan changes require one prepared regimen")
            ref = results[0]
            binding = self._operations.binding(context.owner, ref.id)
            if binding is None or binding.workflow_task_id != context.task_id:
                raise ValidationError("The prepared plan belongs to a different task")
            row = self._enrollment.get_regimen(context.owner, ref.id)
            if row is None:
                raise NotFoundError("The prepared plan is unavailable")
            prepared = self._delegate.prepare(context, EnrollmentFields(), (), results)
            if row.state.value in {"draft", "pending_clarification"} and row.supersedes_id:
                old = self._enrollment.get_regimen(context.owner, row.supersedes_id)
                if old is None or old.state.value != "active":
                    prepared = Preparation(
                        workflow_state="failed_recoverable",
                        result_ref=ref,
                        prompt_key="assistant.enrollment.result_changed",
                    )
            old = self._enrollment.get_regimen(context.owner, values.regimen_id) if values.regimen_id else None
            return prepared.model_copy(
                update={
                    "input_fields": inputs,
                    "view_fields": {**prepared.view_fields, "original_plan": self._original(old) if old else None},
                }
            )
        if values.regimen_id is None:
            choices = [
                (medication, row)
                for medication in self._enrollment.list_medications(context.owner)
                for row in self._enrollment.list_regimens(context.owner, medication.id)
                if row.state.value in {"active", "ended", "superseded"}
            ]
            pages = max(1, (len(choices) + 9) // 10)
            page = values.page if values.page < pages else 0
            actions = []
            current = choices[page * 10 : page * 10 + 10]
            if current:
                actions.append(
                    ChoiceAction(
                        action_id="medication.change_target",
                        options=tuple(
                            ChoiceOption(
                                value=f"{row.id}:{row.version_no}:{row.state.value}",
                                label_key="assistant.medication.select_plan",
                                label_text=f"{med.display_name[:145]} / v{row.version_no} / "
                                + (
                                    {"active": "启用中", "ended": "已结束", "superseded": "已替换"}[row.state.value]
                                    if context.language == "zh"
                                    else {"active": "Active", "ended": "Ended", "superseded": "Replaced"}[
                                        row.state.value
                                    ]
                                ),
                            )
                            for med, row in current
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
                input_fields={**inputs, "page": page},
                prompt_key="assistant.plan_change.choose" if choices else "assistant.plan_change.empty",
                missing_fields=("regimen_id",),
                view_fields={"page": page, "page_count": pages},
                actions=tuple(actions),
            )
        try:
            proposed = self._operations.plan_change_preview(
                context.owner,
                values.regimen_id,
                values.expected_version,
                values.expected_state,
                values.details,
            )
        except StaleVersionError:
            # A stale background task must not break the patient's whole task list.
            return Preparation(
                input_fields=inputs,
                workflow_state="failed_recoverable",
                prompt_key="assistant.enrollment.result_changed",
            )
        visible = proposed.fields.model_dump(mode="json", exclude_none=True)
        changes = {
            key: value
            for key, value in proposed.fields.model_dump(mode="json").items()
            if key in PlanChangeDetails.model_fields
        }
        if changes.get("frequency_rule"):
            changes["frequency_rule"].pop("interval_anchor", None)
        visible.update(change_inputs=changes, original_plan=self._original(proposed.target))
        missing = proposed.preview.missing_fields
        if not proposed.changed:
            missing = (*missing, "changed_instructions")
        ready = proposed.changed and not missing and not proposed.preview.conflicts
        return Preparation(
            input_fields=inputs,
            view_fields=visible,
            missing_fields=missing,
            workflow_state="ready_for_review" if ready else "collecting",
            prompt_key="assistant.enrollment.interval_default"
            if proposed.preview.defaults
            else "assistant.plan_change.review"
            if ready
            else "assistant.plan_change.edit",
            actions=(FieldFormAction(schema_id="medication.enroll:v1", field_names=missing),),
        )

    def prepare_once(
        self, context: WorkflowContext, values: PlanChangeFields, assets: tuple[AttachmentRef, ...], action_key: UUID
    ) -> BusinessRef:
        if context.save_mode != "allowed" or assets or values.regimen_id is None:
            raise ValidationError("Choose a saved plan and enable saving before preparing review")
        if self.prepare(context, values, assets).workflow_state != "ready_for_review":
            raise ValidationError("Enter and check the changed instructions first")
        result = self._operations.prepare_plan_change_once(
            context.owner,
            PlanChangeOperationInput(
                action_key=action_key,
                workflow_task_id=context.task_id,
                workflow_revision=context.revision,
                predecessor_id=values.regimen_id,
                expected_version=values.expected_version,
                expected_state=values.expected_state,
                fields=values.details or PlanChangeDetails(),
            ),
        )
        return BusinessRef(kind="regimen", id=result.regimen.id, version=result.regimen.version_no)

    def reconcile(self, context: WorkflowContext, action_key: UUID) -> BusinessRef | None:
        binding = self._operations.receipt(context.owner, action_key) if context.save_mode == "allowed" else None
        if binding is None:
            return None
        if binding.workflow_task_id != context.task_id:
            raise ValidationError("The plan-change receipt belongs to a different task")
        return BusinessRef(kind="regimen", id=binding.regimen_id, version=binding.version_no)

    def revise_inputs(self, context: WorkflowContext, result_ref: BusinessRef) -> dict[str, JsonValue]:
        fields = self._delegate.revise_inputs(context, result_ref)
        task = self._tasks.get(context.owner, context.task_id)
        values = PlanChangeFields.model_validate(task.fields)
        details = {key: value for key, value in fields.items() if key in PlanChangeDetails.model_fields}
        if details.get("frequency_rule"):
            details["frequency_rule"].pop("interval_anchor", None)
        return values.model_copy(update={"details": PlanChangeDetails.model_validate(details)}).model_dump(
            mode="json",
            exclude_none=True,
        )

    def observe(self, context: WorkflowContext, result_ref: BusinessRef) -> OperationResult:
        return self._delegate.observe(context, result_ref)
