"""Patient UX preferences; language is not a clinical regimen instruction."""

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    conversation_history_enabled: bool = False
    reminders_enabled: bool = True
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
    conversation_history_enabled: bool | None = None
    reminders_enabled: bool | None = None
    reminder_lead_minutes: int | None = Field(default=None, ge=0, le=120)
    timezone: str | None = Field(default=None, max_length=80)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError):
                raise ValueError("Choose a supported IANA timezone") from None
        return value


class PreferenceRepository(Protocol):
    def get(self, patient_id: UUID) -> Preferences: ...
    def save(self, patient_id: UUID, changes: PreferenceUpdate) -> Preferences: ...
