"""Application-facing typed DTOs (Pydantic v2).

External provider DTOs (Stage2 vision) live separately in the vision adapter
contract so that unfrozen external schemas never leak into domain types
(API_CONTRACTS.md section B).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .enums import (
    FieldName,
    IdentityStatus,
    IntakeStatus,
    OccurrenceStatus,
    RegimenState,
    RuleKind,
    SourceKind,
    SourceReviewStatus,
    VisualStatus,
)


class DTO(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --- Source documents / fields (provenance) ---------------------------------


class SourceDocumentDTO(DTO):
    id: UUID
    patient_id: UUID
    source_kind: SourceKind
    review_status: SourceReviewStatus
    reviewed_at: datetime | None
    demo_only: bool = True


class SourceFieldDTO(DTO):
    id: UUID
    patient_id: UUID
    source_id: UUID
    field_name: FieldName
    field_value: Any
    review_status: SourceReviewStatus
    reviewed_at: datetime | None
    demo_only: bool = True


class FrequencyRuleDTO(DTO):
    """Deterministic schedule rule (mirrors SQL jsonb CHECK).

    kind=daily    : times_per_day local times
    kind=weekly   : days_of_week (1=Mon..7=Sun) + local_time
    kind=interval : every_hours
    """

    kind: RuleKind | str = Field(pattern="^(daily|weekly|interval)$")
    local_times: list[str] = Field(default_factory=list)  # "HH:MM"
    days_of_week: list[int] = Field(default_factory=list)  # 1..7
    every_hours: int | None = None


# --- Patient medication / regimen -------------------------------------------


class PatientMedicationDTO(DTO):
    id: UUID
    patient_id: UUID
    display_name: str
    product_id: UUID | None = None
    source_id: UUID | None = None
    identity_status: IdentityStatus = IdentityStatus.UNVERIFIED
    archived_at: datetime | None = None
    demo_only: bool = True


class RegimenDraftInput(DTO):
    """Fields captured during enrollment; anything missing stays pending."""

    medication_name: str
    dose_amount: float | None = None
    dose_unit: str | None = None
    frequency_rule: FrequencyRuleDTO | None = None
    is_prn: bool = False
    route: str | None = None
    food_instruction: str | None = None


class RegimenVersionDTO(DTO):
    id: UUID
    patient_id: UUID
    patient_medication_id: UUID
    source_id: UUID | None
    version_no: int
    state: RegimenState
    dose_amount: float | None
    dose_unit: str | None
    frequency_rule: dict[str, Any] | None
    is_prn: bool
    route: str | None
    food_instruction: str | None
    effective_from: datetime | None
    effective_to: datetime | None
    supersedes_id: UUID | None
    confirmation_challenge_id: UUID | None
    created_at: datetime
    demo_only: bool = True


class MissingInstruction(DTO):
    """Which required instruction is still absent (pending, never inferred)."""

    field: FieldName
    reason: str = "missing"


# --- Dose rules / occurrences / events --------------------------------------


class DoseRuleDTO(DTO):
    id: UUID
    patient_id: UUID
    regimen_id: UUID
    rule_kind: RuleKind
    local_times: list[str] = Field(default_factory=list)
    days_of_week: list[int] = Field(default_factory=list)
    timezone: str = "Asia/Singapore"
    enabled: bool = True


class DoseOccurrenceDTO(DTO):
    id: UUID
    patient_id: UUID
    regimen_id: UUID
    rule_id: UUID
    due_at: datetime
    status: OccurrenceStatus
    generation_key: str


class DoseEventDTO(DTO):
    id: UUID
    patient_id: UUID
    regimen_id: UUID
    occurrence_id: UUID | None
    event_time: datetime
    intake_status: IntakeStatus
    visual_status: VisualStatus = VisualStatus.NOT_CHECKED
    ingestion_proven: bool = False  # ALWAYS False for self reports
    idempotency_key: str
    created_at: datetime


class DoseEventInput(DTO):
    regimen_id: UUID
    occurrence_id: UUID | None = None
    intake_status: IntakeStatus
    event_time: datetime
    idempotency_key: str = Field(min_length=1, max_length=128)


class DoseHistoryEntryDTO(DTO):
    event: DoseEventDTO | None
    occurrence: DoseOccurrenceDTO | None
    regimen_id: UUID
    medication_display_name: str


# --- Agent session / confirmation ------------------------------------------


class AgentSessionDTO(DTO):
    id: UUID
    patient_id: UUID
    intent: str | None
    state: str
    pending_field_names: list[str] = Field(default_factory=list)
    state_version: int = 1
    updated_at: datetime
    expires_at: datetime


class ConfirmationChallengeDTO(DTO):
    id: UUID
    patient_id: UUID
    session_id: UUID
    session_state_version: int
    action: str
    regimen_id: UUID
    occurrence_id: UUID | None
    intended_intake_status: IntakeStatus | None
    idempotency_key: str
    token_hash: str
    issued_at: datetime
    expires_at: datetime
    confirmed_at: datetime | None = None
    consumed_at: datetime | None = None


# --- Tool traces (redacted, allowlist-checked like core_trace_summary_is_safe)


class ToolTraceDTO(DTO):
    id: UUID
    patient_id: UUID
    session_id: UUID
    correlation_id: UUID
    tool_name: str
    tool_status: str
    request_summary: dict[str, Any] = Field(default_factory=dict)
    response_summary: dict[str, Any] = Field(default_factory=dict)
    called_at: datetime
    duration_ms: int | None = None


# --- Service results ---------------------------------------------------------


class EnrollmentResultDTO(DTO):
    medication: PatientMedicationDTO
    regimen: RegimenVersionDTO
    missing_instructions: list[MissingInstruction]
    source_fields: list[SourceFieldDTO]


class ActivationResultDTO(DTO):
    regimen: RegimenVersionDTO
    superseded_regimen_ids: list[UUID] = Field(default_factory=list)


class DueDoseResultDTO(DTO):
    occurrence: DoseOccurrenceDTO | None
    medication_display_name: str
    dose_description: str | None = None
    is_prn: bool = False


class SelfReportResultDTO(DTO):
    event: DoseEventDTO | None  # None when idempotent replay returns existing
    existing_event_id: UUID | None = None
    already_recorded: bool = False
