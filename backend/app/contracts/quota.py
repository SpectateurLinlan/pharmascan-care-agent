"""Atomic success accounting with hidden per-turn reservation capability."""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Usage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    patient_id: UUID
    usage_date: date
    llm_user_turns: int = Field(ge=0)
    model_requests: int = Field(ge=0)
    limit: int = Field(ge=1)
    next_reset_at: datetime


@dataclass(frozen=True)
class Reservation:
    state: Literal["reserved", "pending", "completed", "exhausted", "busy"]
    usage: Usage
    turn_key: str
    nonce: str = field(repr=False)


class QuotaRepository(Protocol):
    def usage(self, patient_id: UUID) -> Usage: ...
    def reserve(self, patient_id: UUID, turn_key: str) -> Reservation: ...
    def model_request(self, patient_id: UUID, reservation: Reservation) -> None: ...
    def finish(self, patient_id: UUID, reservation: Reservation, success: bool) -> Usage: ...
