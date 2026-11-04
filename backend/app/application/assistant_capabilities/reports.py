"""Prepare only an owned patient UI; actual self-report APIs keep write authority."""

from collections.abc import Callable
from typing import TypeVar
from uuid import UUID
from zoneinfo import ZoneInfo

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
from ...contracts.dose_report_workflow import REPORT_SCHEMAS, DoseReportFields
from ...contracts.medication_management import ClinicalMutationGuard
from ...contracts.ports import Clock
from ...domain.errors import NotFoundError, StaleVersionError, ValidationError
from ..dosing import DoseScheduleService, SelfReportService
from ..enrollment import MedicationEnrollmentService

T = TypeVar("T")


class PatientReportAdapter:
    capability_ids = frozenset(REPORT_SCHEMAS)

    def __init__(
        self,
        *,
        enrollment: MedicationEnrollmentService,
        reports: SelfReportService,
        schedule: DoseScheduleService,
        actions: ActionRepository,
        clinical: ClinicalMutationGuard,
        clock: Clock,
    ):
        self.enrollment, self.reports, self.schedule = enrollment, reports, schedule
        self.actions, self.clinical, self.clock = actions, clinical, clock

    def _target(self, context: WorkflowContext, ref: BusinessRef):
        if ref.kind != "regimen":
            raise ValidationError("Choose a recorded plan for the patient report")
        plan = self.enrollment.get_regimen(context.owner, ref.id)
        if plan is None:
            raise NotFoundError("Report plan not found for this patient")
        med = self.enrollment.get_medication(context.owner, plan.patient_medication_id)
        day = self.clock.now().astimezone(ZoneInfo(context.timezone)).date()
        if (
            med is None
            or med.archived_at is not None
            or plan.version_no != ref.version
            or plan.state.value != "active"
            or plan.is_prn != (context.capability_id == "dose.prn.report")
            or plan.course_start_date
            and plan.course_start_date > day
            or plan.course_end_date
            and plan.course_end_date < day
            or plan.effective_from
            and plan.effective_from > self.clock.now()
            or plan.effective_to
            and plan.effective_to <= self.clock.now()
        ):
            raise StaleVersionError("The current reviewed plan changed; select its current report action")
        return plan, med

    @staticmethod
    def _binding(context, receipt, ref, *, current=True):
        if (
            receipt.task_id != context.task_id
            or receipt.capability_id != context.capability_id
            or receipt.owner != context.owner
            or receipt.business_ref != ref
            or (
                receipt.binding_revision != context.revision if current else receipt.binding_revision > context.revision
            )
        ):
            raise StaleVersionError("This report confirmation belongs to another task or review revision")

    def _events(self, context: WorkflowContext, ref: BusinessRef | None = None):
        for operation in self.actions.list(context.owner, context.task_id):
            if operation.safe_reason != "dose_report_operation" or operation.business_ref is None:
                continue
            if operation.binding_revision > context.revision:
                continue
            if ref is not None and ref.kind == "regimen" and operation.business_ref != ref:
                continue
            key = "report-" + str(operation.action_key)
            event = self.reports.find_existing_report(patient_id=context.owner, idempotency_key=key)
            challenge = self.reports.find_confirmation(patient_id=context.owner, idempotency_key=key)
            if event is None or challenge is None or challenge.confirmed_at is None or challenge.consumed_at is None:
                continue
            try:
                binding = self.actions.read(context.owner, challenge.id)
                self._binding(context, binding, operation.business_ref, current=False)
            except (NotFoundError, StaleVersionError):
                continue
            if (
                event.regimen_id != operation.business_ref.id
                or challenge.regimen_id != event.regimen_id
                or event.occurrence_id != challenge.occurrence_id
                or event.intake_status != challenge.intended_intake_status
            ):
                continue
            if ref is None or ref.kind != "dose_event" or ref.id == event.id:
                yield event

    def prepare(
        self,
        context: WorkflowContext,
        values: DoseReportFields,
        assets: tuple[AttachmentRef, ...],
        results: tuple[BusinessRef, ...] = (),
    ) -> Preparation:
        if assets or context.capability_id not in self.capability_ids:
            raise ValidationError("This report preparation does not accept photos or another capability")
        inputs = values.model_dump(mode="json", exclude_none=True)
        if results:
            if len(results) != 1:
                raise ValidationError("A report action has one owned result")
            ref = results[0]
            if ref.kind == "dose_event":
                event = next(self._events(context, ref), None)
                if event is None:
                    raise NotFoundError("The actual task-bound patient report is unavailable")
                plan = self.enrollment.get_regimen(context.owner, event.regimen_id)
                medicine = self.enrollment.get_medication(context.owner, plan.patient_medication_id) if plan else None
                return Preparation(
                    input_fields=inputs,
                    workflow_state="completed",
                    prompt_key="assistant.report.completed",
                    result_ref=ref,
                    view_fields={
                        "intake_status": event.intake_status.value,
                        "event_time": event.event_time.isoformat(),
                        "ingestion_proven": False,
                        "medication_name": medicine.display_name if medicine else None,
                    },
                )
            try:
                plan, med = self._target(context, ref)
            except StaleVersionError:
                return Preparation(
                    input_fields=inputs,
                    workflow_state="failed_recoverable",
                    result_ref=ref,
                    prompt_key="assistant.report.changed",
                )
            return Preparation(
                input_fields=inputs,
                workflow_state="awaiting_confirmation",
                result_ref=ref,
                prompt_key="assistant.report.patient_review",
                view_fields={
                    "report_target": {
                        "regimen_id": str(plan.id),
                        "version": plan.version_no,
                        "medication_name": med.display_name,
                        "dose_amount": plan.dose_amount,
                        "dose_unit": plan.dose_unit,
                        "is_prn": plan.is_prn,
                    }
                },
                actions=(
                    ExistingReviewAction(
                        component_key="existing_self_report", owned_ref=ref, expected_version=plan.version_no
                    ),
                ),
            )
        if values.regimen_id is None:
            choices = []
            for med in self.enrollment.list_medications(context.owner):
                for plan in self.enrollment.list_regimens(context.owner, med.id):
                    ref = BusinessRef(kind="regimen", id=plan.id, version=plan.version_no)
                    try:
                        self._target(context, ref)
                    except StaleVersionError:
                        continue
                    choices.append((med, plan))
            pages = max(1, (len(choices) + 9) // 10)
            page = values.page if values.page < pages else 0
            current = choices[page * 10 : page * 10 + 10]
            actions = (
                (
                    ChoiceAction(
                        action_id="report.target",
                        options=tuple(
                            ChoiceOption(
                                value=f"{plan.id}:{plan.version_no}",
                                label_key="assistant.medication.select_plan",
                                label_text=med.display_name[:200],
                            )
                            for med, plan in current
                        ),
                    ),
                )
                if current
                else ()
            )
            navigation = tuple(
                ChoiceOption(value=f"page:{number}", label_key=key)
                for number, key in (
                    (page - 1, "assistant.medication.previous"),
                    (page + 1, "assistant.medication.next"),
                )
                if 0 <= number < pages
            )
            return Preparation(
                input_fields={**inputs, "page": page},
                missing_fields=("regimen_id",),
                prompt_key="assistant.report.choose" if choices else "assistant.report.empty",
                actions=(
                    *actions,
                    *((ChoiceAction(action_id="report.page", options=navigation),) if navigation else ()),
                ),
            )
        plan, med = self._target(
            context, BusinessRef(kind="regimen", id=values.regimen_id, version=values.expected_version)
        )
        return Preparation(
            input_fields=inputs,
            workflow_state="ready_for_review",
            prompt_key="assistant.report.ready",
            view_fields={
                "medication_name": med.display_name,
                "dose_amount": plan.dose_amount,
                "dose_unit": plan.dose_unit,
                "is_prn": plan.is_prn,
            },
        )

    def prepare_once(self, context, values, assets, action_key):
        if context.save_mode != "allowed" or assets or values.regimen_id is None:
            raise ValidationError("Enable saving and select the recorded report target")
        ref = BusinessRef(kind="regimen", id=values.regimen_id, version=values.expected_version)
        self._target(context, ref)
        receipt = self.actions.reserve(context, action_key)
        self.actions.complete(context, receipt.model_copy(update={"business_ref": ref}))
        return ref

    def reconcile(self, context, action_key):
        try:
            receipt = self.actions.read(context.owner, action_key)
        except NotFoundError:
            return None
        if receipt.business_ref is None:
            return None
        self._binding(context, receipt, receipt.business_ref)
        return receipt.business_ref

    def revise_inputs(self, context, result_ref):
        raise ValidationError("Choose a fresh patient report task when its prepared target changes")

    def read_patient_result(self, context, result_ref, values=None):
        event = next(self._events(context, result_ref), None)
        return BusinessRef(kind="dose_event", id=event.id) if event else result_ref

    def observe(self, context, result_ref):
        event = next(self._events(context, result_ref), None)
        return OperationResult(state="succeeded" if event else "pending", business_ref=result_ref)

    def run_patient_action(self, context: WorkflowContext, result_ref: BusinessRef, write: Callable[[], T]) -> T:
        def checked():
            self._target(context, result_ref)
            return write()

        return self.clinical.run(context.owner, self.clinical.revision(context.owner), checked)

    def run_bound_request(
        self,
        context: WorkflowContext,
        target: BusinessRef,
        occurrence_id: UUID | None,
        key: str,
        operation_key: UUID,
        confirm: bool,
        write: Callable[[], T],
    ) -> T:
        owner = context.owner
        if occurrence_id is not None:
            occurrence = self.schedule.get_occurrence(owner, occurrence_id)
            if occurrence is None or occurrence.regimen_id != target.id:
                raise NotFoundError("Report occurrence not found for this plan")
        prior = self.reports.find_confirmation(patient_id=owner, idempotency_key=key)
        if prior is not None:
            try:
                binding = self.actions.read(owner, prior.id)
            except NotFoundError:
                raise StaleVersionError("This confirmation predates the current patient review") from None
            self._binding(context, binding, target)
        elif confirm:
            raise StaleVersionError("Request a current patient report summary first")
        operation = self.actions.reserve(context, operation_key)
        self.actions.complete(
            context, operation.model_copy(update={"business_ref": target, "safe_reason": "dose_report_operation"})
        )
        result = write()
        if not confirm:
            challenge_id = getattr(result, "challenge_id", None)
            if challenge_id is not None:
                binding = self.actions.reserve(context, challenge_id)
                self.actions.complete(context, binding.model_copy(update={"business_ref": target}))
        return result
