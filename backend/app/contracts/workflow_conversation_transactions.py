"""Closed independently confirmed native conversation transition."""

from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from .assistant_workflows import WorkflowDTO
from .dto import AgentSessionDTO


class ConversationTransition(WorkflowDTO):
    task_id: UUID
    revision: int = Field(strict=True, ge=1)
    capability_id: Literal["conversation.new", "conversation.resume", "conversation.clear"]
    target: UUID | None = None
    action_key: UUID
    session_id: UUID
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("Independent confirmation required")
        return value

    @model_validator(mode="after")
    def target_scope(self):
        if (self.capability_id == "conversation.resume") != (self.target is not None):
            raise ValueError("Resume requires one owned conversation")
        return self


class ConversationTransitionResult(WorkflowDTO):
    session: AgentSessionDTO | None = None


class ConversationTransitionPort(Protocol):
    def execute(self, owner: UUID, command: ConversationTransition) -> ConversationTransitionResult: ...
