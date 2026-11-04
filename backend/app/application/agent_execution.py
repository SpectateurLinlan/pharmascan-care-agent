"""Bounded orchestration and cooperative cancellation, with no clinical authority."""

from collections.abc import Callable
from contextlib import contextmanager
from time import monotonic as system_monotonic
from typing import TypeVar
from uuid import UUID

from ..contracts.agent_execution import (
    BudgetExceeded,
    DeadlineExceeded,
    ExecutionBudget,
    ExecutionStopped,
    ProviderUsage,
    RunEvent,
    RunMetadata,
    RunRecord,
    RunRepository,
    TaskCancelled,
    current_execution,
    execution_step,
)
from ..domain.errors import DuplicateEventError
from .agent_runtime_metadata import combine_usage, content_hash, model_name, runtime_hash, source_revision

T = TypeVar("T")
TERMINAL = {"completed", "cancelled", "failed"}


def event(record, kind, *, action_key=None, reason_key=None, duration_ms=None):
    record.events.append(
        RunEvent(
            sequence=len(record.events) + 1,
            run_id=record.metadata.run_id,
            kind=kind,
            status=record.status,
            action_key=action_key,
            reason_key=reason_key,
            duration_ms=duration_ms,
        )
    )


class ExecutionControl:
    def __init__(self, repo, owner, run_id, monotonic):
        self._repo, self._owner, self._run, self._now = repo, owner, run_id, monotonic
        self._spans: list[str] = []
        self._model_attempts = 0

    def _check(self, record):
        if record.status in {"cancelling", "cancelled"}:
            raise TaskCancelled()
        if self._now() >= record.budget.deadline_monotonic:
            raise DeadlineExceeded()

    def check(self):
        with self._repo.locked(self._owner, self._run) as record:
            self._check(record)

    def remaining(self, native_timeout):
        with self._repo.locked(self._owner, self._run) as record:
            self._check(record)
            return min(native_timeout, record.budget.deadline_monotonic - self._now())

    def guarded(self, write: Callable[[], T]) -> T:
        with self._repo.locked(self._owner, self._run) as record:
            self._check(record)
            return write()

    @contextmanager
    def step(self, kind):
        self.check()
        if kind in self._spans:
            yield
            self.check()
            return
        started = self._now()
        with self._repo.locked(self._owner, self._run) as record:
            self._check(record)
            if kind in {"model", "tool"}:
                counter, limit = (
                    ("model_requests", record.budget.max_model_requests)
                    if kind == "model"
                    else ("tool_calls", record.budget.max_tool_calls)
                )
                if getattr(record.metadata, counter) >= limit:
                    raise BudgetExceeded()
                record.metadata = record.metadata.model_copy(update={counter: getattr(record.metadata, counter) + 1})
            if kind == "model":
                self._model_attempts = 0
            event(record, "step_started", action_key=kind)
        self._spans.append(kind)
        try:
            yield
            self.check()
        except BaseException:
            with self._repo.locked(self._owner, self._run) as record:
                event(record, "step_failed", action_key=kind, duration_ms=max(0, (self._now() - started) * 1000))
            # Stop outranks an I/O failure: its caller must not start fallback.
            self.check()
            raise
        else:
            with self._repo.locked(self._owner, self._run) as record:
                event(record, "step_completed", action_key=kind, duration_ms=max(0, (self._now() - started) * 1000))
        finally:
            self._spans.pop()

    def model_started(self, model, instruction, tools):
        with self._repo.locked(self._owner, self._run) as record:
            self._check(record)
            record.metadata = record.metadata.model_copy(
                update={
                    "configured_model": model_name(model),
                    "instruction_hash": content_hash(instruction),
                    "schema_hash": content_hash(tools),
                }
            )

    def model_returned(self, returned_model, usage: ProviderUsage | None):
        with self._repo.locked(self._owner, self._run) as record:
            updates = {"returned_model": model_name(returned_model)}
            if usage is not None:
                updates.update(
                    usage=combine_usage(record.metadata.usage, usage),
                    usage_responses=record.metadata.usage_responses + 1,
                )
            record.metadata = record.metadata.model_copy(update=updates)

    def sdk_attempt(self):
        with self._repo.locked(self._owner, self._run) as record:
            self._check(record)
            self._model_attempts += 1
            record.metadata = record.metadata.model_copy(
                update={
                    "provider": "gemini",
                    "sdk_attempts": (record.metadata.sdk_attempts or 0) + 1,
                    "sdk_retries": (record.metadata.sdk_retries or 0) + (self._model_attempts > 1),
                }
            )


class AgentExecutionService:
    def __init__(self, repo: RunRepository | None = None, *, monotonic=system_monotonic, control=None, verifier=None):
        if (repo is None) == (control is None) or (control is not None and verifier is None):
            raise ValueError("Choose one explicit run storage boundary")
        self._repo, self._now = repo, monotonic
        self._revision = source_revision()
        self._runtime_hash = runtime_hash()
        self._durable = None
        if control is not None:
            from .durable_agent_execution import DurableAgentExecutionService

            self._durable = DurableAgentExecutionService(control=control, verifier=verifier, monotonic=monotonic,
                                                        revision=self._revision, runtime_hash=self._runtime_hash)

    def start(self, owner: UUID, run_id: UUID):
        if self._durable is not None:
            return self._durable.start(owner, run_id)
        now = self._now()
        record = RunRecord(
            budget=ExecutionBudget(deadline_monotonic=now + 45),
            started_monotonic=now,
            metadata=RunMetadata(run_id=run_id, revision=self._revision, runtime_hash=self._runtime_hash),
        )
        event(record, "run_started")
        self._repo.create(owner, record)

    def read(self, owner, run_id):
        if self._durable is not None:
            return self._durable.read(owner, run_id)
        with self._repo.locked(owner, run_id) as record:
            return record.snapshot()

    def cancel(self, owner, run_id):
        if self._durable is not None:
            return self._durable.cancel(owner, run_id)
        with self._repo.locked(owner, run_id) as record:
            if record.status == "running":
                record.status = "cancelling"
                event(record, "run_cancelling", reason_key="cancelled")
            return record.snapshot()

    def execute(self, owner: UUID, run_id: UUID, work: Callable[[], T]) -> T:
        if self._durable is not None:
            return self._durable.execute(owner, run_id, work)
        with self._repo.locked(owner, run_id) as record:
            if record.claimed:
                raise DuplicateEventError("Assistant run was already executed; read its status")
            record.claimed = True
        control = ExecutionControl(self._repo, owner, run_id, self._now)
        token = current_execution.set(control)
        try:
            with execution_step("application"):
                result = work()
            # Cancellation and completion serialize at the same boundary.
            with self._repo.locked(owner, run_id) as record:
                control.check()
                record.status = "completed"
                event(record, "run_completed")
            return result
        except BaseException as exc:
            with self._repo.locked(owner, run_id) as record:
                if record.status not in TERMINAL:
                    cancelled = isinstance(exc, TaskCancelled) or record.status == "cancelling"
                    record.status = "cancelled" if cancelled else "failed"
                    reason = (
                        "cancelled"
                        if cancelled
                        else exc.reason
                        if isinstance(exc, ExecutionStopped)
                        else "execution_failed"
                    )
                    event(record, "run_cancelled" if cancelled else "run_failed", reason_key=reason)
            raise
        finally:
            with self._repo.locked(owner, run_id) as record:
                record.metadata = record.metadata.model_copy(
                    update={
                        "duration_ms": max(0, (self._now() - record.started_monotonic) * 1000),
                    }
                )
            current_execution.reset(token)
