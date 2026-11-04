"""Closed image processing inputs and non-clinical, page-only evidence."""

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from .assistant_workflows import EphemeralPayload, WorkflowDTO


class CompareFields(WorkflowDTO):
    intent: Literal["personal", "identify"] = "personal"
    regimen_id: UUID | None = None
    source_attachment_id: UUID | None = None
    page: int = Field(default=0, strict=True, ge=0, le=100000)

    @model_validator(mode="after")
    def owned_target_only(self):
        if self.intent == "identify" and self.regimen_id is not None:
            raise ValueError("Catalogue checks do not select a personal regimen")
        return self


class CompareQuery(WorkflowDTO):
    expected_revision: int = Field(strict=True, ge=1)
    ephemeral: EphemeralPayload | None = None


class CompareCandidate(WorkflowDTO):
    name: str = Field(min_length=1, max_length=200)
    strength: str | None = Field(default=None, max_length=100)
    market: Literal["US"] = "US"


class ComparisonResult(WorkflowDTO):
    intent: Literal["personal", "identify"]
    decision: Literal["match", "unknown", "ambiguous", "conflict", "missing_reference", "unavailable"]
    reason_key: Literal["visual_reference_only", "no_reviewed_reference", "image_unclear", "plan_conflict",
                        "missing_reference", "service_unavailable"]
    selected_medication: str | None = None
    candidates: tuple[CompareCandidate, ...] = Field(default=(), max_length=10)
    safe_to_take: Literal[False] = False
    ingestion_proven: Literal[False] = False
    count_reliable: Literal[False] = False
