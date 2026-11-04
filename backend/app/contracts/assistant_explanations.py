"""Content-minimal evidence steps rendered in the patient's language."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ExplanationStep(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    operation_key: str = Field(max_length=100)
    outcome: Literal["success", "partial", "not_found", "not_attempted", "unavailable", "failed", "pending"]
    source_name: str | None = Field(default=None, max_length=160)
    source_refs: tuple[str, ...] = Field(default=(), max_length=10)
    reason_key: str | None = Field(default=None, max_length=100)
    count: int | None = Field(default=None, ge=0)
