"""Bounded client-relayed image evidence; never patient facts or write authority."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .source_extraction import PrintedInstructions

Line = Annotated[str, Field(max_length=400)]
PHOTO_READ_TOOLS = frozenset(
    {
        "list_active_medications",
        "check_due_dose",
        "get_dose_status",
        "get_medication_history",
        "get_medication_understanding",
        "get_medication_inventory",
        "get_adherence_history",
        "get_unresolved_follow_ups",
        "get_longitudinal_summary",
    }
)


class PhotoProduct(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(max_length=200)
    strength: str | None = Field(default=None, max_length=200)
    printed_lines: list[Line] = Field(default_factory=list, max_length=4)
    printed_directions: str | None = Field(default=None, max_length=1000)
    printed_indication: Line | None = None
    printed_cautions: list[Line] = Field(default_factory=list, max_length=5)
    instructions: PrintedInstructions | None = None


class PhotoCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    display_name: str | None = Field(default=None, max_length=200)
    strength: str | None = Field(default=None, max_length=200)
    external_catalogue_id: str = Field(max_length=200)
    market: Literal["US"] = "US"
    visual_similarity: float | None = Field(default=None, allow_inf_nan=False)


class PhotoVisual(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    decision: Literal["unknown", "ambiguous", "unavailable"]
    reason: str = Field(max_length=1000)
    candidates: list[PhotoCandidate] = Field(default_factory=list, max_length=5)
    count_reliable: bool
    ingestion_proven: Literal[False] = False
    safe_to_take_confirmed: Literal[False] = False


class ChatPhotoContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    image_type: Literal["loose_pills", "blister", "package", "printed", "document", "unchecked"]
    workflow: Literal["pill_evidence", "source_review", "ask_patient"]
    checked: bool
    abstained: bool
    source_kind: Literal["package", "pharmacy_label", "prescription"]
    provider: str | None = Field(default=None, max_length=200)
    extraction_model: str | None = Field(default=None, max_length=200)
    products: list[PhotoProduct] = Field(default_factory=list, max_length=5)
    visual: PhotoVisual | None = None

    @model_validator(mode="after")
    def bounded_evidence(self) -> "ChatPhotoContext":
        if len(self.model_dump_json()) > 24_000:
            raise ValueError("Photo evidence exceeds the conversation limit")
        return self

    def model_context(self) -> dict[str, object]:
        return {
            "origin": "client_relayed_unverified",
            "is_patient_statement": False,
            "may_authorize_writes": False,
            "evidence": self.model_dump(mode="json"),
        }

    def caption(self, language: str) -> str:
        return "已发送照片" if language == "zh" else "Photo attached"

    def patient_summary(self, language: str) -> str:
        names = [" · ".join(filter(None, [item.name, item.strength])) for item in self.products]
        if self.visual:
            names = [" · ".join(filter(None, [item.display_name, item.strength])) for item in self.visual.candidates]
        if language == "zh":
            return ("照片中的待核对信息：" + "；".join(names) + "。" if names else "这张照片还需要补充信息。") + (
                "这些是未经确认的图像线索，不是您已核对的用药计划。请对照原始标签，告诉我您想进一步核对什么。"
            )
        return (
            "Unconfirmed information from the photo: " + "; ".join(names) + ". "
            if names
            else "This photo needs more information. "
        ) + (
            "These are image clues, not your reviewed medication plan. "
            "Check the original label and tell me which detail you would like to review."
        )
