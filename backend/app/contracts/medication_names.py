"""Name suggestions are not verified patient medication identities."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class NameQuery(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    text: str = Field(min_length=1, max_length=160)
    purpose: Literal["general_use", "patient_product"]


class NameCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str = Field(max_length=200)
    canonical_name: str = Field(max_length=160)
    display_name: str = Field(max_length=200)
    source_refs: tuple[str, ...] = Field(default=(), max_length=5)
    medication_id: UUID | None = None
    strength: str | None = None
    form: str | None = None
    release: str | None = None


class NameResolution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    status: Literal["resolved", "needs_confirmation", "ambiguous", "not_found", "unavailable"]
    original: str
    canonical_name: str | None = None
    candidates: tuple[NameCandidate, ...] = Field(default=(), max_length=5)


class NameChoice(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: UUID
    version: int = Field(default=1, ge=1)
    original: str = Field(max_length=160)
    question: Literal["general_use"] = "general_use"
    expires_at: datetime
    options: tuple[NameCandidate, ...] = Field(min_length=1, max_length=5)


class NameSelection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    choice_id: UUID
    candidate_id: str = Field(min_length=1, max_length=200)
    expected_version: int = Field(ge=1)
