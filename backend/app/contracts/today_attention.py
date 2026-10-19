from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict


class TodayPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    regimen_id: UUID
    state: Literal["pending", "upcoming", "unrecorded", "recorded", "as_needed", "not_scheduled", "unavailable"]
    next_due_at: AwareDatetime | None = None
    unrecorded_times: list[AwareDatetime]


class TodayAttention(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    as_of: AwareDatetime
    local_date: str
    timezone: str
    plans: list[TodayPlan]
