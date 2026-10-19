"""Explicit patient confirmation of reports about existing scheduled occurrences."""

import hashlib
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from .dto import DoseEventDTO

ReportStatus = Literal["reported_taken", "reported_not_taken", "unsure"]
LateReason = Literal["forgot_to_record", "app_unavailable", "unsure_time", "correcting_record", "other"]


class LateReportInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID
    intake_status: ReportStatus
    actual_administration_at: AwareDatetime | None = None
    reason: LateReason
    notes: str = Field(default="", max_length=1000)
    expected_report_id: UUID | None = None

    @model_validator(mode="after")
    def appropriate_time(self):
        if self.actual_administration_at and (
            self.intake_status != "reported_taken" or self.actual_administration_at.microsecond
        ):
            raise ValueError("Actual administration time is only for a taken report and must use whole seconds")
        return self

    def binding_key(self, occurrence_id: UUID) -> str:
        canonical = "\n".join(
            [
                str(occurrence_id),
                str(self.id),
                self.intake_status,
                str(int(self.actual_administration_at.timestamp())) if self.actual_administration_at else "",
                self.reason,
                str(self.expected_report_id or ""),
                self.notes,
            ]
        )
        return f"late:{self.id}:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class LateReportRecord(LateReportInput):
    patient_id: UUID
    occurrence_id: UUID
    regimen_id: UUID
    recorded_at: AwareDatetime
    version: int
    idempotency_key: str
    ingestion_proven: Literal[False] = False
    visual_status: Literal["not_checked"] = "not_checked"


class LateReportRepository(Protocol):
    def original(self, patient_id: UUID, occurrence_id: UUID) -> DoseEventDTO | None: ...
    def history(self, patient_id: UUID, occurrence_id: UUID) -> list[LateReportRecord]: ...
    def save(
        self, patient_id: UUID, occurrence_id: UUID, values: LateReportInput, challenge_id: UUID, now: datetime
    ) -> LateReportRecord: ...


class DoseFollowUp(BaseModel):
    occurrence_id: UUID
    regimen_id: UUID
    medication_id: UUID
    medication_name: str
    strength_text: str | None = None
    form: str | None = None
    version_no: int = 1
    can_report: bool = True
    unavailable_reason: Literal["review_required"] | None = None
    due_at: AwareDatetime
    dose_amount: float | None
    dose_unit: str | None
    report_id: UUID | None = None
    intake_status: str | None = None
    actual_administration_at: AwareDatetime | None = None
    recorded_at: AwareDatetime | None = None
    reason: str | None = None
    notes: str = ""


class LateReportChallenge(BaseModel):
    challenge_id: UUID
    session_id: UUID
    expires_at: AwareDatetime
    occurrence: DoseFollowUp
    proposed: LateReportInput
    timezone: str


class DoseFollowUps(BaseModel):
    items: list[DoseFollowUp]
    has_more: bool
    as_of: AwareDatetime
    timezone: str


class DoseReportAudit(BaseModel):
    original: DoseEventDTO | None
    corrections: list[LateReportRecord]


class LateReportConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge_id: UUID
    report: LateReportInput
