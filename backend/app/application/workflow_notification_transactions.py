"""A confirmed browser request, never a model-supplied subscription credential."""

import hashlib
import json
from uuid import uuid5

from ..contracts.workflow_notification_transactions import NotificationTransition, NotificationTransitionPort
from ..domain.errors import ValidationError


class NotificationWorkflowTransactions:
    def __init__(self, *, port: NotificationTransitionPort):
        self.port = port

    def run(
        self, owner, task_id, revision, capability, confirmed, *, subscription=None, subscription_id=None, endpoint=None
    ):
        if confirmed is not True or capability not in {"notification.subscribe", "notification.unsubscribe"}:
            raise ValidationError("Confirm the current subscription action independently")
        digest = hashlib.sha256(
            json.dumps(
                {
                    "subscription": subscription.model_dump() if subscription else None,
                    "subscription_id": str(subscription_id) if subscription_id else None,
                    "endpoint": endpoint,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        command = NotificationTransition(
            task_id=task_id,
            revision=revision,
            capability_id=capability,
            confirmed=True,
            action_key=uuid5(task_id, f"native-subscription:{revision}:{capability}:{digest}"),
            subscription=subscription,
            subscription_id=subscription_id,
            endpoint=endpoint,
        )
        return self.port.execute(owner, command)
