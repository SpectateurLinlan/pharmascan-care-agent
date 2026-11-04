"""Closed reminder read/export fields; no snooze, settings or sender authority."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from .assistant_workflows import WorkflowDTO


class ReminderListFields(WorkflowDTO):
    days: int = Field(default=7, strict=True, ge=1, le=7)
    page: int = Field(default=0, strict=True, ge=0, le=100000)


class CalendarFields(WorkflowDTO):
    range: Literal["30", "90", "remaining", "custom"] = "30"
    start_date: date | None = None
    end_date: date | None = None
    include_medications: bool = Field(default=True, strict=True)
    include_tasks: bool = Field(default=True, strict=True)

    @model_validator(mode="after")
    def bounded_window(self):
        if not self.include_medications and not self.include_tasks:
            raise ValueError("Select at least one calendar content type")
        if self.range == "custom":
            if self.start_date is None or self.end_date is None or self.end_date < self.start_date:
                raise ValueError("Choose paired ordered custom dates")
            if (self.end_date - self.start_date).days > 365:
                raise ValueError("Custom calendar ranges cannot exceed 366 days")
        elif self.start_date is not None or self.end_date is not None:
            raise ValueError("Dates require the custom calendar range")
        return self


class NotificationStatusFields(WorkflowDTO):
    pass


class SnoozeFields(WorkflowDTO):
    occurrence_id: UUID | None = None
    minutes: int | None = Field(default=None, strict=True, ge=1, le=1440)
    previous_remind_at: datetime | None = None
    previous_timezone: str | None = Field(default=None, max_length=80)


class ReminderSettingsFields(WorkflowDTO):
    reminders_enabled: bool | None = Field(default=None, strict=True)
    reminder_lead_minutes: int | None = Field(default=None, strict=True, ge=0, le=120)
    previous_enabled: bool | None = Field(default=None, strict=True)
    previous_lead_minutes: int | None = Field(default=None, strict=True, ge=0, le=120)
    previous_timezone: str | None = Field(default=None, max_length=80)


REMINDER_WRITE_SCHEMAS = {"reminder.snooze": SnoozeFields, "reminder.settings": ReminderSettingsFields}


class NotificationDeviceFields(WorkflowDTO):
    """Device credentials and native IDs belong only to the patient browser/API."""


NOTIFICATION_DEVICE_SCHEMAS = dict.fromkeys(
    ("notification.subscribe", "notification.unsubscribe", "notification.test"), NotificationDeviceFields)


REMINDER_READ_SCHEMAS = {"reminder.list": ReminderListFields, "reminder.calendar.export": CalendarFields,
                        "notification.status": NotificationStatusFields}
