"""Public preference draft operations, separate from native patient persistence."""

from ...contracts.assistant_workflows import Preparation
from ...contracts.preferences import PreferenceUpdate
from ...contracts.settings_workflow import PREFERENCE_SCHEMAS
from ...domain.errors import StaleVersionError, ValidationError
from ..preferences import PreferenceService


class PreferenceDrafts:
    prompt = "assistant.settings"
    review_component = "existing_preference_review"
    schemas = PREFERENCE_SCHEMAS
    read_ids = frozenset({"profile.view"})

    def __init__(self, preferences: PreferenceService):
        self.preferences = preferences

    def current(self, context, values, review_id=None):
        return self.preferences.get(context.owner).model_dump(mode="json", exclude={
            "patient_id", "created_at", "updated_at"})

    def payload(self, context, values, review_id):
        changes = values.model_dump(mode="json", exclude={"previous"}, exclude_none=True)
        return PreferenceUpdate.model_validate(changes).model_dump(mode="json", exclude_unset=True)

    def missing(self, context, values):
        fields = values.model_dump(exclude={"previous"}, exclude_none=True)
        return tuple((["change"] if not fields else []) + (["previous"] if values.previous is None else []))

    def unchanged(self, context, values, review_id=None):
        return values.previous is not None and values.previous.model_dump(mode="json") == self.current(context, values)

    def check(self, context, values, review_id=None):
        if self.missing(context, values) or not self.unchanged(context, values):
            raise StaleVersionError("The preferences changed; collect the current settings before reviewing")
        if not self.payload(context, values, review_id):
            raise ValidationError("Choose a preference change")

    def target(self, context, values, review_id):
        return None

    def collect(self, context, values):
        current = self.current(context, values)
        missing = () if context.capability_id in self.read_ids else self.missing(context, values)
        if not missing and context.capability_id not in self.read_ids:
            self.check(context, values)
        return Preparation(input_fields=values.model_dump(mode="json", exclude_none=True),
            workflow_state="collecting" if missing or context.capability_id in self.read_ids else "ready_for_review",
            prompt_key=("assistant.settings.read" if context.capability_id in self.read_ids
                        else "assistant.settings.collect"),
            missing_fields=missing, view_fields={"current_preferences": current})

    def visible(self, context, values, review_id):
        return {"current_preferences": self.current(context, values)}

    def native_result(self, context, values, review_id):
        return self.preferences.get(context.owner)

    def verify(self, context, values, review_id, result):
        current = self.native_result(context, values, review_id)
        return current == result and all(getattr(current, key) == value
            for key, value in self.payload(context, values, review_id).items())
