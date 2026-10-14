"""Typed tool contracts: allowlisted names, typed requests and results.

The agent's tool surface is an explicit allowlist (AGENTS.md rule 21). A tool
declares its parameters as a frozen DTO; nothing accepts a raw dict.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ..contracts.enums import ToolName, ToolStatus


class ToolDTO(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ToolRequest(ToolDTO):
    """Every tool call is scoped by an authenticated patient identity.

    ``patient_id`` is derived from the validated server token at the transport
    boundary — never chosen by the LLM (AGENTS.md rule 22).
    """

    patient_id: UUID
    session_id: UUID
    correlation_id: UUID
    client_turn_id: str = Field(min_length=1, max_length=128)


class CreateReminderRequest(ToolRequest):
    occurrence_id: UUID
    minutes: int = Field(ge=1, le=1440)


class EnrollMedicationRequest(ToolRequest):
    medication_name: str = Field(min_length=1, max_length=160)
    dose_amount: float | None = None
    dose_unit: str | None = None
    frequency_kind: str | None = None
    frequency_local_times: list[str] = Field(default_factory=list)
    frequency_days_of_week: list[int] = Field(default_factory=list)
    frequency_every_hours: int | None = None
    is_prn: bool = False
    route: str | None = None
    food_instruction: str | None = None


class ConfirmRegimenRequest(ToolRequest):
    regimen_id: UUID
    challenge_id: UUID
    session_state: str
    session_state_version: int


class CheckDueDoseRequest(ToolRequest):
    window: Literal["due", "tonight"] = "due"
    regimen_id: UUID | None = None


class RecordSelfReportRequest(ToolRequest):
    regimen_id: UUID
    occurrence_id: UUID | None = None
    intake_status: str
    idempotency_key: str = Field(min_length=1, max_length=128)
    confirmed_challenge_id: UUID | None = None


class ListActiveMedicationsRequest(ToolRequest):
    pass


class MedicationHistoryRequest(ToolRequest):
    regimen_id: UUID
    days: int = 7


class GetDoseStatusRequest(ToolRequest):
    """Read-only dose-status question: "Have I taken <medication> today?".

    ``medication_name`` is free text from the patient turn; the handler is
    responsible for resolving it to a patient-owned medication or reporting
    that it could not be resolved. It is never treated as an identifier.
    """

    medication_name: str | None = Field(default=None, min_length=1, max_length=160)
    medication_id: UUID | None = None
    occurrence_id: UUID | None = None
    day_offset: int = Field(default=0, ge=-30, le=0)


class EnrollmentResultPayload(ToolDTO):
    """Serialised enrollment outcome; missing instructions stay explicit."""

    medication_id: UUID
    regimen_id: UUID
    state: str
    missing_instructions: list[str] = Field(default_factory=list)


class ToolResult(ToolDTO):
    tool_name: ToolName
    status: ToolStatus
    payload: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    rule_id: str | None = None
    requires_confirmation: bool = False
    clarification_question: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in (ToolStatus.SUCCESS, ToolStatus.SIMULATED)

    @property
    def blocked(self) -> bool:
        return self.status in (ToolStatus.BLOCKED, ToolStatus.FAILED)
