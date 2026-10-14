"""Deterministic, explicitly scoped record summaries; no adherence inference."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from .observations import Observation


class SummaryMedication(BaseModel):
    medication_id: UUID
    regimen_id: UUID
    name: str
    version: int
    state: str
    is_prn: bool
    dose_amount: float | None
    dose_unit: str | None
    food_instruction: str | None
    course_start: str | None
    course_end: str | None
    local_times: list[str]
    recorded_occurrences: int
    without_report: int


class ReviewSummary(BaseModel):
    period: Literal["week", "month", "course"]
    window_start: datetime
    window_end: datetime
    generated_at: datetime
    timezone: str
    medications: list[SummaryMedication]
    reported_taken: int
    reported_not_taken: int
    unsure: int
    observations: list[Observation]
    questions: list[str]
    coverage_note: str
