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
    release: Literal["ER", "DR"] | None = None
    release_printed: str | None = None


class PrintedDose(VisionDTO):
    amount: float
    amount_max: float | None = None
    unit: str | None = None


class PrintedInstructions(VisionDTO):
    """Untrusted parsed parts sharing the original instruction text and line."""

    text: str
    line: str
    dose: PrintedDose | None = None
    times_per_day: int | None = None
    every_hours: float | None = None
    as_needed: bool = False
    times_of_day: list[Literal["morning", "afternoon", "evening", "night", "bedtime"]] = Field(default_factory=list)
    food: Literal["before_food", "after_food", "with_food", "with_or_without_food", "empty_stomach"] | None = None
    duration: str | None = None
    max_per_day: str | None = None


class DispensedQuantity(PrintedEvidence):
    amount: float | None = None
    unit: str | None = None


class PrintedCaution(PrintedEvidence):
    kind: Literal["storage", "side_effect", "how_to_take", "warning"] = "warning"


class RegimenEvidence(VisionDTO):
    """As printed only; quantity is dispensed amount, never per-dose quantity."""

    directions: PrintedEvidence | None = None
    quantity: PrintedEvidence | None = None
    date: PrintedEvidence | None = None
    expiry_date: PrintedEvidence | None = None
    instructions: PrintedInstructions | None = None
    indication: PrintedEvidence | None = None
    cautions: list[PrintedCaution] = Field(default_factory=list)
    supplied_quantity: DispensedQuantity | None = None
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


class ListedMedication(VisionDTO):
    id: str
    name: str
    strength: str | None = None
    rxcui: str | None = None


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
    label_kind: Literal["dispensing", "package", "none"] | None = None
    dispensed_by: PrintedEvidence | None = None
    message: str | None = None


class SourceExtractionPort(Protocol):
    def extract_medication_source(
        self,
        *,
        source_document_id: UUID,
        source_kind: Literal["package", "pharmacy_label", "prescription"],
        image_bytes: bytes,
        medications: tuple[ListedMedication, ...] = (),
    ) -> MedicationSourceExtractionDTO: ...


class ImageRoute(VisionDTO):
    image_type: Literal["loose_pills", "blister", "package", "printed", "document", "unchecked"]
    checked: bool
    abstained: bool
    suggested_workflow: Literal["pill_evidence", "source_review", "ask_patient"]
    message: str


class ImageRoutingPort(Protocol):
    def route_image(self, image: bytes) -> ImageRoute: ...
