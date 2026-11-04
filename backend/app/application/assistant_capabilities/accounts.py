"""Auth secrets and identity changes belong only to the existing secure patient UI."""

from ...contracts.assistant_workflows import OperationResult, Preparation, SecureAccountAction
from ...contracts.settings_workflow import ACCOUNT_SCHEMAS
from ...domain.errors import ValidationError


class SecureAccountAdapter:
    capability_ids = frozenset(ACCOUNT_SCHEMAS)

    def prepare(self, context, values, assets, results=()):
        if assets or results or context.capability_id not in self.capability_ids:
            raise ValidationError("Use the secure account form without credentials in the workflow")
        return Preparation(input_fields={}, prompt_key="assistant.account.secure", actions=(
            SecureAccountAction(action=context.capability_id.split(".")[1]),))

    def observe(self, context, result_ref):
        return OperationResult(state="failed", reason="account_result_belongs_to_secure_form")
