"""Vision adapter contracts: internal DTOs + Port.

These mirror `docs/API_CONTRACTS.md` section B, NOT the raw external JSON.
The external schema (OpenAPI v0.4.0) is an older documented contract and may
change; mapping happens only inside `stage2_adapter.py`.

** SIMULATED / UNFROZEN ** — every provider here is either an explicit fake
or an HTTP adapter whose live behavior is still BLOCKED (B01). No test in
this repository may claim a real Stage2 result.
"""

from __future__ import annotations

from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

MatchDecision = Literal["match", "unknown", "ambiguous", "unavailable", "unsupported"]


class VisionDTO(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EmbeddingResult(VisionDTO):
    """256-d vector is expected ONLY if the live API confirms it."""

    embedding: list[float]
    dimension: int
    embedding_space_id: str
    model_version: str
    normalized: bool | None = None
    provider_request_id: str | None = None


class GalleryReference(VisionDTO):
    medication_id: str
    name: str | None = None
    embeddings: list[list[float]]
    embedding_space_id: str


class MatchOutcome(VisionDTO):
    """NOTE: the v0.4.0 API returns a decision only — no similarity score.

    `score` therefore stays ``None`` unless a future contract exposes it, and
    it is *visual similarity*, never a probability or an identity confidence.
    """

    decision: MatchDecision
    medication_id: str | None = None
    score: float | None = None
    margin: float | None = None
    threshold_version: str | None = None
    model_version: str | None = None
    quality_flags: list[str] = Field(default_factory=list)
    provenance: list[str] = Field(default_factory=list)


class ScanBox(VisionDTO):
    """One detected box; x/y/w/h are normalised 0..1 when known."""

    x: float | None = None
    y: float | None = None
    w: float | None = None
    h: float | None = None
    score: float | None = None


class ScanDiagnostics(VisionDTO):
    """`/scan` is diagnostics-only until the duplicate-box bug is fixed.

    ``duplicate_boxes`` and ``overlapping_boxes`` are *measured* flags derived
    from the returned boxes, not invented annotations.
    """

    pill_count: int
    boxes: list[ScanBox] = Field(default_factory=list)
    duplicate_boxes: bool = False
    overlapping_boxes: bool = False
    usable_for_dose_count: bool = False
    raw_decision: str | None = None
    model_version: str | None = None


class PillCandidate(VisionDTO):
    """A /v1/identify candidate — a visual possibility, never an identity."""

    external_catalogue_id: str
    display_name: str | None = None
    brand: str | None = None
    strength: str | None = None
    form: str | None = None
    market: str = "US"
    visual_similarity: float | None = None
    source_dataset: str | None = None


class VisionPort(Protocol):
    """Public boundary used by the agent's vision tools.

    Implementations must never raise a bare provider exception across this
    boundary; they return explicit unavailable/unsupported outcomes instead.
    """

    def embed(self, *, image_bytes: bytes, modality: Literal["loose_pill"]) -> EmbeddingResult: ...

    def match(
        self, *, queries: list[list[float]], gallery: list[GalleryReference]
    ) -> MatchOutcome: ...

    def scan_diagnostics(self, *, image_bytes: bytes) -> ScanDiagnostics: ...

    def identify_candidates(
        self, *, image_bytes: bytes, top_k: int = 5
    ) -> list[PillCandidate]: ...


class VisionError(Exception):
    """Base for adapter-level failures mapped to explicit error states."""


class VisionUnavailable(VisionError):
    """Provider unreachable / timeout / 5xx. NEVER mapped to 'unmatched'."""


class VisionSchemaError(VisionError):
    """Provider returned a payload we cannot trust."""


class ModelVersionMismatch(VisionError):
    """Query embeddings were produced by a different embedding space."""


class UnsupportedModality(VisionError):
    """Requested input (e.g. blister/box for loose-pill space) is not allowed."""


class EmbeddingSpace:
    """Version guard for cosine comparisons (ARCHITECTURE trust boundary 7)."""

    def __init__(self, space_id: str, model_version: str, dimension: int) -> None:
        self.space_id = space_id
        self.model_version = model_version
        self.dimension = dimension

    def assert_compatible(self, *, space_id: str, model_version: str, dimension: int) -> None:
        if space_id != self.space_id or model_version != self.model_version:
            raise ModelVersionMismatch(
                f"embedding space mismatch: query={space_id}/{model_version} "
                f"expected={self.space_id}/{self.model_version}"
            )
        if dimension != self.dimension:
            raise ModelVersionMismatch(
                f"embedding dimension mismatch: got {dimension}, expected {self.dimension}"
            )
