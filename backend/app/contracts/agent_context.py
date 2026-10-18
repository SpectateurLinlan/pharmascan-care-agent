"""Versioned short-lived context, not permanent patient facts or vector memory."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .medication_dialogue import MedicationDialogue


class CandidateReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    medication_id: UUID
    regimen_id: UUID
    display_name: str = Field(max_length=200)


class ClarificationContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["medication_choice"] = "medication_choice"
    candidates: list[CandidateReference] = Field(max_length=10)
    requested_intake_status: Literal["taken", "not_taken", "unsure"] | None = None


class RecentTurn(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    user: str = Field(max_length=500)
    assistant: str = Field(max_length=700)


class CareClarification(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    missing_field: Literal[
        "medication",
        "stock_quantity",
        "stock_unit",
        "follow_up_date",
        "follow_up_type",
        "barrier_time",
        "support_action",
    ]


class AgentContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    version: Literal[1] = 1
    active_task: str | None = Field(default=None, max_length=50)
    last_intent: str | None = Field(default=None, max_length=50)
    referenced_medication_id: UUID | None = None
    referenced_regimen_id: UUID | None = None
    referenced_occurrence_id: UUID | None = None
    enrollment_task_id: UUID | None = None
    awaiting_clarification: ClarificationContext | None = None
    care_clarification: CareClarification | None = None
    preferred_language: Literal["en", "zh"] = "en"
    recent_turns: list[RecentTurn] = Field(default_factory=list, max_length=6)
    conversation_summary: str = Field(default="", max_length=600)
    medication_dialogue: MedicationDialogue | None = None
