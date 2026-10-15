"""Private infrastructure projections of retained v0.8/v0.10 schemas.

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
    imprint_check: str | None = None
    imprint_read_for: list[str] = Field(default_factory=list)


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


class QuantityWire(PrintedWire):
    amount: float | None = None
    unit: str | None = None


class CautionWire(PrintedWire):
    kind: Literal["storage", "side_effect", "how_to_take", "warning"] = "warning"


class DoseWire(Wire):
    amount: float
    amount_max: float | None = None
    unit: str | None = None


class InstructionsWire(Wire):
    text: str
    line: str
    dose: DoseWire | None = None
    times_per_day: int | None = None
    every_hours: float | None = None
    as_needed: bool = False
    times_of_day: list[Literal["morning", "afternoon", "evening", "night", "bedtime"]] = Field(default_factory=list)
    food: Literal["before_food", "after_food", "with_food", "with_or_without_food", "empty_stomach"] | None = None
    duration: str | None = None
    max_per_day: str | None = None


class DocumentWire(Wire):
    directions: PrintedWire | None = None
    quantity: QuantityWire | None = None
    dose_form: PrintedWire | None = None
    date: PrintedWire | None = None
    expiry_date: PrintedWire | None = None
    instructions: InstructionsWire | None = None
    indication: PrintedWire | None = None
    cautions: list[CautionWire] = Field(default_factory=list)


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
    release: Literal["ER", "DR"] | None = None
    release_printed: str | None = None


class LabelWire(Wire):
    candidates: list[LabelCandidateWire]
    note: str
    ocr_model: str
    source: Literal["photo", "pdf_text", "pdf_scan"] = "photo"
    label_kind: Literal["dispensing", "package", "none"] | None = None
    dispensed_by: PrintedWire | None = None
    message: str | None = None
