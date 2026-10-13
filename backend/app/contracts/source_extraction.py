"""Read-only source extraction boundary, no regimen writes or dose inference."""

from typing import Literal, Protocol
from uuid import UUID

from app.contracts.vision import VisionDTO
from pydantic import Field


class PrintedEvidence(VisionDTO):
    value: str
    line: str
    presence: Literal["present"] = "present"


class IngredientIdentity(VisionDTO):
    name: str
    rxcui: str | None


class ProductIdentity(VisionDTO):
    name: str
    brand: str | None
    ingredients: list[IngredientIdentity]
    strength: str | None
    rxcui: str | None
    rxnorm_name: str | None
    dose_form: PrintedEvidence | None = None
    source_lines: list[str]
    first_line: int | None = None


class RegimenEvidence(VisionDTO):
    """As printed only; quantity is dispensed amount, never per-dose quantity."""

    directions: PrintedEvidence | None = None
    quantity: PrintedEvidence | None = None
    date: PrintedEvidence | None = None
    expiry_date: PrintedEvidence | None = None
    missing_fields: list[str] = Field(default_factory=list)
    explicit_null_fields: list[str] = Field(default_factory=list)
    dose_amount: None = None
    frequency: None = None
    administration_times: None = None
    duration: None = None


class SourceListComparison(VisionDTO):
    status: Literal["same_medicine", "different_strength", "contains_listed", "not_on_list"]
    medication_id: str | None
    message: str


class ExtractedMedication(VisionDTO):
    product: ProductIdentity
    regimen_evidence: RegimenEvidence
    list_comparison: SourceListComparison | None = None
    review_status: Literal["extracted"] = "extracted"
    can_activate_regimen: Literal[False] = False


class MedicationSourceExtractionDTO(VisionDTO):
    source_document_id: UUID
    source_kind: Literal["package", "pharmacy_label", "prescription"]
    provider_source: Literal["photo", "pdf_text", "pdf_scan"]
    provider: str = "pharmascan:v0.8.0:/v1/read-label"
    extraction_model: str
    candidates: list[ExtractedMedication]
    note: str
    review_required: Literal[True] = True


class SourceExtractionPort(Protocol):
    def extract_medication_source(
        self,
        *,
        source_document_id: UUID,
        source_kind: Literal["package", "pharmacy_label", "prescription"],
        image_bytes: bytes,
    ) -> MedicationSourceExtractionDTO: ...
