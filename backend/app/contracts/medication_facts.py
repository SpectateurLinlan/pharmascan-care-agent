"""Quoted, scoped use evidence; never product verification or dosing authority."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FactDTO(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class UseLabelEvidence(FactDTO):
    source_id: str
    names: tuple[str, ...]
    ingredient_set: tuple[str, ...]
    route_scope: str | None = None
    formulation_scope: str | None = None
    release_scope: str | None = None
    sections: dict[str, str]


class UseFact(FactDTO):
    source_id: str
    ingredient_set: tuple[str, ...]
    route_scope: str | None = None
    formulation_scope: str | None = None
    release_scope: str | None = None
    population_scope: str | None = None
    polarity: Literal["affirmed", "denied"]
    claim_key: str | None = None
    quote: str = Field(min_length=1, max_length=600)
    field: Literal["indications_and_usage", "purpose"]


class FactCoverage(FactDTO):
    groups: tuple[tuple[str, ...], ...] = ()
    supported: tuple[UseFact, ...] = ()
    withheld: tuple[UseFact, ...] = ()
    reason: str
    reports_same_scope_conflict: bool = False
