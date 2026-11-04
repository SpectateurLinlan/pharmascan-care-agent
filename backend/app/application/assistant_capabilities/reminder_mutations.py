"""Prepare reminder drafts; only the independent native patient APIs may save."""

from collections.abc import Callable
from datetime import timedelta
from typing import TypeVar
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from ...contracts.assistant_workflows import (
    ActionRepository,
    AttachmentRef,
    BusinessRef,
    ChoiceAction,
    ChoiceOption,
    ExistingReviewAction,
    OperationResult,
    Preparation,
    WorkflowContext,
)
from ...contracts.enums import OccurrenceStatus, RegimenState
from ...contracts.medication_management import ClinicalMutationGuard
from ...contracts.ports import Clock
from ...contracts.reminder_workflow import REMINDER_WRITE_SCHEMAS, ReminderSettingsFields, SnoozeFields
from ...domain.errors import NotFoundError, StaleVersionError, ValidationError
from ..dosing import DoseScheduleService
from ..enrollment import MedicationEnrollmentService
from ..preferences import PreferenceService
from ..reminders import ReminderService

T = TypeVar("T")
ReminderFields = SnoozeFields | ReminderSettingsFields


class ReminderMutationAdapter:
    capability_ids = frozenset(REMINDER_WRITE_SCHEMAS)

    def __init__(self, *, enrollment: MedicationEnrollmentService, schedule: DoseScheduleService,
                 reminders: ReminderService, preferences: PreferenceService, clock: Clock,
                 actions: ActionRepository, clinical: ClinicalMutationGuard):
        self.enrollment, self.schedule, self.reminders = enrollment, schedule, reminders
        self.preferences, self.clock, self.actions, self.clinical = preferences, clock, actions, clinical

    def _receipt(self, context, ref, suffix=None):
        try:
            row = self.actions.read(context.owner, uuid5(ref.id, suffix) if suffix else ref.id)
        except NotFoundError:
            if suffix:
                return None
            raise
        if (row.owner != context.owner or row.task_id != context.task_id
                or row.capability_id != context.capability_id or row.binding_revision > context.revision):
            raise StaleVersionError("This reminder review belongs to another task")
        return row

    def _current(self, context, values):
        if isinstance(values, SnoozeFields):
            return self.reminders.get_saved(context.owner, values.occurrence_id)
        return self.preferences.get(context.owner)

    def _target(self, context, values):
        row = self.schedule.get_occurrence(context.owner, values.occurrence_id)
        if row is None:
            raise NotFoundError("Choose an existing owned dose; projected reminders cannot be snoozed")
        plan = self.enrollment.get_regimen(context.owner, row.regimen_id)
        if plan.state != RegimenState.ACTIVE or row.status == OccurrenceStatus.CLOSED:
            raise ValidationError("Choose an open dose of a current reviewed plan")
        if self.clock.now() + timedelta(minutes=values.minutes or 1) >= self.reminders.deadline(context.owner, row):
            raise ValidationError("The delay reaches the original reminder deadline")
        return row, self.enrollment.get_medication(context.owner, plan.patient_medication_id)

    def _missing(self, values):
        names = ("occurrence_id", "minutes", "previous_timezone") if isinstance(values, SnoozeFields) else (
            "reminders_enabled", "reminder_lead_minutes", "previous_enabled", "previous_lead_minutes",
            "previous_timezone")
        return tuple(name for name in names if getattr(values, name) is None)

    def _before_matches(self, context, values):
        preference = self.preferences.get(context.owner)
        if values.previous_timezone != preference.timezone:
            return False
        if isinstance(values, SnoozeFields):
            row = self._current(context, values)
            return (row.remind_at if row else None) == values.previous_remind_at
        return (preference.reminders_enabled == values.previous_enabled
                and preference.reminder_lead_minutes == values.previous_lead_minutes)

    def _check(self, context, values, ref=None):
        if self._missing(values) or not self._before_matches(context, values):
            raise StaleVersionError("The reminder state changed; collect the current fields again")
        if isinstance(values, SnoozeFields):
            self._target(context, values)
        if ref and self._receipt(context, ref).clinical_revision != self.clinical.revision(context.owner):
            raise StaleVersionError("The clinical records changed; prepare a new reminder review")

    def _payload(self, values):
        return {"occurrence_id": str(values.occurrence_id), "minutes": values.minutes} if isinstance(
            values, SnoozeFields) else {"reminders_enabled": values.reminders_enabled,
                                       "reminder_lead_minutes": values.reminder_lead_minutes}

    def review_snapshot(self, context, values):
        """Pure public policy/read projection for a separately owned transaction."""
        self._check(context, values)
        current = self._current(context, values)
        result = {"current": current.model_dump(mode="json") if current else None,
                  "timezone": self.preferences.get(context.owner).timezone}
        if isinstance(values, SnoozeFields):
            occurrence, _medicine = self._target(context, values)
            result.update({"occurrence": occurrence.model_dump(mode="json"),
                "plan": self.enrollment.get_regimen(context.owner, occurrence.regimen_id).model_dump(mode="json"),
                "deadline": self.reminders.deadline(context.owner, occurrence).isoformat()})
        return result

    def validate_payload(self, values, payload, confirmed):
        if not confirmed or payload.model_dump(mode="json", exclude_unset=True) != self._payload(values):
            raise StaleVersionError("Independently confirm the exact reviewed reminder fields")

    def _visible(self, context, values):
        preference = self.preferences.get(context.owner)
        result = {"timezone": preference.timezone, "current_settings": {
            "reminders_enabled": preference.reminders_enabled,
            "reminder_lead_minutes": preference.reminder_lead_minutes}}
        if isinstance(values, SnoozeFields) and values.occurrence_id:
            row = self.schedule.get_occurrence(context.owner, values.occurrence_id)
            if row is None:
                raise NotFoundError("Dose not found for this patient")
            plan = self.enrollment.get_regimen(context.owner, row.regimen_id)
            medicine = self.enrollment.get_medication(context.owner, plan.patient_medication_id)
            saved = self._current(context, values)
            result.update({"medication_name": medicine.display_name, "due_at": row.due_at.isoformat(),
                           "previous_remind_at": saved.remind_at.isoformat() if saved else None})
        return result

    def _review_ref(self, context, ref):
        if ref.kind == "reminder_review":
            row = self._receipt(context, ref)
            if row.business_ref != ref:
                raise StaleVersionError("This reminder review changed")
            return ref
        for row in self.actions.list(context.owner, context.task_id):
            candidate = row.business_ref
            if candidate and candidate.kind == "reminder_review":
                success = self._receipt(context, candidate, "reminder-native-success")
                if success and success.business_ref == ref and success.state == "succeeded":
                    return candidate
        raise NotFoundError("This reminder result has no native success receipt")

    def prepare(self, context: WorkflowContext, values: ReminderFields, assets: tuple[AttachmentRef, ...],
                results: tuple[BusinessRef, ...] = ()) -> Preparation:
        if assets or context.capability_id not in self.capability_ids:
            raise ValidationError("Use the selected typed reminder draft")
        inputs = values.model_dump(mode="json", exclude_none=True)
        visible = self._visible(context, values)
        if results:
            if len(results) != 1:
                raise ValidationError("Choose one reminder review")
            ref = self._review_ref(context, results[0])
            success = self._receipt(context, ref, "reminder-native-success")
            if success and success.state == "succeeded":
                return Preparation(input_fields=inputs, result_ref=results[0], view_fields=visible,
                    workflow_state="completed" if results[0].kind == "reminder_action" else "awaiting_confirmation",
                    prompt_key="assistant.reminder.saved" if results[0].kind == "reminder_action"
                    else "assistant.reminder.check_result")
            try:
                self._check(context, values, ref)
            except (NotFoundError, StaleVersionError, ValidationError):
                return Preparation(input_fields=inputs, result_ref=ref, view_fields=visible,
                                   workflow_state="failed_recoverable", prompt_key="assistant.reminder.changed")
            return Preparation(input_fields=inputs, result_ref=ref, view_fields={**visible,
                "reminder_review": {"payload": self._payload(values)}}, workflow_state="awaiting_confirmation",
                prompt_key="assistant.reminder.patient_review", actions=(ExistingReviewAction(
                    component_key="existing_reminder_review", owned_ref=ref, expected_version=1),))
        missing = self._missing(values)
        if not missing:
            self._check(context, values)
        choices = []
        if isinstance(values, SnoozeFields) and values.occurrence_id is None:
            start, end = self.schedule.today_window(context.owner)
            for medicine in self.enrollment.list_medications(context.owner)[:50]:
                for plan in self.enrollment.list_regimens(context.owner, medicine.id):
                    if plan.state != RegimenState.ACTIVE:
                        continue
                    for row in self.schedule.existing_occurrences(context.owner, plan.id, start, end):
                        if (row.status != OccurrenceStatus.CLOSED
                                and self.reminders.deadline(context.owner, row) > self.clock.now()):
                            choices.append(ChoiceOption(value=str(row.id), label_key="assistant.reminder.select",
                                label_text=f"{medicine.display_name[:150]} · "
                                f"{row.due_at.astimezone(ZoneInfo(context.timezone)):%Y-%m-%d %H:%M}"))
            visible["has_existing_occurrences"] = bool(choices)
        return Preparation(input_fields=inputs, view_fields=visible, missing_fields=missing,
            workflow_state="collecting" if missing else "ready_for_review",
            prompt_key="assistant.reminder.collect" if missing else "assistant.reminder.ready",
            actions=(ChoiceAction(action_id="reminder.occurrence", options=tuple(choices[:10])),) if choices else ())

    def prepare_once(self, context: WorkflowContext, values: ReminderFields, assets: tuple[AttachmentRef, ...],
                     action_key: UUID) -> BusinessRef:
        if context.save_mode != "allowed" or assets:
            raise ValidationError("Save this reminder draft before independent confirmation")
        self._check(context, values)
        ref = BusinessRef(kind="reminder_review", id=action_key, version=1)
        receipt = self.actions.reserve(context, action_key)
        self.actions.complete(context, receipt.model_copy(update={
            "business_ref": ref, "safe_reason": "reminder_prepared",
            "clinical_revision": self.clinical.revision(context.owner), "state": "succeeded"}))
        return ref

    def reconcile(self, context, action_key):
        try:
            return self._receipt(context, BusinessRef(kind="reminder_review", id=action_key)).business_ref
        except NotFoundError:
            return None

    def revise_inputs(self, context, result_ref):
        ref = self._review_ref(context, result_ref)
        if self._receipt(context, ref, "reminder-native-success"):
            raise StaleVersionError("This reminder action already succeeded")
        if self._receipt(context, ref, "reminder-patient-confirmation"):
            checked = self._receipt(context, ref, f"reminder-no-result:{context.revision - 1}")
            if checked is None or checked.safe_reason != "reminder_no_result_checked":
                raise StaleVersionError("Check the actual reminder result before editing")
        return {}

    def read_patient_result(self, context, result_ref, values=None):
        ref = self._review_ref(context, result_ref)
        success = self._receipt(context, ref, "reminder-native-success")
        if success and success.state == "succeeded":
            self._current(context, values)  # Read actual owned native state; receipt proves the earlier action only.
            return success.business_ref
        if self._before_matches(context, values):
            receipt = self.actions.reserve(context, uuid5(ref.id, f"reminder-no-result:{context.revision}"))
            self.actions.complete(context, receipt.model_copy(update={"business_ref": ref,
                                  "safe_reason": "reminder_no_result_checked", "state": "succeeded"}))
        return ref

    def observe(self, context, result_ref):
        return OperationResult(state="pending", business_ref=result_ref)

    def run_patient_action(self, context: WorkflowContext, result_ref: BusinessRef, write: Callable[[], T]) -> T:
        return self.clinical.run(context.owner, self.clinical.revision(context.owner), write)

    def run_bound_request(self, context, values, ref, payload, confirmed, write):
        self._receipt(context, ref)
        self.validate_payload(values, payload, confirmed)
        if self._receipt(context, ref, "reminder-native-success"):
            return self._current(context, values)
        self._check(context, values, ref)
        if self._receipt(context, ref, "reminder-patient-confirmation"):
            raise StaleVersionError("Check the uncertain reminder result; do not repeat this write")
        operation = self.actions.reserve(context, uuid5(ref.id, "reminder-patient-confirmation"))
        self.actions.complete(context, operation.model_copy(update={"business_ref": ref,
                              "safe_reason": "reminder_patient_confirmed", "state": "succeeded"}))
        result = write()
        current = self._current(context, values)
        if current is None or current != result:
            raise StaleVersionError("The native reminder result could not be verified")
        receipt = self.actions.reserve(context, uuid5(ref.id, "reminder-native-success"))
        actual = BusinessRef(kind="reminder_action", id=receipt.action_key, version=1)
        self.actions.complete(context, receipt.model_copy(update={"business_ref": actual,
                              "safe_reason": "reminder_saved", "state": "succeeded"}))
        return result
