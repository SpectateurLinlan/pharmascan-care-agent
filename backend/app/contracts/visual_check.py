"""Normalized visual evidence, never clinical authorization."""

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from .vision import ModelMetadata, PillCandidate, ScanDiagnostics


class VisualEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    model: ModelMetadata
    detection: ScanDiagnostics
    candidates: list[PillCandidate]


class VisualEvidencePort(Protocol):
    def inspect(self, image: bytes) -> VisualEvidence: ...


class VisualCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    decision: Literal["unknown", "ambiguous", "unavailable"]
    selected_medication: str | None
    comparison_available: Literal[False] = False
    reason: str
    candidates: list[PillCandidate]
    count_reliable: bool
    ingestion_proven: Literal[False] = False
    safe_to_take_confirmed: Literal[False] = False
    next_action: str = "Review your recorded instructions and packaging; ask a pharmacist if unsure."


class VisualCheckRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    regimen_id: str | None = None
    requires_image: Literal[True] = True
    visual_status: Literal["not_checked"] = "not_checked"
