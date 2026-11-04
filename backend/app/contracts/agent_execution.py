"""Content-free execution port. Cancellation can stop, never authorize, a write."""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from typing import Literal, Protocol, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ..domain.errors import DomainError

T = TypeVar("T")
StepKind = Literal["application", "model", "tool"]
RunStatus = Literal["running", "cancelling", "completed", "cancelled", "failed"]
Reason = Literal["cancelled", "deadline_exceeded", "budget_exceeded", "execution_failed", "worker_interrupted"]


class ExecutionStopped(DomainError):
    reason: Reason = "execution_failed"

    def __init__(self):
        super().__init__("Assistant execution stopped; check its current status")


class TaskCancelled(ExecutionStopped):
    reason = "cancelled"


class DeadlineExceeded(ExecutionStopped):
    reason = "deadline_exceeded"


class BudgetExceeded(ExecutionStopped):
    reason = "budget_exceeded"


class RuntimeDTO(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ExecutionBudget(RuntimeDTO):
    deadline_monotonic: float
    max_model_requests: int = Field(default=4, ge=0, le=4)
    max_tool_calls: int = Field(default=4, ge=0, le=4)


class ProviderUsage(RuntimeDTO):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)


class RunMetadata(RuntimeDTO):
    run_id: UUID
    provider: Literal["gemini"] | None = None
    configured_model: str | None = Field(default=None, max_length=100, pattern=r"^[a-zA-Z0-9._/-]+$")
    returned_model: str | None = Field(default=None, max_length=100, pattern=r"^[a-zA-Z0-9._/-]+$")
    instruction_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    schema_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{40}$")
    runtime_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    model_requests: int = 0
    tool_calls: int = 0
    sdk_attempts: int | None = None
    sdk_retries: int | None = None
    usage: ProviderUsage | None = None
    usage_responses: int = 0
    duration_ms: float = 0


class RunEvent(RuntimeDTO):
    sequence: int = Field(ge=1)
    run_id: UUID
    task_id: UUID | None = None
    action_key: StepKind | None = None
    kind: Literal[
        "run_started",
        "step_started",
        "step_completed",
        "step_failed",
        "run_cancelling",
        "run_completed",
        "run_cancelled",
        "run_failed",
    ]
    status: RunStatus
    reason_key: Reason | None = None
    duration_ms: float | None = None


class RunSnapshot(RuntimeDTO):
    status: RunStatus
    metadata: RunMetadata
    events: tuple[RunEvent, ...]


@dataclass
class RunRecord:
    """Public control-storage DTO, never clinical data or a saved reply."""

    budget: ExecutionBudget
    started_monotonic: float
    metadata: RunMetadata
    status: RunStatus = "running"
    claimed: bool = False
    events: list[RunEvent] = field(default_factory=list)

    def snapshot(self) -> RunSnapshot:
        return RunSnapshot(status=self.status, metadata=self.metadata, events=tuple(self.events))


class RunRepository(Protocol):
    def create(self, owner: UUID, record: RunRecord) -> None: ...
    def locked(self, owner: UUID, run_id: UUID) -> AbstractContextManager[RunRecord]: ...


class ExecutionPort(Protocol):
    def check(self) -> None: ...
    def remaining(self, native_timeout: float) -> float: ...
    def step(self, kind: StepKind) -> AbstractContextManager[None]: ...
    def guarded(self, write: Callable[[], T]) -> T: ...
    def model_started(self, model: str | None, instruction: str, tools: list[dict[str, object]]) -> None: ...
    def model_returned(self, returned_model: str | None, usage: ProviderUsage | None) -> None: ...
    def sdk_attempt(self) -> None: ...


current_execution: ContextVar[ExecutionPort | None] = ContextVar("assistant_execution", default=None)


def checkpoint() -> None:
    if control := current_execution.get():
        control.check()


def bounded_timeout(native_timeout: float) -> float:
    control = current_execution.get()
    return control.remaining(native_timeout) if control else native_timeout


def tracked_step(kind: StepKind):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with execution_step(kind):
                return function(*args, **kwargs)

        return wrapped

    return decorate


@contextmanager
def execution_step(kind: StepKind) -> Iterator[None]:
    control = current_execution.get()
    if control is None:
        yield
    else:
        with control.step(kind):
            yield
