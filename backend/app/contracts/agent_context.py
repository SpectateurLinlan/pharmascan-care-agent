"""Versioned short-lived context, not permanent patient facts or vector memory."""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SerializerFunctionWrapHandler, model_serializer

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


class PendingIntervalEnrollment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    medication_name: str = Field(min_length=1, max_length=160)
    every_hours: int = Field(ge=1, le=720)
    dose_amount: float | None = None
    dose_unit: str | None = Field(default=None, max_length=40)
    course_start_date: date | None = None
    course_end_date: date | None = None
    route: str | None = Field(default=None, max_length=40)
    food_instruction: str | None = Field(default=None, max_length=200)
    local_time: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    use_default: bool = False
    expires_at: datetime


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
    pending_interval_enrollment: PendingIntervalEnrollment | None = None

    @model_serializer(mode="wrap")
    def serialize_context(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data = handler(self)
        if self.pending_interval_enrollment is None:
            data.pop("pending_interval_enrollment", None)
        return data
