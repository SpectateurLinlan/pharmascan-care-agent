"""Patient descriptions are records, never diagnoses or medication instructions."""

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class ObservationInput(BaseModel):
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


class Observation(BaseModel):
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
