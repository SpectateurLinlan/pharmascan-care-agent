"""Process-local control records sharing the explicitly injected P04 boundary."""

from contextlib import contextmanager

from ..contracts.agent_execution import RunRecord
from ..domain.errors import DuplicateEventError, NotFoundError
from .memory_workflows import MemoryWorkflowState


class MemoryRunRepository:
    def __init__(self, state: MemoryWorkflowState):
        self._state = state

    def create(self, owner, record: RunRecord) -> None:
        with self._state.lock:
            key = (owner, record.metadata.run_id)
            if key in self._state.runs:
                raise DuplicateEventError("Assistant run already exists; read its status")
            self._state.runs[key] = record

    @contextmanager
    def locked(self, owner, run_id):
        with self._state.lock:
            record = self._state.runs.get((owner, run_id))
            if record is None:
                raise NotFoundError("Assistant run not found")
            yield record
