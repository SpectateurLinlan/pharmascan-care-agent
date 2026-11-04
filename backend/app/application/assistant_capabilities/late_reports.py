"""Existing historical patient review only; never an Agent report writer."""

from collections.abc import Callable, Iterator
from typing import TypeVar
from uuid import UUID
from zoneinfo import ZoneInfo

from ...contracts.assistant_workflows import (
    ActionReceipt,
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
from ...contracts.late_report_workflow import LATE_REVIEW_SCHEMAS, LateReviewFields
from ...contracts.late_reports import DoseFollowUp, LateReportInput, LateReportRecord
from ...contracts.medication_management import ClinicalMutationGuard
from ...domain.errors import NotFoundError, StaleVersionError, ValidationError
from ..late_reports import LateReportService

T = TypeVar("T")


class PatientLateReportAdapter:
    capability_ids = frozenset(LATE_REVIEW_SCHEMAS)

    def __init__(self, *, reports: LateReportService, actions: ActionRepository, clinical: ClinicalMutationGuard):
        self.reports, self.actions, self.clinical = reports, actions, clinical

    def _target(self, context: WorkflowContext, ref: BusinessRef) -> DoseFollowUp:
        if ref.kind != "dose_occurrence":
            raise ValidationError("Choose an existing scheduled occurrence")
        item = self.reports.occurrence(context.owner, ref.id)
        audit = self.reports.audit(context.owner, ref.id)
        if len(audit.corrections) + 1 != ref.version or bool(item.report_id) != (
            context.capability_id == "dose.correction.review"
        ):
            raise StaleVersionError("This report changed; select its current history before correcting it")
        return item

    @staticmethod
    def _binding(
        context: WorkflowContext, receipt: ActionReceipt, target: BusinessRef, *, current: bool = True
    ) -> None:
        if (
            receipt.owner != context.owner
            or receipt.task_id != context.task_id
            or receipt.capability_id != context.capability_id
            or receipt.business_ref != target
            or (
                receipt.binding_revision != context.revision if current else receipt.binding_revision > context.revision
            )
        ):
            raise StaleVersionError("This confirmation belongs to another historical review")

    def _results(self, context: WorkflowContext, ref: BusinessRef) -> Iterator[LateReportRecord]:
        for operation in self.actions.list(context.owner, context.task_id):
            target = operation.business_ref
            if (
                operation.safe_reason != "late_report_operation"
                or target is None
                or operation.binding_revision > context.revision
                or target.kind != "dose_occurrence"
            ):
                continue
            if ref.kind == "dose_occurrence" and target != ref:
                continue
            audit = self.reports.audit(context.owner, target.id)
            report = next((row for row in audit.corrections if row.id == operation.action_key), None)
            if report is None or (ref.kind == "late_report" and ref.id != report.id):
                continue
            challenge = self.reports.find_confirmation(context.owner, report.idempotency_key)
            if (
                challenge is None
                or challenge.confirmed_at is None
                or challenge.consumed_at is None
                or challenge.occurrence_id != target.id
                or challenge.regimen_id != report.regimen_id
                or challenge.intended_intake_status.value != report.intake_status
                or report.version != target.version
            ):
                continue
            try:
                self._binding(context, self.actions.read(context.owner, challenge.id), target, current=False)
            except (NotFoundError, StaleVersionError):
                continue
            yield report

    def prepare(
        self,
        context: WorkflowContext,
        values: LateReviewFields,
        assets: tuple[AttachmentRef, ...],
        results: tuple[BusinessRef, ...] = (),
    ) -> Preparation:
        if assets or context.capability_id not in self.capability_ids:
            raise ValidationError("This historical review accepts only an existing occurrence")
        inputs = values.model_dump(mode="json", exclude_none=True)
        if results:
            if len(results) != 1:
                raise ValidationError("Choose one historical report")
            ref = results[0]
            actual = next(self._results(context, ref), None)
            if actual:
                return Preparation(
                    input_fields=inputs,
                    workflow_state="completed",
                    result_ref=ref,
                    prompt_key="assistant.late.completed",
                    view_fields={
                        "intake_status": actual.intake_status,
                        "event_time": actual.recorded_at.isoformat(),
                        "ingestion_proven": False,
                        "report_version": actual.version,
                    },
                )
            if ref.kind != "dose_occurrence":
                raise NotFoundError("The actual historical report is unavailable")
            try:
                item = self._target(context, ref)
            except (ValidationError, StaleVersionError):
                return Preparation(
                    input_fields=inputs,
                    workflow_state="failed_recoverable",
                    result_ref=ref,
                    prompt_key="assistant.late.changed",
                )
            return Preparation(
                input_fields=inputs,
                workflow_state="awaiting_confirmation",
                result_ref=ref,
                prompt_key="assistant.late.patient_review",
                view_fields={"late_target": item.model_dump(mode="json"), "timezone": context.timezone},
                actions=(
                    ExistingReviewAction(
                        component_key="existing_late_report", owned_ref=ref, expected_version=ref.version
                    ),
                ),
            )
        if values.occurrence_id is None:
            data = self.reports.recent(context.owner, include_reported=True, materialize_current=False)
            items = [
                row
                for row in data["items"]
                if row.can_report and bool(row.report_id) == (context.capability_id == "dose.correction.review")
            ]
            pages = max(1, (len(items) + 9) // 10)
            page = values.page if values.page < pages else 0
            choices = []
            for row in items[page * 10 : page * 10 + 10]:
                generation = len(self.reports.audit(context.owner, row.occurrence_id).corrections) + 1
                local_due = row.due_at.astimezone(ZoneInfo(context.timezone)).strftime("%Y-%m-%d %H:%M")
                choices.append(
                    ChoiceOption(
                        value=f"{row.occurrence_id}:{generation}:{row.report_id or 'none'}",
                        label_key="assistant.late.select",
                        label_text=f"{row.medication_name} · {local_due}"[:200],
                    )
                )
            nav = tuple(
                ChoiceOption(value=f"page:{number}", label_key=key)
                for number, key in (
                    (page - 1, "assistant.medication.previous"),
                    (page + 1, "assistant.medication.next"),
                )
                if 0 <= number < pages
            )
            return Preparation(
                input_fields={**inputs, "page": page},
                missing_fields=("occurrence_id",),
                prompt_key="assistant.late.choose" if items else "assistant.late.empty",
                view_fields={"coverage_limit": 50, "has_more": data["has_more"], "timezone": data["timezone"]},
                actions=(
                    *((ChoiceAction(action_id="late.target", options=tuple(choices)),) if choices else ()),
                    *((ChoiceAction(action_id="late.page", options=nav),) if nav else ()),
                ),
            )
        ref = BusinessRef(kind="dose_occurrence", id=values.occurrence_id, version=values.expected_version)
        item = self._target(context, ref)
        if item.report_id != values.expected_report_id:
            raise StaleVersionError("This report changed; select its current record")
        return Preparation(
            input_fields=inputs,
            workflow_state="ready_for_review",
            prompt_key="assistant.late.ready",
            view_fields={"late_target": item.model_dump(mode="json"), "timezone": context.timezone},
        )

    def prepare_once(
        self, context: WorkflowContext, values: LateReviewFields, assets: tuple[AttachmentRef, ...], action_key: UUID
    ) -> BusinessRef:
        if context.save_mode != "allowed" or assets or values.occurrence_id is None:
            raise ValidationError("Enable saving and choose an existing occurrence")
        ref = BusinessRef(kind="dose_occurrence", id=values.occurrence_id, version=values.expected_version)
        item = self._target(context, ref)
        if item.report_id != values.expected_report_id:
            raise StaleVersionError("This report changed")
        receipt = self.actions.reserve(context, action_key)
        self.actions.complete(context, receipt.model_copy(update={"business_ref": ref}))
        return ref

    def reconcile(self, context, action_key):
        try:
            receipt = self.actions.read(context.owner, action_key)
        except NotFoundError:
            return None
        if receipt.business_ref is not None:
            self._binding(context, receipt, receipt.business_ref)
        return receipt.business_ref

    def revise_inputs(self, context, result_ref):
        raise ValidationError("Choose a new historical review when its target changes")

    def read_patient_result(self, context, result_ref, values=None):
        actual = next(self._results(context, result_ref), None)
        return BusinessRef(kind="late_report", id=actual.id, version=actual.version) if actual else result_ref

    def observe(self, context, result_ref):
        return OperationResult(
            state="succeeded" if next(self._results(context, result_ref), None) else "pending", business_ref=result_ref
        )

    def run_patient_action(self, context: WorkflowContext, result_ref: BusinessRef, write: Callable[[], T]) -> T:
        def checked():
            if next(self._results(context, result_ref), None) is None:
                self._target(context, result_ref)
            return write()

        return self.clinical.run(context.owner, self.clinical.revision(context.owner), checked)

    def run_bound_request(
        self,
        context: WorkflowContext,
        target: BusinessRef,
        values: LateReportInput,
        challenge_id: UUID | None,
        write: Callable[[], T],
    ) -> T:
        prior = self.reports.find_confirmation(context.owner, values.binding_key(target.id))
        if prior:
            try:
                binding = self.actions.read(context.owner, prior.id)
            except NotFoundError:
                raise StaleVersionError("This confirmation predates the current patient review") from None
            self._binding(context, binding, target)
            if challenge_id is not None and challenge_id != prior.id:
                raise StaleVersionError("Confirm the original patient summary")
        elif challenge_id is not None:
            raise StaleVersionError("Request a matching patient summary first")
        actual = next(self._results(context, target), None)
        if actual is not None:
            if (
                actual.id != values.id
                or actual.idempotency_key != values.binding_key(target.id)
                or challenge_id is None
            ):
                raise StaleVersionError("This historical report was already saved; start a new correction")
        else:
            self._target(context, target)
        operation = self.actions.reserve(context, values.id)
        self.actions.complete(
            context, operation.model_copy(update={"business_ref": target, "safe_reason": "late_report_operation"})
        )
        result = write()
        if challenge_id is None:
            binding = self.actions.reserve(context, result.challenge_id)
            self.actions.complete(context, binding.model_copy(update={"business_ref": target}))
        return result
