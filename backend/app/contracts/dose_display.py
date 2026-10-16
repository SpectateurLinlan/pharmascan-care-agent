"""Source-backed display arithmetic, never a dose recommendation."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DoseBasis(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    strength_text: str = Field(default="", max_length=100)
    form: Literal["tablet", "capsule", "liquid", "other", "unknown"] = "unknown"
    formulation: Literal["standard", "modified_release", "enteric", "unknown"] = "unknown"
    single_ingredient: bool | None = None
    instructions_text: str = Field(default="", max_length=1000)
    patient_checked: bool = False


class DoseDisplayInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    basis: DoseBasis
    units_per_dose: float = Field(gt=0, le=10000)
    dose_unit: str = Field(min_length=1, max_length=40)


class DoseDisplay(BaseModel):
    status: Literal["calculated", "not_calculated", "conflict"]
    total_amount: float | None = None
    total_unit: Literal["mg"] | None = None
    reason: str
