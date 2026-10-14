"""Private patient-entered contacts, without caregiver identity or delivery authority."""

import re
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CaregiverDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    relationship: str | None = Field(default=None, max_length=80)
    contact_type: Literal["email", "phone"]
    contact_value: str = Field(min_length=3, max_length=254)
    storage_consent: Literal[True]

    @model_validator(mode="before")
    @classmethod
    def normalise_contact(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        if data.get("storage_consent") is not True:
            raise ValueError("Confirm permission to store this contact.")
        value = data.get("contact_value")
        if not isinstance(value, str):
            return data
        value = value.strip()
        if data.get("contact_type") == "email":
            if not value.isascii() or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
                raise ValueError("Enter a valid email address.")
            value = value.lower()
        elif data.get("contact_type") == "phone":
            value = re.sub(r"[ ()-]", "", value)
            if not re.fullmatch(r"\+[1-9][0-9]{7,14}", value):
                raise ValueError("Enter a phone number with its country code.")
        relationship = data.get("relationship")
        return {
            **data,
            "contact_value": value,
            "relationship": None if isinstance(relationship, str) and not relationship.strip() else relationship,
        }


class CaregiverCreate(CaregiverDetails):
    id: UUID


class CaregiverContact(CaregiverCreate):
    patient_id: UUID
    verification_status: Literal["pending"] = "pending"
    notifications_enabled: Literal[False] = False
    sharing_enabled: Literal[False] = False
    created_at: datetime
    updated_at: datetime
    demo_only: Literal[True] = True


class CaregiverRepository(Protocol):
    def list(self, patient_id: UUID) -> list[CaregiverContact]: ...
    def get(self, patient_id: UUID, contact_id: UUID) -> CaregiverContact | None: ...
    def create(self, row: CaregiverContact) -> CaregiverContact: ...
    def update(self, row: CaregiverContact) -> CaregiverContact: ...
    def delete(self, patient_id: UUID, contact_id: UUID) -> None: ...
