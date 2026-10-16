"""Patient-readable conversation records, separate from model context and clinical facts."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class HistoryTurn(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: UUID
    patient_id: UUID
    session_id: UUID
    user_text: str = Field(max_length=2000)
    assistant_text: str = Field(max_length=4000)
    created_at: datetime


class HistoryEntry(BaseModel):
    id: UUID
    user_text: str
    assistant_text: str
    created_at: datetime


class HistoryPage(BaseModel):
    entries: list[HistoryEntry]
    next_before: UUID | None = None


class ConversationHistoryRepository(Protocol):
    def append(self, row: HistoryTurn) -> None: ...
    def page(self, patient_id: UUID, since: datetime, before: UUID | None, limit: int) -> list[HistoryTurn]: ...
    def clear(self, patient_id: UUID) -> None: ...
