"""Reminder projections never materialize occurrences or invoke device permissions."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from ...contracts.assistant_workflows import ChoiceAction, ChoiceOption, DownloadAction, OperationResult, Preparation
from ...contracts.reminder_workflow import CalendarFields, NotificationStatusFields, ReminderListFields
from ...domain.errors import ValidationError


class ReminderReadAdapter:
    capability_ids = frozenset({"reminder.list", "reminder.calendar.export", "notification.status"})

    def __init__(self, *, enrollment, schedule, reminders, plan, care, preferences, clock):
        self.enrollment, self.schedule, self.reminders, self.plan = enrollment, schedule, reminders, plan
        self.care, self.preferences, self.clock = care, preferences, clock

    def prepare(self, context, values, assets, results=()):
        if assets or results or context.capability_id not in self.capability_ids:
            raise ValidationError("Use the selected read-only reminder query")
        inputs = values.model_dump(mode="json", exclude_none=True)
        if isinstance(values, CalendarFields):
            return Preparation(input_fields=inputs, workflow_state="ready_for_review",
                               prompt_key="assistant.reminder.calendar", actions=(
                                   DownloadAction(capability_id="reminder.calendar.export"),
                               ))
        if isinstance(values, NotificationStatusFields):
            return Preparation(input_fields=inputs, prompt_key="assistant.reminder.device")
        if not isinstance(values, ReminderListFields):
            raise ValidationError("Use typed reminder query fields")
        preference = self.preferences.get(context.owner)
        now = self.clock.now()
        zone = ZoneInfo(preference.timezone)
        today = now.astimezone(zone).date()
        end = today + timedelta(days=values.days - 1)
        rows = self.plan.calendar_export_rows(context.owner, lead_minutes=preference.reminder_lead_minutes,
                    start_date=today, end_date=end)[0] if preference.reminders_enabled else []
        pages = max(1, (len(rows) + 9) // 10)
        page = values.page if values.page < pages else 0
        medication_fields = {"occurrence_id", "medication_name", "due_at", "remind_at"}
        medications = [{**row.model_dump(mode="json", include=medication_fields),
                        "projected_only": self.schedule.get_occurrence(context.owner, row.occurrence_id) is None}
                       for row in rows[page * 10:(page + 1) * 10]]
        upper = datetime.combine(end + timedelta(days=1), time.min, tzinfo=zone).astimezone(UTC)
        tasks = [row for row in self.care.actionable_tasks(context.owner, preference.timezone)
                 if now <= row.due_at < upper and (row.reminder_minutes is not None or row.reminder_offsets)] \
            if self.care else []
        return Preparation(input_fields=inputs, prompt_key="assistant.reminder.read", view_fields={
            "timezone": preference.timezone, "reminders_enabled": preference.reminders_enabled,
            "lead_minutes": preference.reminder_lead_minutes, "days": values.days, "page": page, "page_count": pages,
            "medications": medications, "medication_count": len(rows), "care_task_count": len(tasks),
            "care_tasks": [row.model_dump(mode="json", include={"id", "title", "due_at", "reminder_minutes",
                                                                    "reminder_offsets"}) for row in tasks[:10]],
            "snoozes": [row.model_dump(mode="json", include={"occurrence_id", "remind_at", "is_due"})
                        for row in self.reminders.list_current(context.owner)[:10]],
        }, actions=(ChoiceAction(action_id="reminder.days", options=tuple(
            ChoiceOption(value=str(days), label_key=f"assistant.reminder.days{days}") for days in (1, 3, 7)
        )),))

    def observe(self, context, result_ref):
        return OperationResult(state="failed", reason="reminder_reads_do_not_create_business_results")
