"""UTC durable run commands; worker observations have no clinical authority."""

from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime, Field, TypeAdapter, model_validator

from .agent_execution import ProviderUsage, Reason, RunSnapshot, RunStatus, RuntimeDTO, StepKind

Epoch = Annotated[int, Field(strict=True, ge=0)]
Duration = Annotated[float, Field(ge=0, allow_inf_nan=False)]
ModelName = Annotated[str, Field(max_length=100, pattern=r"^[a-zA-Z0-9._/-]+$")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class RunControlState(RuntimeDTO):
    owner: UUID
    run_id: UUID
    task_id: UUID | None = None
    epoch: Epoch
    worker_ticket: UUID = Field(repr=False)
    worker_nonce: UUID = Field(repr=False)
    started_at: AwareDatetime
    deadline_at: AwareDatetime
    server_now: AwareDatetime
    status: RunStatus
    snapshot: RunSnapshot
    claim_acquired: bool = False

    @model_validator(mode="after")
    def matched_snapshot(self):
        if self.snapshot.status != self.status or self.snapshot.metadata.run_id != self.run_id:
            raise ValueError("Run snapshot binding changed")
        if not 0 < (self.deadline_at - self.started_at).total_seconds() <= 45:
            raise ValueError("Run deadline exceeds the server budget")
        if any(e.run_id != self.run_id or e.sequence != i for i, e in enumerate(self.snapshot.events, 1)):
            raise ValueError("Run event sequence binding changed")
        return self


class WorkerRunCommand(RuntimeDTO):
    ticket_id: UUID
    nonce: UUID = Field(repr=False)
    epoch: Epoch
    event_id: UUID


class ClaimRun(WorkerRunCommand):
    kind: Literal["claim"] = "claim"
    revision: Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")] | None = None
    runtime_hash: Digest | None = None


class StartRunStep(WorkerRunCommand):
    kind: Literal["start_step"] = "start_step"
    span_id: UUID
    step_kind: StepKind


class FinishRunStep(WorkerRunCommand):
    kind: Literal["finish_step"] = "finish_step"
    span_id: UUID
    succeeded: bool = Field(strict=True)
    duration_ms: Duration


class ProviderAttempt(RuntimeDTO):
    phase: Literal["attempt"] = "attempt"
    span_id: UUID
    attempt_id: UUID


class ProviderMetadata(RuntimeDTO):
    phase: Literal["metadata"] = "metadata"
    configured_model: ModelName | None = None
    instruction_hash: Digest
    schema_hash: Digest


class ProviderResponse(RuntimeDTO):
    phase: Literal["response"] = "response"
    attempt_id: UUID
    returned_model: ModelName | None = None
    usage: ProviderUsage | None = None


class RecordRunProvider(WorkerRunCommand):
    kind: Literal["record_usage"] = "record_usage"
    observation: Annotated[ProviderAttempt | ProviderMetadata | ProviderResponse, Field(discriminator="phase")]


class FinishRun(WorkerRunCommand):
    kind: Literal["finish"] = "finish"
    status: Literal["completed", "cancelled", "failed"]
    reason: Reason | None = None
    duration_ms: Duration


class RecoverInterruptedRun(WorkerRunCommand):
    kind: Literal["recover_interrupted"] = "recover_interrupted"


RunWorkerCommand = Annotated[
    ClaimRun | StartRunStep | FinishRunStep | RecordRunProvider | FinishRun | RecoverInterruptedRun,
    Field(discriminator="kind"),
]
RUN_WORKER_COMMAND = TypeAdapter(RunWorkerCommand)


class DurableRunControlPort(Protocol):
    def start(self, owner: UUID, run_id: UUID, task_id: UUID | None) -> RunControlState: ...
    def read(self, owner: UUID, run_id: UUID) -> RunControlState: ...
    def request_cancel(self, owner: UUID, run_id: UUID) -> RunControlState: ...
