"""Explicit owner-scoped diagnostic send; never consumes a clinical queue slot."""

from threading import Lock
from typing import Literal
from uuid import UUID

from ..contracts.notifications import Delivery, DeliveryResult, NotificationPort
from ..contracts.ports import Clock
from ..contracts.push import PushSubscriptions
from ..domain.errors import NotFoundError


class PushTestLimited(Exception):
    pass


class PushTestService:
    """A bounded per-process cooldown/replay cache, not a distributed rate-limit claim.

    Multiple API instances can each accept a diagnostic. Clinical dispatch retains
    database-wide idempotency; tests are explicit one-shot, never automatically retried.
    """

    def __init__(self, provider: NotificationPort, clock: Clock):
        self._provider, self._clock = provider, clock
        self._lock = Lock()
        self._recent: dict[UUID, tuple[float, UUID, UUID, DeliveryResult | None]] = {}

    def send(
        self,
        patient_id: UUID,
        subscription_id: UUID,
        request_id: UUID,
        subscriptions: PushSubscriptions,
        language: Literal["en", "zh"] = "en",
    ) -> DeliveryResult:
        subscription = subscriptions.credentials(patient_id, subscription_id)
        if subscription is None:
            raise NotFoundError("Enabled device subscription not found")
        now = self._clock.now().timestamp()
        with self._lock:
            self._recent = {owner: row for owner, row in self._recent.items() if now - row[0] < 60}
            previous = self._recent.get(patient_id)
            if previous:
                if previous[1:3] == (request_id, subscription_id) and previous[3] is not None:
                    return previous[3]
                raise PushTestLimited
            if len(self._recent) >= 1024:
                raise PushTestLimited
            self._recent[patient_id] = (now, request_id, subscription_id, None)
        result = self._provider.send(
            Delivery(
                id=request_id,
                subscription_id=subscription_id,
                subscription=subscription,
                attempts=1,
                language=language,
                purpose="test",
            )
        )
        if result.status == "expired_subscription":
            subscriptions.revoke(patient_id, subscription_id)
        with self._lock:
            self._recent[patient_id] = (now, request_id, subscription_id, result)
        return result
