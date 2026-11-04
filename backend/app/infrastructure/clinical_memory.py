"""Shared read/write lock for staged, atomically published memory aggregates."""

from collections.abc import Callable, Iterator, MutableMapping
from threading import RLock
from typing import Generic, TypeVar
from uuid import UUID

T = TypeVar("T")
Key = tuple[UUID, UUID]


class ClinicalMemory:
    def __init__(self):
        self.lock = RLock()
        self.revisions: dict[UUID, int] = {}


class MemoryClinicalMutationGuard:
    def __init__(self, coordination: ClinicalMemory):
        self._coordination = coordination

    def revision(self, owner: UUID) -> int:
        with self._coordination.lock:
            return self._coordination.revisions.get(owner, 0)

    def run(self, owner: UUID, revision: int, write: Callable[[], T]) -> T:
        from ..domain.errors import StaleVersionError

        with self._coordination.lock:
            if self._coordination.revisions.get(owner, 0) != revision:
                raise StaleVersionError("The records changed; review the draft deletion again")
            return write()


class ClinicalRows(MutableMapping[Key, T], Generic[T]):
    """Repository reads share the writer lock; iteration takes a stable snapshot."""

    def __init__(self, coordination: ClinicalMemory, *, track_revision: bool = True):
        self.coordination = coordination
        self.track_revision = track_revision
        self.rows: dict[Key, T] = {}

    def __getitem__(self, key: Key) -> T:
        with self.coordination.lock:
            return self.rows[key]

    def __setitem__(self, key: Key, value: T) -> None:
        with self.coordination.lock:
            self.rows[key] = value
            if self.track_revision:
                self.coordination.revisions[key[0]] = self.coordination.revisions.get(key[0], 0) + 1

    def __delitem__(self, key: Key) -> None:
        with self.coordination.lock:
            del self.rows[key]
            if self.track_revision:
                self.coordination.revisions[key[0]] = self.coordination.revisions.get(key[0], 0) + 1

    def __len__(self) -> int:
        with self.coordination.lock:
            return len(self.rows)

    def __iter__(self) -> Iterator[Key]:
        with self.coordination.lock:
            return iter(tuple(self.rows))

    def items(self):
        with self.coordination.lock:
            return tuple(self.rows.items())

    def values(self):
        with self.coordination.lock:
            return tuple(self.rows.values())
