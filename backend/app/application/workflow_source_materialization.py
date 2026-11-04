"""Pure source proposal plus independently verified native image; no clinical publication."""

from uuid import uuid5

from ..contracts.assistant_workflows import WorkflowContext
from ..contracts.medication_evidence import EvidenceSourcePublication
from ..contracts.workflow_media_storage import MediaCopyTarget, MediaCopyTicketPort
from ..contracts.workflow_medication_writes import (
    MaterializedMedicationSource,
    SaveSourceRegistration,
    SourcePublicationMetadata,
)
from ..contracts.workflow_verification import VerifiedOriginalPort
from ..domain.errors import StaleVersionError
from .source_operations import SourceEnrollmentOperationService
from .workflow_media_storage import MediaCopyVerificationService


class SourceMaterializationService:
    def __init__(
        self,
        *,
        operations: SourceEnrollmentOperationService,
        originals: VerifiedOriginalPort,
        copies: MediaCopyTicketPort,
        copier: MediaCopyVerificationService,
        domain,
    ):
        self._operations, self._originals, self._copies, self._copier, self._domain = (
            operations,
            originals,
            copies,
            copier,
            domain,
        )

    def materialize(self, owner, command):
        command = SaveSourceRegistration.model_validate(command.model_dump())
        b = command.binding
        if b.capability_id != "medication.source.add" or self._domain.revision(owner) != b.expected_domain_revision:
            raise StaleVersionError("The current owned source inputs changed before materialization")
        ref = b.prepared_ref
        if ref.kind == "media_review":
            if ref.id != b.task_id or ref.version != b.task_revision:
                raise StaleVersionError("The source preparation marker changed")
            target = uuid5(b.task_id, "source-registration")
        elif ref.kind == "enrollment_task":
            target = ref.id
        else:
            raise StaleVersionError("Use the current independent source registration review")
        original_proof = self._originals.verification_for(owner, b.task_id, command.attachment_id)
        context = WorkflowContext(
            owner=owner, task_id=b.task_id, revision=b.task_revision, capability_id=b.capability_id, save_mode="allowed"
        )
        prepared = self._operations.prepare_request(
            context, target, command.attachment_id, allocation_key=b.action_key, include_duplicate_snapshot=True
        )
        proposal = prepared.publication
        duplicate = not isinstance(proposal, EvidenceSourcePublication)
        if duplicate:
            snapshot = prepared.duplicate_snapshot
            if snapshot is None or snapshot.task != proposal:
                raise StaleVersionError("Actual duplicate source snapshot is unavailable")
            metadata = SourcePublicationMetadata(
                **snapshot.model_dump(exclude={"derived_byte_size"}), create_medication=False, prior_task=proposal
            )
        else:
            metadata = SourcePublicationMetadata(
                **{key: getattr(proposal, key) for key in SourcePublicationMetadata.model_fields}
            )
        image = metadata.image
        copy_target = MediaCopyTarget(
            owner=owner,
            medication_id=image.medication_id,
            native_id=image.id,
            media_kind="source_image",
            source_kind=metadata.source.source_kind.value,
            checksum=image.checksum,
            content_type="image/png",
            byte_size=len(proposal.derived_image) if not duplicate else snapshot.derived_byte_size,
        )
        copy_proof = self._copies.recover(context, command.attachment_id, copy_target)
        if copy_proof is None:
            copy_proof = self._copier.copy(
                context,
                command.attachment_id,
                copy_target,
                run_binding=b.run_binding,
                writer_id=uuid5(b.action_key, "source-native-copy"),
            )
        ticket = self._copies.assert_current_copy(context, copy_proof)
        if ticket.target != copy_target or ticket.attachment_id != command.attachment_id:
            raise StaleVersionError("Source copy proof differs from the native proposal")
        return MaterializedMedicationSource(
            metadata=metadata,
            attachment_id=command.attachment_id,
            original_verification=original_proof,
            copy_verification=copy_proof,
            duplicate=duplicate,
        )
