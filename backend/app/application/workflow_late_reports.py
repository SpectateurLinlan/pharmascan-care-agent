"""Optional task binding around independent historical patient APIs."""

from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

from ..contracts.assistant_workflows import WorkflowContext
from ..contracts.late_reports import LateReportInput
from ..domain.errors import StaleVersionError, ValidationError
from .assistant_capabilities.late_reports import PatientLateReportAdapter
from .assistant_workflows import WorkflowService
from .workflow_record_transactions import RecordWorkflowTransactions

T = TypeVar("T")


class WorkflowLateReportService:
    def __init__(
        self,
        *,
        workflows: WorkflowService,
        adapter: PatientLateReportAdapter,
        transactions: RecordWorkflowTransactions | None = None,
    ):
        self.workflows, self.adapter = workflows, adapter
        self.transactions = transactions

    def run(
        self,
        owner: UUID,
        task_id: UUID,
        revision: int,
        occurrence_id: UUID,
        values: LateReportInput,
        challenge_id: UUID | None,
        write: Callable[[], T],
    ) -> T:
        if self.transactions is not None:
            return self.transactions.late(owner, task_id, revision, occurrence_id, values, challenge_id)
        view = self.workflows.view(owner, task_id)
        if view.capability_id not in self.adapter.capability_ids:
            raise ValidationError("This task cannot review a historical report")
        target = view.result_ref
        if target is None or target.kind != "dose_occurrence" or target.id != occurrence_id:
            raise StaleVersionError("Reopen the current historical patient review")
        context = WorkflowContext(owner=owner, task_id=task_id, capability_id=view.capability_id, revision=revision)
        return self.workflows.guarded_patient_action(
            owner,
            task_id,
            revision,
            capability_id=view.capability_id,
            target_id=occurrence_id,
            target_kind="dose_occurrence",
            write=lambda: self.adapter.run_bound_request(context, target, values, challenge_id, write),
        )
