"""Typed persistence bindings are constraints, never independent confirmation."""

from typing import Annotated, Generic, Literal, Protocol, TypeVar
from uuid import UUID

from pydantic import AwareDatetime, Field, TypeAdapter, model_validator

from .assistant_workflows import BusinessRef, ControlReceipt, SaveMode, WorkflowDTO, WorkflowTask, WorkflowUpdate

PositiveRevision = Annotated[int, Field(strict=True, ge=1)]
DomainRevision = Annotated[int, Field(strict=True, ge=0)]
T = TypeVar("T")


class RunWriteBinding(WorkflowDTO):
    run_id: UUID
    epoch: PositiveRevision


class WorkflowWriteBinding(WorkflowDTO):
    task_id: UUID
    task_revision: PositiveRevision
    capability_id: str = Field(pattern=r"^[a-z][a-z0-9_.]{1,119}$")
    action_key: UUID
    prepared_ref: BusinessRef
    expected_domain_revision: DomainRevision
    run_binding: RunWriteBinding | None = None


class BusinessWriteReceipt(WorkflowDTO):
    owner: UUID
    task_id: UUID
    action_key: UUID
    capability_id: str = Field(pattern=r"^[a-z][a-z0-9_.]{1,119}$")
    binding_revision: PositiveRevision
    business_ref: BusinessRef
    domain_revision: DomainRevision
    outcome: Literal["prepared", "applied"]
    recorded_at: AwareDatetime


class NativeWriteResult(WorkflowDTO, Generic[T]):
    """Native response is returned, not copied into the immutable receipt store."""

    receipt: BusinessWriteReceipt
    result: T


class StartSavedWorkflow(WorkflowDTO):
    kind: Literal["start"] = "start"
    task: WorkflowTask
    event_id: UUID | None = None
    request_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    run_binding: RunWriteBinding | None = None

    @model_validator(mode="after")
    def saved_only(self):
        if self.task.save_mode != "allowed":
            raise ValueError("No-save starts use content-free controls")
        return self


class StartEphemeralWorkflow(WorkflowDTO):
    kind: Literal["start_ephemeral"] = "start_ephemeral"
    control: ControlReceipt
    run_binding: RunWriteBinding | None = None

    @model_validator(mode="after")
    def ephemeral_only(self):
        if self.control.mode != "ephemeral":
            raise ValueError("This start requires no-save control metadata")
        return self


class VersionedWorkflowMutation(WorkflowDTO):
    task_id: UUID
    expected_revision: PositiveRevision
    run_binding: RunWriteBinding | None = None


class AdvanceWorkflow(VersionedWorkflowMutation):
    kind: Literal["advance"] = "advance"
    event_id: UUID
    update: WorkflowUpdate
    request_digest: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def no_mode_change(self):
        if self.update.save_mode != "allowed":
            raise ValueError("Saving mode changes use a content-free command")
        return self


class BindWorkflowConversation(VersionedWorkflowMutation):
    kind: Literal["bind_conversation"] = "bind_conversation"
    conversation_id: UUID


class SwitchWorkflowMode(VersionedWorkflowMutation):
    kind: Literal["switch_mode"] = "switch_mode"
    event_id: UUID
    mode: SaveMode


class RevokeWorkflow(VersionedWorkflowMutation):
    kind: Literal["revoke"] = "revoke"
    event_id: UUID


class ResumeWorkflowHandoff(VersionedWorkflowMutation):
    kind: Literal["resume_handoff"] = "resume_handoff"
    target_task_id: UUID
    target_revision: PositiveRevision
    event_id: UUID
    target_state: Literal[
        "choose_method",
        "collecting",
        "validating",
        "ready_for_review",
        "awaiting_confirmation",
        "failed_recoverable",
        "outcome_unknown",
    ] = "collecting"

    @model_validator(mode="after")
    def different_tasks(self):
        if self.target_task_id == self.task_id:
            raise ValueError("Recovery handoff requires a different task")
        return self


WorkflowMutation = Annotated[
    StartSavedWorkflow
    | StartEphemeralWorkflow
    | AdvanceWorkflow
    | BindWorkflowConversation
    | SwitchWorkflowMode
    | RevokeWorkflow
    | ResumeWorkflowHandoff,
    Field(discriminator="kind"),
]
WorkflowMutationResult = WorkflowTask | ControlReceipt
_MUTATION = TypeAdapter(WorkflowMutation)


def parse_workflow_mutation(value: object) -> WorkflowMutation:
    return _MUTATION.validate_python(value)


class WorkflowMutationPort(Protocol):
    def apply(self, owner: UUID, command: WorkflowMutation) -> WorkflowMutationResult: ...
    def read_receipt(self, owner: UUID, action_key: UUID) -> BusinessWriteReceipt | None: ...
