"""Current saved task binding around native device APIs, not an Agent executor."""

from collections.abc import Callable
from typing import TypeVar
from uuid import UUID, uuid5

from ..contracts.assistant_workflows import ActionRepository
from ..contracts.push import PushConfiguration
from ..domain.errors import NotFoundError, ProviderUnavailableError, StaleVersionError, ValidationError
from .assistant_workflows import WorkflowService

T = TypeVar("T")


class WorkflowNotificationService:
    def __init__(
        self,
        *,
        workflows: WorkflowService,
        actions: ActionRepository,
        send_allowed: Callable[[], bool],
        transactions=None,
    ):
        self.workflows, self.actions, self.send_allowed = workflows, actions, send_allowed
        self.transactions = transactions

    def configuration(
        self, owner: UUID, task_id: UUID, revision: int, value: PushConfiguration, authenticated: bool
    ) -> PushConfiguration:
        view = self.workflows.view(owner, task_id)
        if self.transactions is not None:
            self.workflows.read_only_input(owner, task_id, revision, view.capability_id)
            return value.model_copy(update={"test_available": False})
        return self.workflows.guarded_device_action(
            owner,
            task_id,
            revision,
            view.capability_id,
            lambda context: value.model_copy(
                update={"test_available": value.test_available and self.send_allowed() and authenticated}
            ),
        )

    def run(
        self,
        owner: UUID,
        task_id: UUID,
        revision: int,
        capability: str,
        confirmed: bool,
        write: Callable[[], T],
        **native,
    ) -> T:
        if not confirmed:
            raise ValidationError("Confirm this device action separately on the patient page")
        if capability == "notification.test" and not self.send_allowed():
            raise ProviderUnavailableError("Sending a notification test has not been authorized")
        if self.transactions is not None:
            if capability == "notification.test":
                raise ProviderUnavailableError("Persistent notification sending requires separate device acceptance")
            return self.transactions.run(owner, task_id, revision, capability, confirmed, **native)

        def checked(context):
            receipt = None
            if capability == "notification.test":
                action_key = uuid5(task_id, "notification-test-once")
                try:
                    self.actions.read(owner, action_key)
                except NotFoundError:
                    receipt = self.actions.reserve(context, action_key)
                else:
                    raise StaleVersionError("A test was already attempted for this task; do not resend it")
                self.actions.complete(
                    context,
                    receipt.model_copy(
                        update={"state": "outcome_unknown", "safe_reason": "notification_test_attempted"}
                    ),
                )
            result = write()
            if receipt:
                self.actions.complete(
                    context,
                    receipt.model_copy(update={"state": "succeeded", "safe_reason": "notification_test_returned"}),
                )
            return result

        return self.workflows.guarded_device_action(owner, task_id, revision, capability, checked)
