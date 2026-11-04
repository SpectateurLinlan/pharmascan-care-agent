"""Closed conversation transactions, separate from patient business commands."""

from datetime import datetime
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import Field, TypeAdapter, field_validator, model_validator

from .assistant_workflows import WorkflowDTO
from .conversation_history import HistoryTurn
from .conversation_threads import ConversationMessage, ConversationSummary
from .dto import AgentSessionDTO, ToolTraceDTO
from .workflow_persistence import PositiveRevision, RunWriteBinding


class ConversationWriteScope(WorkflowDTO):
    task_id: UUID | None = None
    revision: PositiveRevision | None = None
    run_binding: RunWriteBinding | None = None

    @model_validator(mode="after")
    def paired_task(self):
        if (self.task_id is None) != (self.revision is None):
            raise ValueError("Use a complete current task binding")
        return self


class ScopedMessageWrite(WorkflowDTO):
    scope: ConversationWriteScope = Field(default_factory=ConversationWriteScope)

    @model_validator(mode="after")
    def aware_native_instants(self):
        for name in ("session", "message", "conversation", "turn", "trace"):
            row = getattr(self, name, None)
            if row is None:
                continue
            for field in ("created_at", "updated_at", "expires_at", "called_at"):
                instant = getattr(row, field, None)
                if isinstance(instant, datetime) and instant.utcoffset() is None:
                    raise ValueError("Conversation transactions require timezone-aware instants")
        return self


class CreateConversation(ScopedMessageWrite):
    kind: Literal["create_conversation"] = "create_conversation"
    conversation: ConversationSummary


class CreateSession(ScopedMessageWrite):
    kind: Literal["create_session"] = "create_session"
    session: AgentSessionDTO


class UpdateSessionContext(ScopedMessageWrite):
    kind: Literal["update_context"] = "update_context"
    session: AgentSessionDTO


class BindConversationSession(ScopedMessageWrite):
    kind: Literal["bind_session"] = "bind_session"
    session: AgentSessionDTO


class ClaimConversationTurn(ScopedMessageWrite):
    kind: Literal["claim_turn"] = "claim_turn"
    conversation_id: UUID
    turn_id: UUID
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class AppendConversationTurn(ScopedMessageWrite):
    kind: Literal["append_turn"] = "append_turn"
    session_id: UUID
    message: ConversationMessage


class FailConversationTurn(ScopedMessageWrite):
    kind: Literal["fail_turn"] = "fail_turn"
    turn_id: UUID


class AppendLegacyHistory(ScopedMessageWrite):
    kind: Literal["append_legacy_history"] = "append_legacy_history"
    turn: HistoryTurn


class ClearConversationHistory(ScopedMessageWrite):
    kind: Literal["clear_history"] = "clear_history"
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def independent_confirmation(cls, value):
        if value is not True:
            raise ValueError("Confirm clearing conversation history explicitly")
        return value


class AppendSafeTrace(ScopedMessageWrite):
    kind: Literal["append_safe_trace"] = "append_safe_trace"
    trace: ToolTraceDTO

    @model_validator(mode="after")
    def safe_summaries(self):
        keys = {
            "item_count",
            "demo_only",
            "decision",
            "error_code",
            "state",
            "intake_status",
            "visual_status",
            "already_recorded",
            "missing_count",
        }
        for summary in (self.trace.request_summary, self.trace.response_summary):
            if set(summary) - keys or any(type(v) not in {str, bool, int, type(None)} for v in summary.values()):
                raise ValueError("Trace summary must contain only allowed technical scalars")
            if any(
                isinstance(v, str) and (len(v) > 80 or not all(c.isalnum() or c in "_-" for c in v))
                for v in summary.values()
            ):
                raise ValueError("Trace summary cannot contain untrusted text")
        return self


ConversationWriteCommand = Annotated[
    CreateConversation
    | CreateSession
    | UpdateSessionContext
    | BindConversationSession
    | ClaimConversationTurn
    | AppendConversationTurn
    | FailConversationTurn
    | AppendLegacyHistory
    | ClearConversationHistory
    | AppendSafeTrace,
    Field(discriminator="kind"),
]


class MessageWriteAck(WorkflowDTO):
    kind: Literal["ack"] = "ack"


class ConversationClaimResult(WorkflowDTO):
    kind: Literal["claim"] = "claim"
    status: Literal["new", "completed", "busy"]


class SavedConversationMessage(WorkflowDTO):
    kind: Literal["message"] = "message"
    message: ConversationMessage


ConversationWriteResult = Annotated[
    MessageWriteAck | ConversationClaimResult | SavedConversationMessage, Field(discriminator="kind")
]
MESSAGE_COMMAND = TypeAdapter(ConversationWriteCommand)
MESSAGE_RESULT = TypeAdapter(ConversationWriteResult)
HISTORY_WRITES = frozenset({"create_conversation", "claim_turn", "append_turn", "append_legacy_history"})


class ConversationPersistencePort(Protocol):
    def execute(self, owner: UUID, command: ConversationWriteCommand) -> ConversationWriteResult: ...
