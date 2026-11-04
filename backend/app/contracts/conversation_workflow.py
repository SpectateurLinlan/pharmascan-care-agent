"""Closed chat-support operations; history and device text grant no clinical authority."""

from uuid import UUID

from pydantic import Field

from .assistant_workflows import NavigateAction, WorkflowDTO


class ConversationListFields(WorkflowDTO):
    before: UUID | None = None


class ConversationFields(ConversationListFields):
    conversation_id: UUID | None = None


class EmptySupportFields(WorkflowDTO):
    pass


class FeedbackFields(WorkflowDTO):
    category: str = Field(default="issue", pattern=r"^(issue|suggestion)$")
    message: str | None = Field(default=None, min_length=5, max_length=2000)


class NavigationFields(WorkflowDTO):
    destination: NavigateAction | None = None
    regimen_id: UUID | None = None
    medication_id: UUID | None = None
    care_task_id: UUID | None = None


CONVERSATION_SCHEMAS = {"conversation.list": ConversationListFields, "conversation.view": ConversationFields,
    "conversation.resume": ConversationFields, "conversation.new": EmptySupportFields,
    "conversation.clear": EmptySupportFields, "assistant.usage": EmptySupportFields}
SUPPORT_SCHEMAS = {"feedback.submit": FeedbackFields, "speech.input": EmptySupportFields,
    "speech.playback": EmptySupportFields, "help.open": EmptySupportFields, "guide.start": EmptySupportFields,
    "navigation.open": NavigationFields}
