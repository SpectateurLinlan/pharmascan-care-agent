"""Original patient APIs with optional current workflow authority and typed input."""

from collections.abc import Callable
from uuid import UUID

from pydantic import BaseModel

from ..contracts.assistant_workflows import WorkflowContext, validate_workflow_values
from ..domain.errors import StaleVersionError, ValidationError
from .assistant_capabilities.care import CareAdapter
from .assistant_workflows import WorkflowService
from .preferences import PreferenceService
from .workflow_care_transactions import CareWorkflowTransactions


class WorkflowCareService:
    def __init__(self, *, workflows: WorkflowService, adapter: CareAdapter, preferences: PreferenceService,
                 transactions: CareWorkflowTransactions | None = None):
        self.workflows, self.adapter, self.preferences = workflows, adapter, preferences
        self.transactions = transactions

    def run(
        self,
        owner: UUID,
        task_id: UUID,
        revision: int,
        allowed: set[str],
        target: UUID | None,
        payload: BaseModel | None,
        write: Callable[[], object],
    ) -> object:
        if self.transactions is not None:
            return self.transactions.apply_native(owner,task_id,revision,allowed,target,payload)
        view = self.workflows.view(owner, task_id)
        if view.capability_id not in allowed or view.capability_id not in self.adapter.write_ids:
            raise ValidationError("This patient endpoint does not match the current care task")
        ref = view.result_ref
        if ref is None or ref.kind != "care_review":
            raise StaleVersionError("Reopen the current independent patient care review")
        values = validate_workflow_values(view.capability_id, view.input_fields or {})
        preferences = self.preferences.get(owner)
        context = WorkflowContext(
            owner=owner,
            task_id=task_id,
            revision=revision,
            capability_id=view.capability_id,
            language=preferences.preferred_language,
            timezone=preferences.timezone,
        )
        return self.workflows.guarded_patient_action(
            owner,
            task_id,
            revision,
            capability_id=view.capability_id,
            target_id=ref.id,
            target_kind="care_review",
            write=lambda: self.adapter.run_bound_request(
                context, values, ref, view.capability_id, target, payload, write
            ),
        )

    def run_unbound(self, owner, write):
        if self.transactions is not None:
            # The unbound native API owns its SQL validation and transaction.
            return write()
        return self.adapter.clinical.run(owner, self.adapter.clinical.revision(owner), write)
