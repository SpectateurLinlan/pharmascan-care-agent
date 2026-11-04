"""Optional patient HTTP binding; neither this service nor tokens enter model tools."""

import re
from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

from ..contracts.assistant_workflows import WorkflowContext
from ..contracts.dto import DoseEventInput
from ..domain.errors import StaleVersionError, ValidationError
from .assistant_capabilities.reports import PatientReportAdapter
from .assistant_workflows import WorkflowService
from .workflow_record_transactions import RecordWorkflowTransactions

T = TypeVar("T")


class WorkflowDoseReportService:
    def __init__(
        self,
        *,
        workflows: WorkflowService,
        adapter: PatientReportAdapter,
        transactions: RecordWorkflowTransactions | None = None,
    ):
        self._workflows, self._adapter = workflows, adapter
        self.transactions = transactions

    def run(
        self,
        owner: UUID,
        task_id: UUID,
        revision: int,
        regimen_id: UUID,
        occurrence_id: UUID | None,
        key: str,
        confirm: bool,
        write: Callable[[], T],
        *,
        values: DoseEventInput | None = None,
        challenge_id: UUID | None = None,
        session_id: UUID | None = None,
    ) -> T:
        match = re.fullmatch(r"report-([0-9a-fA-F-]{36})", key)
        if match is None:
            raise ValidationError("Use the original patient report request key")
        try:
            operation_key = UUID(match[1])
        except ValueError:
            raise ValidationError("Invalid patient report request key") from None
        if key != "report-" + str(operation_key):
            raise ValidationError("Use the original canonical patient report request key")
        if self.transactions is not None:
            if values is None or values.regimen_id != regimen_id or values.occurrence_id != occurrence_id:
                raise ValidationError("Typed report needs its current validated native request")
            return self.transactions.dose(
                owner, task_id, revision, operation_key, values, confirm, challenge_id, session_id
            )
        view = self._workflows.view(owner, task_id)
        capability = "dose.prn.report" if occurrence_id is None else "dose.report"
        if view.capability_id != capability:
            raise ValidationError("This task cannot report this dose kind")
        context = WorkflowContext(owner=owner, task_id=task_id, capability_id=capability, revision=revision)

        def patient_write():
            ref = next(
                (
                    row
                    for row in view.actions
                    if row.kind == "existing_review" and row.component_key == "existing_self_report"
                ),
                None,
            )
            if ref is None:
                raise StaleVersionError("Reopen the current patient report review")
            target = ref.owned_ref
            return self._adapter.run_bound_request(context, target, occurrence_id, key, operation_key, confirm, write)

        return self._workflows.guarded_patient_action(
            owner,
            task_id,
            revision,
            capability_id=capability,
            target_id=regimen_id,
            target_kind="regimen",
            write=patient_write,
        )
