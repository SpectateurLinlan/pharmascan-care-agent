"""Reference classes and evidence for deterministic visual eligibility."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ReferenceContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    patient_id: UUID
    medication_id: UUID
    reference_kind: Literal["catalogue_seeded_candidate", "patient_loose_pill", "package"]
    regimen_state: Literal["active", "draft", "pending_clarification", "ended", "superseded"]
    reviewed: bool = False
    product_mapping_confirmed: bool = False
    usage_permitted: bool = False
    model_version: str | None = None
    embedding_space_id: str | None = None
    preprocessing_version: str | None = None
    dimension: int | None = None
    normalized: bool | None = None


class ReferenceEligibility(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    eligible_for_current_match: bool
    can_seed_candidate: bool = False
    reason: str
    proves_identity: Literal[False] = False
    proves_ingestion: Literal[False] = False
