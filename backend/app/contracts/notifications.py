"""Worker interfaces are distinct from patient HTTP and Agent tools."""

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel

from .push import PushSubscriptionInput


class Delivery(BaseModel):
    id: UUID
    subscription_id: UUID
    subscription: PushSubscriptionInput
    attempts: int
    language: Literal["en", "zh"] = "en"
    purpose: Literal["reminder", "test"] = "reminder"


class DeliveryResult(BaseModel):
    status: Literal[
        "sent", "temporary", "expired_subscription", "provider_rejected", "invalid_subscription", "uncertain_delivery"
    ]
    retry_seconds: int = 60


class NotificationPort(Protocol):
    def send(self, delivery: Delivery) -> DeliveryResult: ...


class DeliveryRepository(Protocol):
    def claim(self, now: datetime) -> Delivery | None: ...
    def finish(self, delivery: Delivery, result: DeliveryResult, now: datetime) -> None: ...


class DispatchResult(BaseModel):
    """Counts describe work processed, never device receipt."""

    status: Literal["completed", "busy", "budget_exhausted"]
    profiles: int = 0
    processed: int = 0


class DispatchRunner(Protocol):
    def run(self) -> DispatchResult: ...
