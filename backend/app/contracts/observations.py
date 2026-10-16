"""Patient descriptions are records, never diagnoses or medication instructions."""

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class Measurement(BaseModel):
    kind: Literal["note", "blood_pressure", "blood_glucose", "weight", "sleep", "mood"] = "note"
    value: float | None = Field(default=None, ge=0, le=10000, allow_inf_nan=False)
    secondary_value: float | None = Field(default=None, ge=0, le=10000, allow_inf_nan=False)
    unit: Literal["mmHg", "mmol/L", "mg/dL", "kg", "hours", "score"] | None = None

    @model_validator(mode="after")
    def compatible_measurement(self):
        units = {
            "blood_pressure": {"mmHg"},
            "blood_glucose": {"mmol/L", "mg/dL"},
            "weight": {"kg"},
            "sleep": {"hours"},
            "mood": {"score"},
        }
        if self.kind == "note":
            if any(value is not None for value in (self.value, self.secondary_value, self.unit)):
                raise ValueError("A descriptive note has no numeric measurement")
        elif self.value is None or self.unit not in units[self.kind]:
            raise ValueError("Choose a compatible value and unit")
        if self.kind == "blood_pressure" and self.secondary_value is None:
            raise ValueError("Blood pressure needs both systolic and diastolic values")
        if self.kind != "blood_pressure" and self.secondary_value is not None:
            raise ValueError("Only blood pressure has a second value")
        return self


class ObservationInput(Measurement):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: UUID
    occurred_at: AwareDatetime
    description: str = Field(min_length=1, max_length=1000)
    severity: Literal["mild", "moderate", "severe"] | None = None
    notes: str | None = Field(default=None, max_length=1000)
    medication_id: UUID | None = None
    confirmed: bool = False


class HealthNoteReview(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    description: str = Field(min_length=1, max_length=1000)
    requires_patient_review: Literal[True] = True
    urgent_help_advised: bool = False


class Observation(Measurement):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: UUID
    patient_id: UUID
    occurred_at: AwareDatetime
    description: str
    severity: Literal["mild", "moderate", "severe"] | None = None
    notes: str | None = None
    medication_id: UUID | None = None
    source: Literal["patient_reported"] = "patient_reported"
    created_at: datetime
    updated_at: datetime
    demo_only: Literal[True] = True


class ObservationRepository(Protocol):
    def list(self, patient_id: UUID, start: datetime, end: datetime) -> list[Observation]: ...
    def get(self, patient_id: UUID, observation_id: UUID) -> Observation | None: ...
    def save(self, record: Observation) -> Observation: ...
    def delete(self, patient_id: UUID, observation_id: UUID) -> None: ...
