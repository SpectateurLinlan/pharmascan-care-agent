"""Read-only knowledge boundary. No patient identity crosses the provider port."""

from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeDTO(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class KnowledgeProduct(KnowledgeDTO):
    name: str = Field(min_length=1, max_length=160)
    ingredients: list[str] = Field(default_factory=list, max_length=8)
    form: str | None = None
    route: str | None = None
    strength: str | None = None
    rxcui: str | None = None
    release: Literal["standard", "modified_release", "enteric", "unknown"] = "unknown"


class LabelSection(KnowledgeDTO):
    field: str
    text: str
    truncated: bool = False


class LabelSource(KnowledgeDTO):
    source_name: Literal["openFDA Drug Label / SPL"] = "openFDA Drug Label / SPL"
    market: Literal["US"] = "US"
    set_id: UUID
    label_id: UUID
    version: str
    effective_time: str
    retrieved_at: str
    url: str
    api_url: str
    sections: list[LabelSection]


class KnowledgeResult(KnowledgeDTO):
    status: Literal["matched", "no_reliable_match", "unavailable"]
    reason: str
    match_scope: Literal["US_label_product_family"] = "US_label_product_family"
    candidate_count: int = 0
    sources: list[LabelSource] = Field(default_factory=list)
    use_statement: str | None = None
    use_statement_zh: str | None = None
    translation_status: Literal["controlled_translation", "original_english_only"] = "original_english_only"
    personal_dosing_authority: Literal[False] = False
    regulatory_note: str = (
        "Manufacturer-submitted US SPL data; openFDA does not independently verify label contents. "
        "Not evidence of FDA approval, Singapore registration, personal indication or dosing. "
        "Bounded search and partial excerpts are not a complete medication safety review."
    )


class MedicationKnowledgeProvider(Protocol):
    def lookup(self, product: KnowledgeProduct) -> KnowledgeResult: ...


class ReviewedInstructions(KnowledgeDTO):
    regimen_id: UUID
    version: int
    source_document_id: UUID
    review_status: str
    source_kind: str
    dose_amount: float | None
    dose_unit: str | None
    frequency_rule: dict[str, object] | None
    is_prn: bool
    route: str | None
    food_instruction: str | None
    course_start_date: str | None
    course_end_date: str | None
    original_instructions: str | None
    original_line: str | None
    professional_verification_inferred: Literal[False] = False


class MedicationUnderstanding(KnowledgeDTO):
    question: Literal["general_use", "personal_instructions", "personal_reason"]
    medication_name: str | None
    general_knowledge: KnowledgeResult | None = None
    personal_instructions: ReviewedInstructions | None = None
    personal_indication: None = None
    patient_safe_summary: str
