"""Read-only, session/conversation-bound medication choices. Never write authority."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints


class MedicationOption(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    medication_id: UUID
    regimen_id: UUID
    display_name: str = Field(max_length=200)
    label: str = Field(max_length=300)
    ingredient_names: list[Annotated[str, StringConstraints(max_length=200)]] = Field(
        default_factory=list, max_length=8
    )


class MedicationSelection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    choice_id: UUID
    medication_id: UUID


class MedicationChoice(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: UUID
    question: Literal["general_use", "personal_instructions", "personal_reason"]
    prompt: str = Field(default="", max_length=500)
    target_name: str | None = Field(default=None, max_length=160)
    include_original: bool = False
    expires_at: AwareDatetime
    options: list[MedicationOption] = Field(max_length=10)


class MedicationDialogue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    topic: Literal["medication", "other"] = "medication"
    listed: list[MedicationOption] = Field(default_factory=list, max_length=10)
    choice: MedicationChoice | None = None
    conversation_id: UUID | None = None
    candidate_version: str = Field(default="", max_length=64)
    subject_name: str | None = Field(default=None, max_length=160)
    answered_medication_ids: list[UUID] = Field(default_factory=list, max_length=3)
    history_medication_id: UUID | None = None
