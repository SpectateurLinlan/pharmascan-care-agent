"""Durable patient text, separate from executable tool/session state."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ConversationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID
    title: str = Field(max_length=120)
    created_at: datetime
    updated_at: datetime


class ConversationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID
    conversation_id: UUID
    user_text: str = Field(max_length=2000)
    assistant_text: str = Field(max_length=32000)
    photo_attached: bool = False
    created_at: datetime


class ConversationList(BaseModel):
    entries: list[ConversationSummary]
    next_before: UUID | None = None


class ConversationPage(BaseModel):
    conversation: ConversationSummary
    entries: list[ConversationMessage]
    next_before: UUID | None = None


class ConversationResume(BaseModel):
    conversation: ConversationSummary
    session_id: UUID


class ConversationThreads(Protocol):
    def create(self, owner: UUID, row: ConversationSummary) -> None: ...
    def get(self, owner: UUID, conversation_id: UUID) -> ConversationSummary | None: ...
    def list(self, owner: UUID, before: UUID | None, limit: int) -> list[ConversationSummary]: ...
    def messages(
        self, owner: UUID, conversation_id: UUID, before: UUID | None, limit: int
    ) -> list[ConversationMessage]: ...
    def claim(
        self, owner: UUID, conversation_id: UUID, turn_id: UUID, digest: str
    ) -> Literal["new", "completed", "busy"]: ...
    def message(self, owner: UUID, turn_id: UUID) -> ConversationMessage | None: ...
    def append(self, owner: UUID, session_id: UUID, row: ConversationMessage) -> ConversationMessage: ...
    def fail(self, owner: UUID, turn_id: UUID) -> None: ...
    def clear(self, owner: UUID) -> None: ...
