"""Patient ports share one verified JWT; the verifier has a separate lazy identity."""

from types import MappingProxyType

import psycopg

from ..agent.capabilities import build_capability_registry
from ..config import ConfigError
from ..contracts.assistant_capabilities import CapabilityAvailability
from ..contracts.workflow_medication_writes import MedicationWritePreparationPort
from ..contracts.workflow_runtime import CapabilityPersistenceBoundary, PersistentWorkflowPorts
from ..infrastructure.durable_agent_runs import SupabaseDurableRunControl
from ..infrastructure.enrollment_operations import SupabaseEnrollmentWritePort
from ..infrastructure.supabase_data import SupabaseDataClient
from ..infrastructure.verified_original_repos import SupabaseVerifiedOriginals
from ..infrastructure.workflow_care_writes import SupabaseCareWorkflowWrites
from ..infrastructure.workflow_media_cleanup import SupabaseMediaCleanupTickets
from ..infrastructure.workflow_media_storage import SupabaseMediaCopyTickets
from ..infrastructure.workflow_media_writes import SupabaseMediaWorkflowWrites
from ..infrastructure.workflow_medication_writes import SupabaseMedicationWorkflowWrites
from ..infrastructure.workflow_message_repos import SupabaseConversationPersistence
from ..infrastructure.workflow_record_writes import SupabaseRecordWorkflowWrites
from ..infrastructure.workflow_reminder_writes import SupabaseReminderWorkflowWrites
from ..infrastructure.workflow_repos import (
    SupabaseActionRepository,
    SupabaseControlRepository,
    SupabaseWorkflowMutations,
    SupabaseWorkflowRepository,
)
from ..infrastructure.workflow_settings_writes import SupabaseSettingsWorkflowWrites
from ..infrastructure.workflow_verification import (
    EvidenceConnectionSettings,
    PostgresEvidenceVerifier,
    RestrictedEvidenceConnection,
)


def build_persistent_workflow_ports(
    *,
    data: SupabaseDataClient,
    evidence_dsn: str | None = None,
    medication_preparations: MedicationWritePreparationPort | None = None,
) -> PersistentWorkflowPorts:
    """Construct only; no metadata/Storage query and no verifier connection."""
    receipts = SupabaseWorkflowMutations(data)
    native_reads = SupabaseEnrollmentWritePort(data)
    copies = SupabaseMediaCopyTickets(data=data)
    verifier = None
    if evidence_dsn:
        try:
            verifier = PostgresEvidenceVerifier(
                RestrictedEvidenceConnection(EvidenceConnectionSettings(evidence_dsn), connect=psycopg.connect)
            )
        except ValueError:
            # An optional evidence configuration cannot take down the homepage
            # or grant fallback clinical authority. Expose only a safe reason.
            pass
    return PersistentWorkflowPorts(
        boundaries=build_persistence_boundaries(),
        tasks=SupabaseWorkflowRepository(data),
        controls=SupabaseControlRepository(data),
        actions=SupabaseActionRepository(data),
        mutations=receipts,
        receipts=receipts,
        messages=SupabaseConversationPersistence(data),
        runs=SupabaseDurableRunControl(data),
        originals=SupabaseVerifiedOriginals(data),
        media_copies=copies,
        media_cleanup=SupabaseMediaCleanupTickets(data=data, receipts=receipts),
        medications=SupabaseMedicationWorkflowWrites(
            data=data, reads=native_reads, receipts=receipts, preparations=medication_preparations
        ),
        records=SupabaseRecordWorkflowWrites(data=data, reads=native_reads, receipts=receipts),
        care=SupabaseCareWorkflowWrites(data=data, receipts=receipts),
        media=SupabaseMediaWorkflowWrites(data=data, receipts=receipts, copies=copies),
        settings=SupabaseSettingsWorkflowWrites(data=data, receipts=receipts),
        reminders=SupabaseReminderWorkflowWrites(data=data, receipts=receipts),
        verifier=verifier,
        verification_reason=None if verifier is not None else "verification_unavailable",
    )


def build_persistence_boundaries():
    """Saved-workflow inventory only; no inference of implementation/acceptance."""
    definitions = {d.id: d for d in build_capability_registry().list(CapabilityAvailability())}
    boundaries = {}
    common = frozenset({"tasks", "controls", "actions", "mutations", "messages", "runs"})
    domain_families = {"medications", "records", "care", "media", "settings", "reminders"}

    def declare(family, names, *, external=None, confirmation=None):
        for name in names.split():
            if name in boundaries or name not in definitions:
                raise ConfigError("Persistent capability boundary is missing or duplicated")
            definition = definitions[name]
            ports = common | ({family} if family in domain_families else set())
            if external == "verified_private_storage":
                ports = ports | {"originals", "media_copies"}
            guard = confirmation or (
                "independent_patient_api"
                if family in domain_families
                else "read_only"
                if definition.mode == "read"
                else "browser"
                if definition.mode in {"device_ui", "patient_ui", "navigation"}
                else "workflow_control"
            )
            boundaries[name] = CapabilityPersistenceBoundary(
                name, definition.mode, family, frozenset(ports), guard, external
            )

    declare(
        "medications",
        "medication.enroll medication.draft.delete medication.source.review medication.plan.change medication.plan.end",
    )
    declare("medications", "medication.source.add", external="verified_private_storage")
    declare("workflow", "medication.draft.resume")
    declare("records", "dose.report dose.prn.report dose.late.review dose.correction.review")
    declare(
        "care",
        "observation.add observation.edit observation.delete inventory.count barrier.add followup.add followup.edit "
        "followup.contacted followup.complete followup.defer followup.cancel",
    )
    declare(
        "media",
        "gallery.photo.edit gallery.photo.remove gallery.photo.delete gallery.photo.retire "
        "library.pdf.edit library.pdf.delete",
    )
    declare("media", "gallery.photo.add library.pdf.add", external="verified_private_storage")
    declare("reminders", "reminder.snooze reminder.settings")
    declare(
        "settings",
        "caregiver.add caregiver.edit caregiver.delete preference.language preference.text preference.voice "
        "preference.reminder preference.privacy preference.timezone profile.edit feedback.submit",
    )
    declare("messages", "conversation.resume conversation.new conversation.clear")
    declare(
        "native_read",
        "medication.plan.view medication.setup.list medication.today medication.due medication.status "
        "medication.history medication.source.view record.catalogue record.history record.summary record.visit.prepare",
    )
    declare("native_read", "medication.knowledge medication.instructions", external="provider_read")
    declare(
        "native_read",
        "observation.list inventory.view barrier.list followup.list gallery.list gallery.photo.view library.list "
        "library.pdf.view library.pdf.download reminder.list notification.status caregiver.list profile.view "
        "conversation.list conversation.view assistant.usage",
    )
    declare(
        "device",
        "image.compare source.preview reminder.calendar.export notification.subscribe notification.unsubscribe "
        "notification.test speech.input speech.playback",
        external="browser_handoff",
    )
    declare(
        "auth", "account.status account.login account.link account.password account.signout", external="browser_handoff"
    )
    declare("navigation", "help.open guide.start navigation.open", external="browser_handoff")
    if set(boundaries) != set(definitions):
        raise ConfigError("Every capability needs an explicit persistent boundary before composition")
    return MappingProxyType(boundaries)
