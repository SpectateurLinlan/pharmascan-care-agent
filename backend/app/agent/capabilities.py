"""Static user capability registry; adapters are bound at the composition root."""

from ..contracts.assistant_capabilities import CapabilityAvailability, CapabilityDefinition, CapabilityView
from ..domain.errors import ValidationError


class CapabilityRegistry:
    def __init__(self, definitions: tuple[CapabilityDefinition, ...]):
        self._definitions = {definition.id: definition for definition in definitions}

    def get(self, capability_id: str) -> CapabilityDefinition:
        if capability_id not in self._definitions:
            raise ValidationError("Unknown assistant capability")
        return self._definitions[capability_id]

    def list(self, availability: CapabilityAvailability) -> tuple[CapabilityView, ...]:
        return tuple(self._view(definition, availability) for definition in self._definitions.values())

    @staticmethod
    def _view(definition: CapabilityDefinition, availability: CapabilityAvailability) -> CapabilityView:
        reason = None
        if not availability.workflows_enabled:
            reason = availability.workflow_unavailable_reason
        elif definition.id in availability.disabled_capabilities:
            reason = "feature_disabled"
        elif definition.adapter_key not in availability.adapters:
            reason = "not_implemented"
        elif (
            availability.implemented_capabilities is not None
            and definition.id not in availability.implemented_capabilities
        ):
            reason = "not_implemented"
        elif not definition.required_services <= availability.services:
            reason = "service_unavailable"
        elif definition.id == "notification.test" and not availability.notification_send_allowed:
            reason = "notification_send_not_authorized"
        implemented = definition.adapter_key in availability.adapters and (
            availability.implemented_capabilities is None or definition.id in availability.implemented_capabilities
        )
        return CapabilityView(
            **definition.model_dump(), implemented=implemented, available=reason is None, reason=reason
        )

    def model_catalog(self, availability: CapabilityAvailability) -> tuple[CapabilityView, ...]:
        return tuple(row for row in self.list(availability) if row.available and row.mode in {"read", "workflow"})


def build_capability_registry() -> CapabilityRegistry:
    groups = (
        ("enrollment", "enrollment", "workflow", "medication.enroll"),
        (
            "medication_management",
            "enrollment",
            "workflow",
            "medication.draft.resume medication.draft.delete medication.source.add medication.source.review "
            "medication.plan.change medication.plan.end",
        ),
        ("medication_management", "enrollment", "read", "medication.plan.view medication.setup.list"),
        (
            "records",
            "records",
            "read",
            "medication.today medication.due medication.status medication.history medication.source.view "
            "record.catalogue record.history record.summary record.visit.prepare",
        ),
        ("knowledge", "medication_understanding", "read", "medication.knowledge medication.instructions"),
        ("records", "self_report", "patient_ui", "dose.report dose.prn.report"),
        ("records", "late_reports", "patient_ui", "dose.late.review dose.correction.review"),
        ("care", "observations", "read", "observation.list"),
        ("care", "observations", "workflow", "observation.add observation.edit observation.delete"),
        ("care", "care", "read", "inventory.view barrier.list followup.list"),
        (
            "care",
            "care",
            "workflow",
            "inventory.count barrier.add followup.add followup.edit followup.contacted "
            "followup.complete followup.defer followup.cancel",
        ),
        ("media", "gallery", "read", "gallery.list gallery.photo.view"),
        (
            "media",
            "gallery",
            "workflow",
            "gallery.photo.add gallery.photo.edit gallery.photo.remove gallery.photo.delete gallery.photo.retire",
        ),
        ("media", "vision", "device_ui", "image.compare"),
        ("media", "source_preview", "device_ui", "source.preview"),
        ("media", "library_files", "read", "library.list library.pdf.view library.pdf.download"),
        ("media", "library_files", "workflow", "library.pdf.add library.pdf.edit library.pdf.delete"),
        ("reminders", "reminders", "read", "reminder.list"),
        ("reminders", "reminders", "workflow", "reminder.snooze reminder.settings"),
        ("reminders", "reminders", "device_ui", "reminder.calendar.export"),
        ("reminders", "push", "read", "notification.status"),
        ("reminders", "push", "device_ui", "notification.subscribe notification.unsubscribe notification.test"),
        ("contacts", "caregivers", "read", "caregiver.list"),
        ("contacts", "caregivers", "workflow", "caregiver.add caregiver.edit caregiver.delete"),
        (
            "preferences",
            "preferences",
            "workflow",
            "preference.language preference.text preference.voice preference.reminder preference.privacy "
            "preference.timezone profile.edit",
        ),
        ("preferences", "preferences", "read", "profile.view"),
        (
            "account_ui",
            "account",
            "patient_ui",
            "account.status account.login account.link account.password account.signout",
        ),
        ("conversations", "conversations", "read", "conversation.list conversation.view"),
        ("conversations", "conversations", "workflow", "conversation.resume conversation.new conversation.clear"),
        ("conversations", "quota", "read", "assistant.usage"),
        ("device_ui", "speech", "device_ui", "speech.input speech.playback"),
        ("feedback", "feedback", "workflow", "feedback.submit"),
        ("navigation", "navigation", "navigation", "help.open guide.start navigation.open"),
    )
    return CapabilityRegistry(
        tuple(
            CapabilityDefinition(
                id=name,
                title_key=f"assistant.capability.{name}",
                mode=mode,
                input_schema_id=f"{name}:v1",
                adapter_key=adapter,
                required_services=frozenset({service}),
            )
            for adapter, service, mode, names in groups
            for name in names.split()
        )
    )
