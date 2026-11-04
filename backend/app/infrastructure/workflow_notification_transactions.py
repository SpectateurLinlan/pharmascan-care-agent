"""Fixed same-JWT subscription RPC. No sending or verifier authority."""

from ..contracts.push import PushSubscriptionRecord
from ..contracts.workflow_notification_transactions import NotificationTransition
from ..domain.errors import ProviderUnavailableError


class SupabaseNotificationTransitions:
    def __init__(self, data):
        self.data = data

    def execute(self, owner, command):
        self.data.check_patient(owner)
        command = NotificationTransition.model_validate(command.model_dump())
        raw = self.data.request(
            "POST",
            "/rest/v1/rpc/assistant_notification_transition",
            body={"p_command": command.model_dump(mode="json")},
        )
        try:
            if not isinstance(raw, dict) or set(raw) != {"subscription"}:
                raise ValueError
            if command.capability_id == "notification.unsubscribe":
                if raw["subscription"] is not None:
                    raise ValueError
                return None
            result = PushSubscriptionRecord.model_validate(raw["subscription"])
            if not result.enabled:
                raise ValueError
            return result
        except (ValueError, TypeError):
            raise ProviderUnavailableError("Native subscription result binding unavailable") from None
