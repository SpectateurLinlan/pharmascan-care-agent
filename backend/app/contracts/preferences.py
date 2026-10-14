"""Patient UX preferences; language is not a clinical regimen instruction."""

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Preferences(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)
    patient_id: UUID
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    preferred_language: Literal["en", "zh"] = "en"
    speech_locale: Literal["en-SG", "zh-CN"] = "en-SG"
    text_size: Literal["standard", "large"] = "standard"
    text_scale_percent: int = Field(default=100, ge=100, le=150, strict=True)
    voice_enabled: bool = True
    tts_autoplay: bool = False
    reminder_lead_minutes: int = Field(default=0, ge=0, le=120)
    timezone: str = "Asia/Singapore"
    created_at: datetime
    updated_at: datetime


class PreferenceUpdate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    preferred_language: Literal["en", "zh"] | None = None
    text_size: Literal["standard", "large"] | None = None
    text_scale_percent: int | None = Field(default=None, ge=100, le=150, strict=True)
    voice_enabled: bool | None = None
    tts_autoplay: bool | None = None
    reminder_lead_minutes: int | None = Field(default=None, ge=0, le=120)
    # Current demo scheduling supports Singapore. No silent timezone change.
    timezone: Literal["Asia/Singapore"] | None = None


class PreferenceRepository(Protocol):
    def get(self, patient_id: UUID) -> Preferences: ...
    def save(self, patient_id: UUID, changes: PreferenceUpdate) -> Preferences: ...
