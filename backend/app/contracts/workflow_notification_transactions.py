"""Patient browser credentials stay outside model/workflow fields and receipts."""

from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from .assistant_workflows import WorkflowDTO
from .push import PushSubscriptionInput, PushSubscriptionRecord


class NotificationTransition(WorkflowDTO):
    task_id: UUID
    revision: int = Field(strict=True, ge=1)
    capability_id: Literal["notification.subscribe", "notification.unsubscribe"]
    action_key: UUID
    confirmed: Literal[True]
    subscription: PushSubscriptionInput | None = Field(default=None, repr=False)
    subscription_id: UUID | None = None
    endpoint: str | None = Field(default=None, repr=False)

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("Independent confirmation required")
        return value

    @field_validator("endpoint")
    @classmethod
    def valid_endpoint(cls, value):
        return PushSubscriptionInput.valid_endpoint(value) if value is not None else value

    @model_validator(mode="after")
    def closed_action(self):
        if self.capability_id == "notification.subscribe":
            valid = self.subscription is not None and self.subscription_id is None and self.endpoint is None
        else:
            valid = self.subscription is None and ((self.subscription_id is None) != (self.endpoint is None))
        if not valid:
            raise ValueError("Choose exactly the current native subscription action")
        return self


class NotificationTransitionPort(Protocol):
    def execute(self, owner: UUID, command: NotificationTransition) -> PushSubscriptionRecord | None: ...
