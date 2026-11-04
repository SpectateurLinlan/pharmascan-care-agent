"""Consented contact drafts use only the owned public caregiver service."""

from uuid import UUID

from ...contracts.assistant_workflows import ChoiceAction, ChoiceOption, Preparation
from ...contracts.caregivers import CaregiverCreate, CaregiverDetails
from ...contracts.settings_workflow import CONTACT_SCHEMAS
from ...domain.errors import NotFoundError, StaleVersionError, ValidationError
from ..caregivers import CaregiverService


class ContactDrafts:
    prompt = "assistant.settings"
    review_component = "existing_contact_review"
    schemas = CONTACT_SCHEMAS
    read_ids = frozenset({"caregiver.list"})

    def __init__(self, contacts: CaregiverService):
        self.contacts = contacts

    @staticmethod
    def safe(row):
        return row.model_dump(mode="json", exclude={"patient_id"}) if row else None

    def target(self, context, values, review_id):
        return review_id if context.capability_id == "caregiver.add" else values.contact_id

    def current(self, context, values, review_id=None):
        target = self.target(context, values, review_id)
        return self.safe(self.contacts.get(context.owner, target)) if target else None

    def payload(self, context, values, review_id):
        if context.capability_id == "caregiver.delete":
            return {}
        data = {key: getattr(values, key) for key in ("name", "relationship", "contact_type", "contact_value",
                                                     "storage_consent")}
        return (CaregiverCreate(id=review_id, **data) if context.capability_id == "caregiver.add"
                else CaregiverDetails(**data)).model_dump(mode="json")

    def missing(self, context, values):
        needed = []
        if context.capability_id != "caregiver.add":
            needed += [key for key in ("contact_id", "previous", "previous_updated_at") if getattr(values, key) is None]
        if context.capability_id != "caregiver.delete":
            needed += [key for key in ("name", "contact_type", "contact_value", "storage_consent")
                       if not getattr(values, key)]
        return tuple(needed)

    def unchanged(self, context, values, review_id=None):
        row = self.current(context, values, review_id)
        if context.capability_id == "caregiver.add":
            return row is None
        return bool(row and values.previous and values.previous_updated_at
            and all(row[key] == value for key, value in values.previous.model_dump(mode="json").items())
            and row["updated_at"] == values.previous_updated_at.isoformat().replace("+00:00", "Z"))

    def check(self, context, values, review_id=None):
        if self.missing(context, values) or not self.unchanged(context, values, review_id):
            raise StaleVersionError("The contact changed; review the current owned details")
        self.payload(context, values, review_id or UUID(int=0))

    def collect(self, context, values):
        rows = self.contacts.list(context.owner)
        if context.capability_id in self.read_ids:
            return Preparation(input_fields={}, prompt_key="assistant.settings.read",
                               view_fields={"contacts": [self.safe(row) for row in rows]})
        if context.capability_id == "caregiver.add" and (values.contact_id or values.previous):
            raise ValidationError("A new contact draft cannot replace an existing contact")
        visible = {}
        if values.contact_id:
            row = self.contacts.get(context.owner, values.contact_id)
            if row is None:
                raise NotFoundError("Contact not found for this patient")
            visible["current_contact"] = self.safe(row)
        missing = self.missing(context, values)
        if not missing:
            self.check(context, values)
        return Preparation(input_fields=values.model_dump(mode="json", exclude_none=True), missing_fields=missing,
            workflow_state="collecting" if missing else "ready_for_review", prompt_key="assistant.settings.collect",
            view_fields=visible, actions=(ChoiceAction(action_id="settings.contact", options=tuple(
                ChoiceOption(value=str(row.id), label_key="assistant.contact.select", label_text=row.name[:200])
                for row in rows[:10])),) if "contact_id" in missing and rows else ())

    def visible(self, context, values, review_id):
        return {"current_contact": self.current(context, values, review_id)}

    def native_result(self, context, values, review_id):
        if context.capability_id == "caregiver.delete":
            return {"deleted": True}
        return self.contacts.get(context.owner, self.target(context, values, review_id))

    def verify(self, context, values, review_id, result):
        if context.capability_id == "caregiver.delete":
            return result == {"deleted": True} and self.current(context, values, review_id) is None
        actual = self.native_result(context, values, review_id)
        return actual == result and actual is not None and all(
            actual.model_dump(mode="json").get(key) == value
            for key, value in self.payload(context, values, review_id).items())
