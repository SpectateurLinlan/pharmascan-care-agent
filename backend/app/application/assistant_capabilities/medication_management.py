"""Owned medication reads and patient-reviewed maintenance over public services."""

from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

from ...contracts.assistant_workflows import (
    ActionRepository,
    AttachmentRef,
    BusinessRef,
    ChoiceAction,
    ChoiceOption,
    ExistingReviewAction,
    OperationResult,
    Preparation,
    WorkflowContext,
)
from ...contracts.medication_management import (
    MEDICATION_MANAGEMENT_SCHEMAS,
    ClinicalMutationGuard,
    MedicationDraftDeleteFields,
    MedicationPlanEndFields,
    MedicationPlanFields,
    MedicationSetupFields,
)
from ...domain.errors import NotFoundError, StaleVersionError, ValidationError
from ..draft_deletion import DraftDeletionService
from ..enrollment import MedicationEnrollmentService
from ..evidence_enrollment import EvidenceEnrollmentService

T = TypeVar("T")


class MedicationManagementAdapter:
    capability_ids = frozenset(MEDICATION_MANAGEMENT_SCHEMAS)

    def __init__(
        self,
        enrollment: MedicationEnrollmentService,
        evidence: EvidenceEnrollmentService,
        actions: ActionRepository | None = None,
        deletion: DraftDeletionService | None = None,
        clinical_guard: ClinicalMutationGuard | None = None,
    ):
        self._enrollment, self._evidence = enrollment, evidence
        self._actions = actions
        self._deletion = deletion
        self._clinical = clinical_guard

    def _delete_binding(self, context: WorkflowContext, ref: BusinessRef):
        rows = self._actions.list(context.owner, context.task_id) if self._actions else ()
        return max(
            (
                row
                for row in rows
                if row.capability_id == context.capability_id
                and row.business_ref == ref
                and row.binding_revision <= context.revision
            ),
            key=lambda row: row.binding_revision,
            default=None,
        )

    def run_patient_action(self, context: WorkflowContext, result_ref: BusinessRef, write: Callable[[], T]) -> T:
        if context.capability_id != "medication.draft.delete" or self._deletion is None:
            raise ValidationError("This patient action guard is unavailable")
        kind = "draft" if result_ref.kind == "regimen" else "source"
        if self._deletion.receipt(context.owner, kind, result_ref.id) is not None:
            return write()  # Existing deletion receipt authorizes only its idempotent cleanup retry.
        binding = self._delete_binding(context, result_ref)
        if self._clinical is None or binding is None or binding.clinical_revision is None:
            raise StaleVersionError("Reopen the current draft deletion review")

        def checked():
            fields = MedicationDraftDeleteFields(
                kind=kind, target_id=result_ref.id, expected_version=result_ref.version
            )
            if self._delete(context, fields, (result_ref,)).workflow_state != "awaiting_confirmation":
                raise StaleVersionError("The draft changed; review its deletion again")
            return write()

        return self._clinical.run(context.owner, binding.clinical_revision, checked)

    def _delete(self, context: WorkflowContext, values: MedicationDraftDeleteFields, results: tuple[BusinessRef, ...]):
        if self._deletion is None:
            raise ValidationError("Draft deletion receipt lookup is unavailable")
        ref = results[0] if len(results) == 1 else None
        if results and (ref is None or ref.kind not in {"regimen", "enrollment_task"}):
            raise ValidationError("Deletion needs one owned draft reference")
        kind = ("draft" if ref.kind == "regimen" else "source") if ref else values.kind
        target = ref.id if ref else values.target_id
        expected = ref.version if ref else values.expected_version
        if target is None:
            pending = [
                row
                for row in self._evidence.list(context.owner)
                if row.status in {"pending_information", "conflict", "ready_for_review"}
            ]
            linked = {row.draft_regimen_id for row in pending if row.draft_regimen_id}
            choices = [
                ChoiceOption(
                    value=f"source:{row.id}:{row.version}",
                    label_key="assistant.medication.select_draft",
                    label_text=f"{row.product.name[:120]} {(row.product.strength or '')[:60]}",
                )
                for row in pending
            ]
            for medication in self._enrollment.list_medications(context.owner):
                for row in self._enrollment.list_regimens(context.owner, medication.id):
                    if row.state.value in {"draft", "pending_clarification"} and row.id not in linked:
                        choices.append(
                            ChoiceOption(
                                value=f"draft:{row.id}:{row.version_no}",
                                label_key="assistant.medication.select_draft",
                                label_text=f"{medication.display_name[:170]} · v{row.version_no}",
                            )
                        )
            return Preparation(
                prompt_key="assistant.medication.choose_delete" if choices else "assistant.medication.no_drafts",
                input_fields=values.model_dump(mode="json", exclude_none=True),
                view_fields={"records": [], "source_tasks": []},
                missing_fields=("target_id",) if choices else (),
                actions=tuple(
                    ChoiceAction(action_id="medication.delete_target", options=tuple(choices[i : i + 10]))
                    for i in range(0, len(choices), 10)
                ),
            )
        inputs = {"kind": kind, "target_id": str(target), **({"expected_version": expected} if expected else {})}
        receipt = self._deletion.receipt(context.owner, kind, target)
        if receipt is not None:
            return Preparation(
                workflow_state="awaiting_confirmation" if receipt.cleanup_pending else "completed",
                prompt_key="assistant.medication.delete_cleanup"
                if receipt.cleanup_pending
                else "assistant.medication.deleted",
                input_fields=inputs,
                view_fields={**inputs, **receipt.model_dump(mode="json"), "records": [], "source_tasks": []},
                result_ref=ref,
                actions=(
                    ExistingReviewAction(
                        component_key="existing_draft_delete", owned_ref=ref, expected_version=ref.version
                    ),
                )
                if receipt.cleanup_pending and ref
                else (),
            )
        try:
            if kind == "draft":
                row = self._owned_plan(context.owner, target)
                medication = self._enrollment.get_medication(context.owner, row.patient_medication_id)
                if medication is None:
                    raise NotFoundError("Medication not found")
                version = row.version_no
                name = medication.display_name
                protected = row.state.value not in {"draft", "pending_clarification"}
                records = [{"medication_id": str(medication.id), "display_name": name, "plans": [self._plan(row)]}]
                sources = []
            else:
                row = self._evidence.get(context.owner, target)
                version = row.version
                name = f"{row.product.name} {row.product.strength or ''}".strip()
                protected = row.status not in {"pending_information", "conflict", "ready_for_review", "draft_created"}
                if row.draft_regimen_id is not None:
                    linked_plan = self._enrollment.get_regimen(context.owner, row.draft_regimen_id)
                    protected = (
                        protected
                        or linked_plan is None
                        or linked_plan.state.value not in {"draft", "pending_clarification"}
                    )
                records = []
                sources = [
                    {
                        "task_id": str(row.id),
                        "display_name": name,
                        "status": row.status,
                        "conflicting": bool(row.conflicts),
                    }
                ]
        except NotFoundError:
            if not ref:
                raise
            return Preparation(
                workflow_state="outcome_unknown",
                prompt_key="assistant.medication.deletion_unknown",
                input_fields=inputs,
                view_fields={**inputs, "records": [], "source_tasks": []},
                result_ref=ref,
            )
        if protected:
            if not ref:
                raise ValidationError("Confirmed or historical records cannot be deleted as drafts")
            return Preparation(
                workflow_state="failed_recoverable",
                prompt_key="assistant.medication.deletion_changed",
                input_fields=inputs,
                view_fields={**inputs, "records": records, "source_tasks": sources},
                result_ref=ref,
            )
        binding = self._delete_binding(context, ref) if ref else None
        changed = ref is not None and (
            binding is None
            or binding.clinical_revision is None
            or self._clinical is None
            or self._clinical.revision(context.owner) != binding.clinical_revision
        )
        if (expected is not None and version != expected) or changed:
            if ref:
                return Preparation(
                    workflow_state="failed_recoverable",
                    prompt_key="assistant.medication.deletion_changed",
                    input_fields=inputs,
                    view_fields={**inputs, "records": records, "source_tasks": sources},
                    result_ref=ref,
                )
            raise StaleVersionError("The draft changed; review the current version before deleting")
        inputs = {"kind": kind, "target_id": str(target), "expected_version": version}
        medication_id = row.patient_medication_id if kind == "draft" else row.medication_id
        plans = self._enrollment.list_regimens(context.owner, medication_id)
        whole = not any(plan.state.value in {"active", "ended", "superseded"} for plan in plans)
        selected_plan = target if kind == "draft" else row.draft_regimen_id
        affected_plans = [plan for plan in plans if whole or plan.id == selected_plan]
        affected_ids = {plan.id for plan in affected_plans}
        affected_sources = [
            task
            for task in self._evidence.list(context.owner)
            if task.medication_id == medication_id
            and (whole or task.id == target or task.draft_regimen_id in affected_ids)
        ]
        medication = self._enrollment.get_medication(context.owner, medication_id)
        records = (
            [
                {
                    "medication_id": str(medication_id),
                    "display_name": medication.display_name if medication else name,
                    "plans": [self._plan(plan) for plan in affected_plans],
                }
            ]
            if affected_plans
            else []
        )
        sources = [
            {
                "task_id": str(task.id),
                "display_name": task.product.name,
                "strength": task.product.strength,
                "conflicting": bool(task.conflicts),
            }
            for task in affected_sources
        ]
        target_ref = ref or BusinessRef(
            kind="regimen" if kind == "draft" else "enrollment_task", id=target, version=version
        )
        return Preparation(
            workflow_state="awaiting_confirmation" if ref else "ready_for_review",
            prompt_key="assistant.medication.review_delete",
            input_fields=inputs,
            view_fields={
                **inputs,
                "target_name": name,
                "records": records,
                "source_tasks": sources,
                "affected_plan_count": len(affected_plans),
                "affected_source_registration_count": len(affected_sources),
                "medication_record_removed": whole,
            },
            result_ref=ref,
            actions=(
                ExistingReviewAction(
                    component_key="existing_draft_delete", owned_ref=target_ref, expected_version=version
                ),
            )
            if ref
            else (),
        )

    def _owned_plan(self, owner: UUID, regimen_id: UUID, version: int | None = None):
        row = self._enrollment.get_regimen(owner, regimen_id)
        if row is None:
            raise NotFoundError("Medication plan not found")
        if version is not None and row.version_no != version:
            raise StaleVersionError("The medication plan version changed; refresh it before continuing")
        return row

    def _end(self, context: WorkflowContext, values: MedicationPlanEndFields, results: tuple[BusinessRef, ...]):
        if results:
            if len(results) != 1 or results[0].kind != "regimen":
                raise ValidationError("The stop action needs one owned plan")
            ref = results[0]
            row = self._owned_plan(context.owner, ref.id, ref.version)
        elif values.regimen_id is not None:
            row = self._owned_plan(context.owner, values.regimen_id, values.expected_version)
            ref = BusinessRef(kind="regimen", id=row.id, version=row.version_no)
        else:
            choices = []
            for medication in self._enrollment.list_medications(context.owner):
                for row in self._enrollment.list_regimens(context.owner, medication.id):
                    if row.state.value == "active":
                        choices.append(
                            ChoiceOption(
                                value=f"{row.id}:{row.version_no}",
                                label_key="assistant.medication.select_plan",
                                label_text=f"{medication.display_name} · v{row.version_no}",
                            )
                        )
            return Preparation(
                prompt_key="assistant.medication.choose_stop" if choices else "assistant.medication.no_active",
                input_fields=values.model_dump(mode="json", exclude_none=True),
                missing_fields=("regimen_id",) if choices else (),
                view_fields={} if choices else {"records": [], "source_tasks": []},
                actions=tuple(
                    ChoiceAction(action_id="medication.end_target", options=tuple(choices[i : i + 10]))
                    for i in range(0, len(choices), 10)
                ),
            )
        medication = self._enrollment.get_medication(context.owner, row.patient_medication_id)
        if medication is None:
            raise NotFoundError("Medication not found")
        state = (
            "completed" if row.state.value == "ended" else "awaiting_confirmation" if results else "ready_for_review"
        )
        if row.state.value not in {"active", "ended"}:
            raise ValidationError("Only an active recorded plan can be stopped")
        return Preparation(
            workflow_state=state,
            input_fields={"regimen_id": str(row.id), "expected_version": row.version_no},
            prompt_key="assistant.medication.ended" if state == "completed" else "assistant.medication.review_stop",
            view_fields={
                "regimen_id": str(row.id),
                "expected_version": row.version_no,
                "records": [
                    {
                        "medication_id": str(medication.id),
                        "display_name": medication.display_name,
                        "plans": [self._plan(row)],
                    }
                ],
            },
            result_ref=ref if results else None,
            actions=(
                ExistingReviewAction(component_key="existing_plan_end", owned_ref=ref, expected_version=row.version_no),
            )
            if state == "awaiting_confirmation"
            else (),
        )

    def reconcile(self, context: WorkflowContext, action_key: UUID) -> BusinessRef | None:
        if self._actions is None:
            return None
        try:
            receipt = self._actions.read(context.owner, action_key)
        except NotFoundError:
            return None
        if (receipt.task_id, receipt.capability_id, receipt.binding_revision) != (
            context.task_id,
            context.capability_id,
            context.revision,
        ):
            raise StaleVersionError("This preparation belongs to another task revision")
        return receipt.business_ref

    def prepare_once(
        self,
        context: WorkflowContext,
        values: MedicationPlanEndFields | MedicationDraftDeleteFields,
        assets: tuple[AttachmentRef, ...],
        action_key: UUID,
    ) -> BusinessRef:
        if (
            context.capability_id == "medication.draft.delete"
            and isinstance(values, MedicationDraftDeleteFields)
            and context.save_mode == "allowed"
            and not assets
            and self._actions is not None
        ):
            if self._clinical is None:
                raise ValidationError("Draft deletion version guard is unavailable")
            clinical_revision = self._clinical.revision(context.owner)
            prepared = self._delete(context, values, ())
            if prepared.workflow_state != "ready_for_review" or values.target_id is None:
                raise ValidationError("Choose the current draft before preparing deletion")
            ref = BusinessRef(
                kind="regimen" if values.kind == "draft" else "enrollment_task",
                id=values.target_id,
                version=prepared.input_fields["expected_version"],
            )
            receipt = self._actions.reserve(context, action_key)
            self._actions.complete(
                context, receipt.model_copy(update={"business_ref": ref, "clinical_revision": clinical_revision})
            )
            return ref
        if (
            context.capability_id != "medication.plan.end"
            or context.save_mode != "allowed"
            or assets
            or self._actions is None
        ):
            raise ValidationError("This patient action cannot be prepared")
        prepared = self._end(context, values, ())
        if prepared.workflow_state != "ready_for_review" or values.regimen_id is None:
            raise ValidationError("Choose the current active plan before preparing its review")
        row = self._owned_plan(context.owner, values.regimen_id, values.expected_version)
        ref = BusinessRef(kind="regimen", id=row.id, version=row.version_no)
        receipt = self._actions.reserve(context, action_key)
        self._actions.complete(context, receipt.model_copy(update={"business_ref": ref}))
        return ref

    def revise_inputs(self, context: WorkflowContext, result_ref: BusinessRef):
        if context.capability_id == "medication.draft.delete":
            kind = "draft" if result_ref.kind == "regimen" else "source"
            if self._deletion and self._deletion.receipt(context.owner, kind, result_ref.id):
                raise ValidationError("Finish pending photo cleanup before changing this deleted draft")
            version = (
                self._owned_plan(context.owner, result_ref.id).version_no
                if kind == "draft"
                else self._evidence.get(context.owner, result_ref.id).version
            )
            return {"kind": kind, "target_id": str(result_ref.id), "expected_version": version}
        row = self._owned_plan(context.owner, result_ref.id, result_ref.version)
        return {"regimen_id": str(row.id), "expected_version": row.version_no}

    @staticmethod
    def _plan(row):
        # The clinical DTO also contains patient identity and confirmation data.
        # Only this explicit patient-facing projection crosses the Agent boundary.
        return {
            "regimen_id": str(row.id),
            "version_no": row.version_no,
            "state": row.state.value,
            "source_id": str(row.source_id) if row.source_id else None,
            "supersedes_id": str(row.supersedes_id) if row.supersedes_id else None,
            "dose_amount": row.dose_amount,
            "dose_unit": row.dose_unit,
            "frequency_rule": row.frequency_rule,
            "is_prn": row.is_prn,
            "food_instruction": row.food_instruction,
            "course_start_date": row.course_start_date.isoformat() if row.course_start_date else None,
            "course_end_date": row.course_end_date.isoformat() if row.course_end_date else None,
        }

    def prepare(
        self,
        context: WorkflowContext,
        values: MedicationSetupFields | MedicationPlanEndFields | MedicationDraftDeleteFields,
        assets: tuple[AttachmentRef, ...],
        results: tuple[BusinessRef, ...] = (),
    ) -> Preparation:
        if (
            context.capability_id == "medication.draft.delete"
            and isinstance(values, MedicationDraftDeleteFields)
            and not assets
        ):
            return self._delete(context, values, results)
        if (
            context.capability_id == "medication.plan.end"
            and isinstance(values, MedicationPlanEndFields)
            and not assets
        ):
            return self._end(context, values, results)
        if context.capability_id not in self.capability_ids or assets or results:
            raise ValidationError("This medication read does not accept attachments or business results")
        medications = self._enrollment.list_medications(context.owner)
        selected = values.medication_id if isinstance(values, MedicationPlanFields) else None
        if selected is not None and not any(row.id == selected for row in medications):
            raise NotFoundError("Medication not found")
        source_tasks = []
        excluded_drafts = set()
        if context.capability_id == "medication.setup.list":
            pending = [
                row
                for row in self._evidence.list(context.owner)
                if row.status
                in {
                    "pending_information",
                    "conflict",
                    "ready_for_review",
                }
            ]
            excluded_drafts = {row.draft_regimen_id for row in pending if row.draft_regimen_id}
            source_tasks = [
                {
                    "task_id": str(row.id),
                    "display_name": row.product.name,
                    "strength": row.product.strength,
                    "status": row.status,
                    "conflicting": bool(row.conflicts),
                }
                for row in pending
            ]
        records = []
        for medication in medications:
            if selected is not None and medication.id != selected:
                continue
            plans = self._enrollment.list_regimens(context.owner, medication.id)
            if context.capability_id == "medication.setup.list":
                plans = [
                    row
                    for row in plans
                    if row.state.value in {"draft", "pending_clarification"} and row.id not in excluded_drafts
                ]
                if not plans:
                    continue
            records.append(
                {
                    "medication_id": str(medication.id),
                    "display_name": medication.display_name,
                    "plans": [self._plan(row) for row in plans],
                }
            )
        total = max(len(records), len(source_tasks))
        page_count = max(1, (total + 9) // 10)
        page = values.page if values.page < page_count else 0
        page_records = records[page * 10 : page * 10 + 10]
        actions = []
        if context.capability_id == "medication.plan.view" and selected is None and page_records:
            actions.append(
                ChoiceAction(
                    action_id="medication.target",
                    options=tuple(
                        ChoiceOption(
                            value=row["medication_id"],
                            label_key="assistant.medication.select",
                            label_text=row["display_name"],
                        )
                        for row in page_records
                    ),
                )
            )
        pages = tuple(
            ChoiceOption(value=f"page:{number}", label_key=label)
            for number, label in (
                (page - 1, "assistant.medication.previous"),
                (page + 1, "assistant.medication.next"),
            )
            if 0 <= number < page_count
        )
        if pages:
            actions.append(ChoiceAction(action_id="medication.page", options=pages))
        return Preparation(
            prompt_key="assistant.medication.page_changed"
            if page != values.page
            else "assistant.medication.choose"
            if context.capability_id == "medication.plan.view" and selected is None
            else "assistant.medication.read",
            input_fields={**values.model_dump(mode="json", exclude_none=True), "page": page},
            missing_fields=("medication_id",)
            if context.capability_id == "medication.plan.view" and selected is None
            else (),
            view_fields={
                **values.model_dump(mode="json", exclude_none=True),
                "page": page,
                "records": page_records,
                "source_tasks": source_tasks[page * 10 : page * 10 + 10],
                "page_count": page_count,
                "record_count": len(records),
                "source_task_count": len(source_tasks),
            },
            actions=tuple(actions),
        )

    def observe(self, context: WorkflowContext, result_ref: BusinessRef) -> OperationResult:
        if (
            context.capability_id == "medication.draft.delete"
            and result_ref.kind in {"regimen", "enrollment_task"}
            and self._deletion
        ):
            receipt = self._deletion.receipt(
                context.owner, "draft" if result_ref.kind == "regimen" else "source", result_ref.id
            )
            return OperationResult(
                state="outcome_unknown" if receipt is None else "pending" if receipt.cleanup_pending else "succeeded",
                business_ref=result_ref,
            )
        if context.capability_id == "medication.plan.end" and result_ref.kind == "regimen":
            row = self._owned_plan(context.owner, result_ref.id, result_ref.version)
            return OperationResult(
                state="succeeded" if row.state.value == "ended" else "pending", business_ref=result_ref
            )
        if result_ref.kind != "medication" or self._enrollment.get_medication(context.owner, result_ref.id) is None:
            raise NotFoundError("Medication not found")
        return OperationResult(state="succeeded", business_ref=result_ref)
