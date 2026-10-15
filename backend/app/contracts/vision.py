"""Public application DTOs. No external JSON objects, clients or ORM entities."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

MatchDecision = Literal["match", "unknown", "ambiguous", "unavailable", "unsupported"]
TextReading = Literal["used", "not_requested", "unavailable", "skipped"]


class VisionDTO(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class ModelMetadata(VisionDTO):
    api_version: str
    model_version: str
    embedding_space_id: str
    preprocessing_version: str
    dimension: int
    normalized: bool
    crop_window: float
    threshold: float
    margin: float
    calibration_json: str  # Opaque provider declaration, NOT validated performance.
    training_coverage: str
    known_limits: list[str]
    evidence: Literal["visual"] = "visual"


class EmbeddingResult(VisionDTO):
    embedding: list[float]
    dimension: int
    embedding_space_id: str
    model_version: str
    preprocessing_version: str
    normalized: bool
    imprint_reads: list[str] | None = None
    text_reading: TextReading = "not_requested"
    provider_request_id: str | None = None


class GalleryReference(VisionDTO):
    medication_id: str
    name: str | None = None
    embeddings: list[list[float]]
    embedding_space_id: str
    model_version: str
    preprocessing_version: str
    imprint: str | None = None


class ReferenceSimilarity(VisionDTO):
    medication_id: str
    name: str
    score: float  # Visual cosine similarity, NOT probability.


class MatchOutcome(VisionDTO):
    decision: MatchDecision
    medication_id: str | None = None
    score: float | None = None
    threshold: float | None = None
    margin: float | None = None  # Provider operating margin, NOT measured score gap.
    closest: ReferenceSimilarity | None = None
    runner_up: ReferenceSimilarity | None = None
    threshold_version: str | None = None  # No such field in v0.8.0; never fabricated.
    model_version: str | None = None
    embedding_space_id: str | None = None
    evidence: Literal["visual"] = "visual"
    limits: str | None = None
    quality_flags: list[str] = Field(default_factory=list)
    provenance: list[str] = Field(default_factory=list)
    imprint_check: str | None = None
    imprint_read_for: list[str] = Field(default_factory=list)


class ScanBox(VisionDTO):
    """Pixel geometry, NOT normalized coordinates. None means unknown geometry."""

    x: float | None = None
    y: float | None = None
    w: float | None = None
    h: float | None = None
    score: float | None = None  # v0.8.0 detection has no per-box score.


class ScanDiagnostics(VisionDTO):
    pill_count: int
    boxes: list[ScanBox] = Field(default_factory=list)
    box_flags: list[list[str]] = Field(default_factory=list)
    provider_count_reliable: bool = False
    flags: list[str] = Field(default_factory=list)
    found_by: str | None = None
    duplicate_boxes: bool = False
    overlapping_boxes: bool = False
    usable_for_dose_count: bool = False  # App independently keeps automatic counts disabled.
    input_abstained: bool = False
    text_reading: TextReading = "not_requested"
    raw_decision: str | None = None
    model_version: str | None = None
    evidence: Literal["visual"] = "visual"
    limits: str | None = None


class PillCandidate(VisionDTO):
    external_catalogue_id: str
    display_name: str | None = None
    brand: str | None = None
    strength: str | None = None
    form: str | None = None
    market: Literal["US"] = "US"
    visual_similarity: float | None = None
    source_dataset: str | None = None
    rxcui: str | None = None
    ingredients: list[str] = Field(default_factory=list)
    model_version: str | None = None
    limits: str | None = None


class VisionPort(Protocol):
    """Provider errors are explicit typed failures, never fabricated match success."""

    def model_info(self) -> ModelMetadata: ...
    def embed(self, *, image_bytes: bytes, modality: Literal["loose_pill"]) -> EmbeddingResult: ...
    def match(self, *, queries: list[EmbeddingResult], gallery: list[GalleryReference]) -> MatchOutcome: ...
    def scan_diagnostics(self, *, image_bytes: bytes) -> ScanDiagnostics: ...
    def detect(self, *, image_bytes: bytes) -> ScanDiagnostics: ...
    def identify_candidates(self, *, image_bytes: bytes, top_k: int = 5) -> list[PillCandidate]: ...


class VisionError(Exception):
    """Explicit failure across the public Port, safe for application mapping."""


class VisionUnavailable(VisionError):
    """Timeout/network/5xx. NEVER equivalent to unknown medicine."""


class VisionSchemaError(VisionError):
    """Invalid/untrusted response or local input."""


class VisionRequestError(VisionError):
    """HTTP 4xx; no automatic retry. Does not expose raw provider detail."""

    def __init__(self, status_code: int, code: str) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(f"Stage2 request rejected: HTTP {status_code} ({code})")


class ModelVersionMismatch(VisionError):
    """Embedding/model/preprocessing drift; comparisons must fail closed."""


class UnsupportedModality(VisionError):
    """A package/blister is not input for the loose-pill encoder."""


class EmbeddingSpace:
    def __init__(self, space_id: str, model_version: str, dimension: int) -> None:
        self.space_id = space_id
        self.model_version = model_version
        self.dimension = dimension

    def assert_compatible(self, *, space_id: str, model_version: str, dimension: int) -> None:
        if (space_id, model_version, dimension) != (self.space_id, self.model_version, self.dimension):
            raise ModelVersionMismatch("Embedding model, space or dimension mismatch")
