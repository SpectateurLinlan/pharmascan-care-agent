"""Optional Assistant binding for the existing independently confirmed patient APIs."""

from collections.abc import Callable
from uuid import UUID

from pydantic import JsonValue

from ..contracts.assistant_workflows import WorkflowContext, validate_workflow_values
from ..domain.errors import StaleVersionError, ValidationError
from .assistant_capabilities.media_mutations import MediaMutationAdapter
from .assistant_workflows import WorkflowService
from .preferences import PreferenceService
from .workflow_media_transactions import MediaWorkflowTransactions


class WorkflowMediaService:
    def __init__(self, *, workflows: WorkflowService, adapter: MediaMutationAdapter, preferences: PreferenceService,
                 transactions: MediaWorkflowTransactions | None = None):
        self.workflows, self.adapter, self.preferences = workflows, adapter, preferences
        self.transactions = transactions

    def run(self, owner: UUID, task_id: UUID, revision: int, allowed: set[str], target: UUID,
            payload: dict[str, JsonValue], confirmed: bool, write: Callable[[], object]) -> object:
        if self.transactions is not None:
            return self.transactions.apply_native(owner, task_id, revision, allowed, target, payload, confirmed)
        view = self.workflows.view(owner, task_id)
        if view.capability_id not in allowed or view.capability_id not in self.adapter.write_ids:
            raise ValidationError("The patient endpoint does not match this media workflow")
        ref = view.result_ref
        if ref is None or ref.kind != "media_review":
            raise StaleVersionError("Reopen the current independent media review")
        fields = validate_workflow_values(view.capability_id, view.input_fields or {})
        prefs = self.preferences.get(owner)
        context = WorkflowContext(owner=owner, task_id=task_id, revision=revision, capability_id=view.capability_id,
                                  language=prefs.preferred_language, timezone=prefs.timezone, save_mode=view.save_mode)
        return self.workflows.guarded_patient_action(
            owner, task_id, revision, capability_id=view.capability_id, target_id=ref.id, target_kind="media_review",
            write=lambda: self.adapter.run_bound_request(context, fields, ref, target, payload, confirmed, write),
        )

    def run_unbound(self, owner, write):
        return self.adapter.clinical.run(owner, self.adapter.clinical.revision(owner), write)
