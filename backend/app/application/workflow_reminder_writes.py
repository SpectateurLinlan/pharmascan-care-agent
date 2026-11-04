"""Optional task binding around the original patient reminder APIs."""

from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

from pydantic import BaseModel

from ..contracts.assistant_workflows import WorkflowContext, validate_workflow_values
from ..domain.errors import StaleVersionError, ValidationError
from .assistant_capabilities.reminder_mutations import ReminderMutationAdapter
from .assistant_workflows import WorkflowService
from .preferences import PreferenceService
from .workflow_reminder_transactions import ReminderWorkflowTransactions

T = TypeVar("T")


class WorkflowReminderWriteService:
    def __init__(self, *, workflows: WorkflowService, adapter: ReminderMutationAdapter,
                 preferences: PreferenceService, transactions: ReminderWorkflowTransactions | None = None):
        self.workflows, self.adapter, self.preferences = workflows, adapter, preferences
        self.transactions = transactions

    def run(self, owner: UUID, task_id: UUID, revision: int, capability: str, payload: BaseModel,
            confirmed: bool, write: Callable[[], object]) -> object:
        if self.transactions is not None:
            return self.transactions.apply_native(owner, task_id, revision, capability, payload, confirmed)
        view = self.workflows.view(owner, task_id)
        if view.capability_id != capability or capability not in self.adapter.capability_ids:
            raise ValidationError("This patient API does not match the reminder task")
        ref = view.result_ref
        if ref is None or ref.kind != "reminder_review":
            raise StaleVersionError("Reopen the current independent reminder review")
        preference = self.preferences.get(owner)
        context = WorkflowContext(owner=owner, task_id=task_id, revision=revision, capability_id=capability,
                                  language=preference.preferred_language, timezone=preference.timezone)
        values = validate_workflow_values(capability, view.input_fields or {})
        return self.workflows.guarded_patient_action(owner, task_id, revision, capability_id=capability,
            target_id=ref.id, target_kind="reminder_review",
            write=lambda: self.adapter.run_bound_request(context, values, ref, payload, confirmed, write))

    def run_unbound(self, owner: UUID, write: Callable[[], T]) -> T:
        return self.adapter.clinical.run(owner, self.adapter.clinical.revision(owner), write)
