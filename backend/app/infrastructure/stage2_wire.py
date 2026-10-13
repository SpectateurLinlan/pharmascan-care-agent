"""Private-to-infrastructure projections of frozen v0.8.0 schemas.

Full OpenAPI validation precedes projection. Extra fields are ignored here and
never cross into application DTOs. This is not a second OCR/model implementation.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Wire(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, allow_inf_nan=False)


class ModelInfoWire(Wire):
    api_version: str
    model_version: str = Field(min_length=1)
    embedding_space_id: str = Field(min_length=1)
    preprocess_version: str = Field(min_length=1)
    embedding_dim: int
    normalized: bool
    crop_window: float
    threshold: float
    margin: float
    calibration: dict
    training_coverage: str
    known_limits: list[str]


class EmbeddingWire(Wire):
    embedding: list[float]
    dim: int
    model_version: str = Field(min_length=1)
    embedding_space_id: str = Field(min_length=1)
    preprocess_version: str = Field(min_length=1)
    normalized: bool
    imprint_reads: list[str] | None = None
    text_reading: Literal["used", "not_requested", "unavailable", "skipped"] = "not_requested"


class RefWire(Wire):
    medication_id: str
    name: str
    similarity: float


class MatchItemWire(Wire):
    decision: Literal["match", "unknown", "ambiguous"]
    medication_id: str | None
    similarity: float
    closest: RefWire
    runner_up: RefWire | None


class MatchWire(Wire):
    results: list[MatchItemWire]
    model_version: str
    embedding_space_id: str
    threshold: float
    margin: float
    limits: str


class InputCheckWire(Wire):
    type: str
    checked: bool
    abstained: bool


class DetectionWire(Wire):
    boxes: list[list[float]]
    box_flags: list[list[str]]
    pill_count: int
    count_reliable: bool
    flags: list[str]
    found_by: str
    input_check: InputCheckWire | None = None


class ScanWire(Wire):
    detection: DetectionWire
    model_version: str
    limits: str
    input_check: InputCheckWire | None = None
    text_reading: Literal["used", "not_requested", "unavailable", "skipped"] = "not_requested"
    # ScanPill's decision/identify additions are untyped in OpenAPI. Do NOT map them.


class CandidateWire(Wire):
    pill_id: str = Field(min_length=1)
    name: str | None
    brand: str | None = None
    strength: str | None = None
    dose_form: str | None = None
    rxcui: str | None = None
    ingredients: list[str]
    similarity: float
    market: Literal["US"] = "US"


class IdentifyWire(Wire):
    candidates: list[CandidateWire]
    model_version: str
    limits: str
    input_check: InputCheckWire | None = None


class PrintedWire(Wire):
    value: str
    line: str


class DocumentWire(Wire):
    directions: PrintedWire | None = None
    quantity: PrintedWire | None = None
    dose_form: PrintedWire | None = None
    date: PrintedWire | None = None
    expiry_date: PrintedWire | None = None


class IngredientWire(Wire):
    rxcui: str | None
    name: str


class ListCheckWire(Wire):
    status: Literal["same_medicine", "different_strength", "contains_listed", "not_on_list"]
    medication_id: str | None
    message: str


class LabelCandidateWire(Wire):
    name: str
    brand: str | None
    ingredients: list[IngredientWire]
    strength: str | None
    rxcui: str | None
    rxnorm_name: str | None
    found_in: list[str]
    first_line: int | None = None
    fields: DocumentWire | None = None
    list_check: ListCheckWire | None = None


class LabelWire(Wire):
    candidates: list[LabelCandidateWire]
    note: str
    ocr_model: str
    source: Literal["photo", "pdf_text", "pdf_scan"] = "photo"
