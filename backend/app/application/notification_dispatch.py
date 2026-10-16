"""One bounded application pass shared by administrative CLI and HTTP worker."""

from collections.abc import Callable
from contextlib import AbstractContextManager

from ..contracts.notifications import DispatchResult
from .notification_worker import NotificationWorker


class NotificationDispatchService:
    def __init__(
        self,
        *,
        worker: NotificationWorker,
        project: Callable[[Callable[[], bool]], int],
        lease: Callable[[], AbstractContextManager[bool]],
        monotonic: Callable[[], float],
    ):
        self._worker, self._project, self._lease, self._monotonic = worker, project, lease, monotonic

    def run(self, *, limit: int = 5, budget_seconds: float = 20) -> DispatchResult:
        if not 1 <= limit <= 50 or not 1 <= budget_seconds <= 60:
            raise ValueError("Invalid dispatch bounds")
        deadline = self._monotonic() + budget_seconds

        def available() -> bool:
            return self._monotonic() < deadline

        with self._lease() as acquired:
            if not acquired:
                return DispatchResult(status="busy")
            profiles = self._project(available)
            processed = self._worker.deliver(limit, may_continue=available)
            return DispatchResult(
                status="completed" if available() else "budget_exhausted", profiles=profiles, processed=processed
            )
