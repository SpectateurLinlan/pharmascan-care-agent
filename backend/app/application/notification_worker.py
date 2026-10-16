"""Bounded delivery processing; never invokes Gemini or records intake."""

from collections.abc import Callable

from ..contracts.notifications import DeliveryRepository, NotificationPort
from ..contracts.ports import Clock


class NotificationWorker:
    def __init__(self, repository: DeliveryRepository, provider: NotificationPort, clock: Clock):
        self._repository, self._provider, self._clock = repository, provider, clock

    def deliver(self, limit: int = 50, *, may_continue: Callable[[], bool] = lambda: True) -> int:
        completed = 0
        for _ in range(min(max(limit, 0), 100)):
            if not may_continue():
                break
            delivery = self._repository.claim(self._clock.now())
            if delivery is None:
                break
            result = self._provider.send(delivery)
            self._repository.finish(delivery, result, self._clock.now())
            completed += 1
        return completed
