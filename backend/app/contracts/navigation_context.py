"""Navigation is a scoped record reference, never a medical conclusion."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class NavigationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: Literal["medicines", "medicine-detail", "records"]
    medication_id: UUID | None = None
    regimen_id: UUID | None = None


class NavigationContext(NavigationInput):
    display_name: str | None = None
