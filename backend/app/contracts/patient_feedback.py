"""Bounded patient feedback; not a medical message or emergency channel."""

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FeedbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID
    category: Literal["issue", "suggestion"]
    message: str = Field(min_length=5, max_length=2000)


class PatientFeedback(FeedbackInput):
    patient_id: UUID
    created_at: datetime
    demo_only: Literal[True] = True


class FeedbackRepository(Protocol):
    def save(self, row: PatientFeedback) -> PatientFeedback: ...
