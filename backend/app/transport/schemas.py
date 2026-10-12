"""Typed HTTP request/response schemas for the transport layer.

These are transport-level DTOs: they are deliberately separate from both the
domain DTOs (``contracts.dto``) and the agent tool request objects
(``agent.tools``). The transport must not leak repository or agent internals,
and it must not let a caller choose an arbitrary ``patient_id`` — the patient
is always derived from the (demo) principal, never from the request body.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Request(BaseModel):
    """Base transport request: reject unknown fields, forbid mutation."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    service: str = "pharmascan-care-agent"
    #: Honest capability flags. Nothing here claims a live external dependency.
    database: Literal["simulated_in_memory", "postgres"] = "simulated_in_memory"
    llm: Literal["unavailable_deterministic_degraded"] = "unavailable_deterministic_degraded"
    stage2_vision: Literal["simulated", "live"] = "simulated"


class DemoStartRequest(Request):
    """Start an isolated demo session for the anonymous principal.

    ``client_id`` identifies the browser tab so a reload can resume the same
    synthetic patient instead of seeding a second one.
    """

    client_id: str = Field(min_length=1, max_length=128)


class DemoStartResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: UUID
    session_id: UUID
    demo_only: Literal[True] = True
    seeded_medication_count: int = 0
    note: str = "synthetic demo data only; no real patient record"


class AgentMessageRequest(Request):
    text: str = Field(default="", max_length=2000)
    session_id: UUID | None = None
    client_turn_id: str = Field(default="turn-1", min_length=1, max_length=128)
    #: Optional typed slots (sliders / buttons in the UI) mapped to tool inputs.
    slots: dict[str, Any] = Field(default_factory=dict)


class ToolTraceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    status: str
    error_code: str | None = None
    requires_confirmation: bool = False
    clarification_question: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentMessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    intent: str
    session_id: UUID
    session_state: str
    requires_confirmation: bool
    #: Always surfaced so the UI can never present this as a live LLM agent.
    mode: str
    tool_traces: list[ToolTraceResponse] = Field(default_factory=list)


class MedicationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medication_id: UUID
    regimen_id: UUID
    display_name: str
    is_prn: bool
    version_no: int
    #: Evidence provenance: never "verified" unless a human reviewed the source.
    identity_status: str = "unverified"
    source_backed: bool = True


class MedicationListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_count: int
    medications: list[MedicationSummary] = Field(default_factory=list)
    note: str = "active regimens only; history preserved separately"


class DraftCreateRequest(Request):
    medication_name: str = Field(min_length=1, max_length=200)
    dose_amount: float | None = None
    dose_unit: str | None = Field(default=None, max_length=40)
    frequency_kind: Literal["daily", "weekly", "interval_hours"] | None = None
    frequency_local_times: list[str] = Field(default_factory=list)
    frequency_days_of_week: list[int] = Field(default_factory=list)
    frequency_every_hours: int | None = None
    is_prn: bool = False
    route: str | None = Field(default=None, max_length=40)
    food_instruction: str | None = Field(default=None, max_length=200)


class DraftCreateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medication_id: UUID
    regimen_id: UUID
    state: str
    source_id: UUID
    missing_instructions: list[str] = Field(default_factory=list)
    reviewable_field_ids: list[UUID] = Field(default_factory=list)
    note: str = "draft only; activation requires reviewed required inputs and explicit confirmation"


class DraftReviewRequest(Request):
    field_ids: list[UUID] | None = None


class DraftReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewed_field_count: int
    source_id: UUID
    note: str = "reviewing the medication-name evidence promotes identity to user_reviewed_document"


class ConfirmChallengeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    regimen_id: UUID
    challenge_id: UUID
    session_id: UUID
    session_state: str
    session_state_version: int
    expires_at: datetime
    #: What the patient is being asked to approve. Shown verbatim in the UI.
    summary: dict[str, Any] = Field(default_factory=dict)
    note: str = "single-use; a new challenge is needed for every activation attempt"


class ConfirmActivateRequest(Request):
    regimen_id: UUID
    challenge_id: UUID
    session_id: UUID
    session_state: str
    session_state_version: int


class ConfirmActivateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    regimen_id: UUID
    state: str
    superseded_regimen_ids: list[UUID] = Field(default_factory=list)


class DueDoseResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    occurrence_id: UUID | None
    regimen_id: UUID
    medication_display_name: str
    dose_description: str | None
    due_at: datetime | None
    is_prn: bool
    #: The UI must never render this as "you took it" or "you missed it".
    visual_status: str = "not_checked"
    ingestion_proven: Literal[False] = False


class SelfReportRequest(Request):
    regimen_id: UUID
    occurrence_id: UUID | None = None
    intake_status: str = Field(min_length=1, max_length=40)
    idempotency_key: str = Field(min_length=1, max_length=200)


class SelfReportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID | None
    intake_status: str
    visual_status: str
    already_recorded: bool
    ingestion_proven: Literal[False] = False
    note: str = "a self report records what the patient said, never proof of ingestion"


class DoseHistoryEntryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    occurrence_id: UUID | None
    due_at: datetime | None
    intake_status: str | None
    visual_status: str | None
    reported: bool


class DoseHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_count: int
    entries: list[DoseHistoryEntryResponse] = Field(default_factory=list)
    note: str = "not_reported is NOT the same as missed"
