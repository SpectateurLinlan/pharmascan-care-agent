"""Optional exact current-task binding for native profile/preference/contact writes."""

from collections.abc import Callable, Mapping
from uuid import UUID

from pydantic import BaseModel

from ..contracts.assistant_workflows import WorkflowContext, validate_workflow_values
from ..domain.errors import StaleVersionError, ValidationError
from .assistant_capabilities.settings_mutations import SettingsMutationAdapter
from .assistant_workflows import WorkflowService
from .preferences import PreferenceService
from .workflow_settings_transactions import SettingsWorkflowTransactions


class WorkflowSettingsService:
    def __init__(self, *, workflows: WorkflowService, adapters: Mapping[str, SettingsMutationAdapter],
                 preferences: PreferenceService, transactions: SettingsWorkflowTransactions | None = None):
        self.workflows, self.adapters, self.preferences = workflows, adapters, preferences
        self.transactions = transactions

    def run(self, owner: UUID, task_id: UUID, revision: int, capability: str, target: UUID | None,
            payload: BaseModel | None, confirmed: bool, write: Callable[[], object]) -> object:
        if self.transactions is not None:
            return self.transactions.apply_native(owner, task_id, revision, capability, target, payload, confirmed)
        view = self.workflows.view(owner, task_id)
        adapter = self.adapters.get(capability)
        if view.capability_id != capability or adapter is None or capability not in adapter.write_ids:
            raise ValidationError("The patient endpoint does not match this settings task")
        ref = view.result_ref
        if ref is None or ref.kind != "settings_review":
            raise StaleVersionError("Reopen the current independent settings review")
        preference = self.preferences.get(owner)
        context = WorkflowContext(owner=owner, task_id=task_id, revision=revision, capability_id=capability,
                                  language=preference.preferred_language, timezone=preference.timezone)
        values = validate_workflow_values(capability, view.input_fields or {})
        return self.workflows.guarded_patient_action(owner, task_id, revision, capability_id=capability,
            target_id=ref.id, target_kind="settings_review",
            write=lambda: adapter.run_bound_request(context, values, ref, target, payload, confirmed, write))

    def run_unbound(self, owner, write):
        adapter = next(iter(self.adapters.values()))
        return adapter.clinical.run(owner, adapter.clinical.revision(owner), write)
