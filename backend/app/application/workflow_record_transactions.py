"""Patient-only report summaries/confirmation over fixed native transaction DTOs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING
from uuid import UUID, uuid5

from ..contracts.assistant_workflows import (
    BusinessRef,
    CapabilityAdapter,
    Preparation,
    WorkflowContext,
    WorkflowRepository,
    WorkflowTask,
    validate_workflow_values,
)
from ..contracts.dto import DoseEventDTO, DoseEventInput, SelfReportResultDTO
from ..contracts.late_reports import LateReportInput
from ..contracts.workflow_coordination import BusinessReceiptReader
from ..contracts.workflow_persistence import BusinessWriteReceipt, WorkflowWriteBinding
from ..contracts.workflow_record_writes import (
    CorrectionWrite,
    DoseReportWrite,
    LateReportWrite,
    PrepareDoseReport,
    PrepareLateReport,
    PrepareRecordReview,
    PrnReportWrite,
    RecordWorkflowWritePort,
)
from ..domain.errors import NotFoundError, ProviderUnavailableError, StaleVersionError, ValidationError
from .preferences import PreferenceService

if TYPE_CHECKING:
    from ..agent.orchestrator import AgentOrchestrator
    from .dosing import SelfReportService
    from .late_reports import LateReportService


class RecordWorkflowTransactions:
    capability_ids = frozenset({"dose.report", "dose.prn.report", "dose.late.review", "dose.correction.review"})

    def __init__(
        self,
        *,
        writes: RecordWorkflowWritePort,
        tasks: WorkflowRepository,
        receipts: BusinessReceiptReader,
        adapters: Mapping[str, CapabilityAdapter],
        preferences: PreferenceService,
        reports: SelfReportService,
        late_reports: LateReportService,
        orchestrator: AgentOrchestrator,
    ):
        self._writes, self._tasks, self._receipts, self._adapters = writes, tasks, receipts, dict(adapters)
        self._preferences, self._reports, self._late, self._orchestrator = (
            preferences,
            reports,
            late_reports,
            orchestrator,
        )

    def _context(self, task):
        prefs = self._preferences.get(task.owner)
        return WorkflowContext(
            owner=task.owner,
            task_id=task.id,
            revision=task.revision,
            capability_id=task.capability_id,
            language=prefs.preferred_language,
            timezone=prefs.timezone,
            save_mode=task.save_mode,
        )

    def prepare(
        self, task: WorkflowTask, expected_revision: int, action_key: UUID, run_binding=None
    ) -> BusinessWriteReceipt:
        prior = self._writes.lookup(task.owner, action_key)
        if prior is not None:
            if (
                prior.task_id != task.id
                or prior.capability_id != task.capability_id
                or prior.binding_revision != expected_revision + 1
                or self._writes.review(task.owner, task.id, prior.binding_revision) != prior
            ):
                raise StaleVersionError("Report review belongs to another scope")
            return prior
        if (
            task.capability_id not in self.capability_ids
            or task.revision != expected_revision
            or task.save_mode != "allowed"
        ):
            raise StaleVersionError("Use the current saved report selection")
        values = validate_workflow_values(task.capability_id, task.fields)
        ready = self._adapters[task.capability_id].prepare(self._context(task), values, ())
        if ready.workflow_state != "ready_for_review":
            raise ValidationError("Choose the existing report target first")
        ref = (
            BusinessRef(kind="regimen", id=values.regimen_id, version=values.expected_version)
            if hasattr(values, "regimen_id")
            else BusinessRef(kind="dose_occurrence", id=values.occurrence_id, version=values.expected_version)
        )
        b = WorkflowWriteBinding(
            task_id=task.id,
            task_revision=task.revision,
            capability_id=task.capability_id,
            action_key=action_key,
            prepared_ref=ref,
            expected_domain_revision=self._writes.revision(task.owner),
            run_binding=run_binding,
        )
        actual = self._writes.prepare(task.owner, PrepareRecordReview(binding=b)).receipt
        if (
            actual.owner != task.owner
            or actual.task_id != task.id
            or actual.action_key != action_key
            or actual.capability_id != task.capability_id
            or actual.binding_revision != expected_revision + 1
            or actual.business_ref != ref
            or actual.outcome != "prepared"
        ):
            raise StaleVersionError("Actual report-selection receipt differs from this task")
        return actual

    def _review(self, owner, task_id, revision, capability):
        task = self._tasks.get(owner, task_id)
        if task.capability_id != capability or task.save_mode != "allowed" or task.state == "suspended":
            raise StaleVersionError("Use the current independent patient report review")
        review = self._writes.review(owner, task_id, revision)
        if review.capability_id != task.capability_id:
            raise StaleVersionError("Report review belongs to another capability")
        if task.state != "completed" and (
            task.revision != revision
            or task.state != "awaiting_confirmation"
            or task.business_refs != (review.business_ref,)
        ):
            raise StaleVersionError("Current report target changed")
        return task, review

    @staticmethod
    def _binding(review: BusinessWriteReceipt, action_key: UUID) -> WorkflowWriteBinding:
        return WorkflowWriteBinding(
            task_id=review.task_id,
            task_revision=review.binding_revision,
            capability_id=review.capability_id,
            action_key=action_key,
            prepared_ref=review.business_ref,
            expected_domain_revision=review.domain_revision,
        )

    def _session(self, owner, challenge, session_id=None):
        if challenge is not None:
            if session_id is not None and session_id != challenge.session_id:
                raise StaleVersionError("Report summary belongs to a different patient session")
            session = self._orchestrator.get_session(patient_id=owner, session_id=challenge.session_id)
            if session is None:
                raise StaleVersionError("Original report-confirmation session unavailable")
            return session
        session = self._orchestrator.get_session(patient_id=owner, session_id=session_id) if session_id else None
        if session is None:
            session = self._orchestrator.start_session(patient_id=owner)
        return self._orchestrator.await_confirmation(patient_id=owner, session_id=session.id)

    def dose(
        self,
        owner,
        task_id,
        revision,
        operation_key,
        values: DoseEventInput,
        confirm,
        challenge_id=None,
        session_id=None,
    ):
        capability = "dose.prn.report" if values.occurrence_id is None else "dose.report"
        task, review = self._review(owner, task_id, revision, capability)
        if review.business_ref.kind != "regimen" or review.business_ref.id != values.regimen_id:
            raise StaleVersionError("Patient report differs from the selected owned plan")
        if values.idempotency_key != "report-" + str(operation_key):
            raise ValidationError("Use the canonical patient operation key")
        if confirm:
            cls = PrnReportWrite if capability == "dose.prn.report" else DoseReportWrite
            prior_receipt = self._writes.lookup(owner, operation_key)
            native = self._writes.apply(
                owner,
                cls(
                    binding=self._binding(review, operation_key),
                    values=values,
                    challenge_id=challenge_id,
                    confirmed=True,
                ),
            ).result
            if isinstance(native, DoseEventDTO):
                return SelfReportResultDTO(
                    event=native, existing_event_id=native.id, already_recorded=prior_receipt is not None
                )
            return native
        if task.state == "completed":
            raise StaleVersionError("This report is already recorded; inspect its actual result")
        prior = self._reports.find_confirmation(patient_id=owner, idempotency_key=values.idempotency_key)
        session = self._session(owner, prior, session_id)
        command = PrepareDoseReport(
            binding=self._binding(review, uuid5(operation_key, f"record-summary:{task_id}:{revision}")),
            session_id=session.id,
            session_state_version=session.state_version,
            operation_key=operation_key,
            intake_status=values.intake_status.value,
            occurrence_id=values.occurrence_id,
        )
        return self._writes.prepare(owner, command).result

    def late(
        self,
        owner: UUID,
        task_id: UUID,
        revision: int,
        occurrence_id: UUID,
        values: LateReportInput,
        challenge_id: UUID | None,
    ):
        capability = "dose.correction.review" if values.expected_report_id is not None else "dose.late.review"
        task, review = self._review(owner, task_id, revision, capability)
        if review.business_ref.kind != "dose_occurrence" or review.business_ref.id != occurrence_id:
            raise StaleVersionError("Patient historical report differs from the selected occurrence")
        if challenge_id is not None:
            cls = CorrectionWrite if capability == "dose.correction.review" else LateReportWrite
            return self._writes.apply(
                owner,
                cls(
                    binding=self._binding(review, values.id),
                    values=values,
                    occurrence_id=occurrence_id,
                    challenge_id=challenge_id,
                    confirmed=True,
                ),
            ).result
        if task.state == "completed":
            raise StaleVersionError("This historical report is already recorded")
        self._late.validate(owner, occurrence_id, values)
        prior = self._late.find_confirmation(owner, values.binding_key(occurrence_id))
        session = self._session(owner, prior)
        return self._writes.prepare(
            owner,
            PrepareLateReport(
                binding=self._binding(review, uuid5(values.id, f"record-summary:{task_id}:{revision}")),
                session_id=session.id,
                session_state_version=session.state_version,
                values=values,
            ),
        ).result

    def project(self, task):
        if task.state != "completed":
            return None
        rows = [
            r
            for r in self._receipts.task_receipts(task.owner, task.id)
            if r.outcome == "applied"
            and r.capability_id == task.capability_id
            and task.business_refs == (r.business_ref,)
            and r.binding_revision <= task.revision
        ]
        if len(rows) != 1:
            raise StaleVersionError("Completed report has no actual native receipt")
        receipt = rows[0]
        historical = task.capability_id in {"dose.late.review", "dose.correction.review"}
        try:
            actual = self._writes.read_result(task.owner, receipt)
            if actual.receipt != receipt:
                raise StaleVersionError("Actual report belongs to another receipt")
            native = actual.result
            event = native.event if isinstance(native, SelfReportResultDTO) else native
            if event is None:
                raise StaleVersionError("Actual report is unavailable")
            visible = {
                "intake_status": event.intake_status if historical else event.intake_status.value,
                "ingestion_proven": False,
                "event_time": (event.recorded_at if historical else event.event_time).isoformat(),
            }
            if historical:
                visible["report_version"] = event.version
        except (StaleVersionError, NotFoundError, ProviderUnavailableError):
            visible = {"actual_result_available": False, "historical_result": True}
        return Preparation(
            input_fields=task.fields,
            result_ref=receipt.business_ref,
            workflow_state="completed",
            prompt_key="assistant.late.completed" if historical else "assistant.report.completed",
            view_fields=visible,
        )
