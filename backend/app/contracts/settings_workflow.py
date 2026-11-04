"""Closed preference/contact drafts; account secrets never belong to a workflow."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from .assistant_workflows import WorkflowDTO
from .caregivers import CaregiverDetails
from .preferences import PreferenceUpdate


class PreferenceSnapshot(PreferenceUpdate):
    speech_locale: Literal["en-SG", "zh-CN"] | None = None


class PreferenceDraft(WorkflowDTO):
    previous: PreferenceSnapshot | None = None


class LanguageFields(PreferenceDraft):
    preferred_language: Literal["en", "zh"] | None = None


class TextFields(PreferenceDraft):
    text_scale_percent: int | None = Field(default=None, strict=True, ge=100, le=150)
    text_size: Literal["standard", "large"] | None = None


class VoiceFields(PreferenceDraft):
    voice_enabled: bool | None = Field(default=None, strict=True)
    tts_autoplay: bool | None = Field(default=None, strict=True)


class ReminderPreferenceFields(PreferenceDraft):
    reminders_enabled: bool | None = Field(default=None, strict=True)
    reminder_lead_minutes: int | None = Field(default=None, strict=True, ge=0, le=120)


class PrivacyFields(PreferenceDraft):
    conversation_history_enabled: bool | None = Field(default=None, strict=True)


class TimezoneFields(PreferenceDraft):
    timezone: str | None = Field(default=None, max_length=80)

    @field_validator("timezone")
    @classmethod
    def native_timezone(cls, value):
        return PreferenceUpdate(timezone=value).timezone


class ProfileFields(PreferenceDraft):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)


class EmptySettingsFields(WorkflowDTO):
    pass


class ContactTargetFields(WorkflowDTO):
    contact_id: UUID | None = None
    previous: CaregiverDetails | None = None
    previous_updated_at: datetime | None = None


class ContactFields(ContactTargetFields):
    name: str | None = Field(default=None, max_length=80)
    relationship: str | None = Field(default=None, max_length=80)
    contact_type: Literal["email", "phone"] | None = None
    contact_value: str | None = Field(default=None, max_length=254)
    storage_consent: bool | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def consent_before_persistence(self):
        if any(getattr(self, key) is not None for key in ("name", "relationship", "contact_type", "contact_value")):
            if self.storage_consent is not True:
                raise ValueError("Confirm storage permission before submitting contact details")
        return self


PREFERENCE_SCHEMAS = {"preference.language": LanguageFields, "preference.text": TextFields,
    "preference.voice": VoiceFields, "preference.reminder": ReminderPreferenceFields,
    "preference.privacy": PrivacyFields, "preference.timezone": TimezoneFields,
    "profile.edit": ProfileFields, "profile.view": EmptySettingsFields}
CONTACT_SCHEMAS = {"caregiver.add": ContactFields, "caregiver.edit": ContactFields,
                   "caregiver.delete": ContactTargetFields, "caregiver.list": EmptySettingsFields}
ACCOUNT_SCHEMAS = dict.fromkeys(
    ("account.status", "account.login", "account.link", "account.password", "account.signout"), EmptySettingsFields)
