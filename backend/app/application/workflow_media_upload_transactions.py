"""Saved raw originals, verified native copies and independent patient registration."""

import hashlib
from collections.abc import Callable, Mapping
from uuid import uuid5

from ..contracts.assistant_workflows import ExistingReviewAction, Preparation, validate_workflow_values
from ..contracts.workflow_attachments import OriginalRepository, WorkflowAttachmentStore
from ..contracts.workflow_media_storage import MediaCopyTarget, MediaCopyTicketPort
from ..contracts.workflow_media_writes import RegisterPdf, RegisterPhoto
from ..contracts.workflow_persistence import WorkflowWriteBinding
from ..domain.errors import NotFoundError, ProviderUnavailableError, StaleVersionError, ValidationError
from .enrollment import MedicationEnrollmentService
from .workflow_media_storage import MediaCopyVerificationService
from .workflow_media_transactions import MediaReviewTransactions


class MediaUploadWorkflowTransactions(MediaReviewTransactions):
    capability_ids = frozenset({"gallery.photo.add", "library.pdf.add"})

    def __init__(
        self,
        *,
        writes,
        tasks,
        receipts,
        originals: OriginalRepository,
        source_storage: WorkflowAttachmentStore,
        copies: MediaCopyTicketPort,
        copiers: Mapping[str, MediaCopyVerificationService],
        normalize: Callable[[bytes], bytes],
        preferences,
        enrollment: MedicationEnrollmentService,
    ):
        # Uploads share the same preparation and minimal native receipt protocol;
        # they have no lifecycle draft or deletion dependency.
        super().__init__(writes=writes, tasks=tasks, receipts=receipts, preferences=preferences)
        self._originals, self._source_storage, self._copies = originals, source_storage, copies
        self.copiers = dict(copiers)
        self._normalize, self._enrollment = normalize, enrollment

    def _original(self, task, values):
        if values.source_attachment_id not in task.attachment_ids:
            raise StaleVersionError("Choose the saved original from this task")
        row = self._originals.get(task.owner, task.id, values.source_attachment_id)
        photo = task.capability_id == "gallery.photo.add"
        if (
            row.state != "saved"
            or row.cleanup_pending
            or row.source_kind != ("reference_photo" if photo else "library_pdf")
        ):
            raise StaleVersionError("Use this task's retained original of the reviewed kind")
        return row

    def _target(self, task, values, *, supplied=None):
        original = self._original(task, values)
        data = self._source_storage.read(task.owner, original.object_ref)
        if (
            len(data) != original.byte_size
            or hashlib.sha256(data).hexdigest() != original.original_checksum
            or supplied is not None
            and data != supplied
        ):
            raise StaleVersionError("Upload bytes differ from this task's exact retained original")
        photo = task.capability_id == "gallery.photo.add"
        native = self._normalize(data) if photo else data
        digest = hashlib.sha256(native).hexdigest()
        return MediaCopyTarget(
            owner=task.owner,
            medication_id=values.medication_id,
            native_id=uuid5(values.medication_id, digest)
            if photo
            else uuid5(task.owner, f"medication-library-pdf:{values.medication_id}:{digest}"),
            media_kind="photo" if photo else "pdf",
            content_type="image/png" if photo else "application/pdf",
            checksum=digest,
            byte_size=len(native),
        )

    def _command(self, task, prep, *, allow_copy=False, supplied=None):
        values = validate_workflow_values(task.capability_id, task.fields)
        target = self._target(task, values, supplied=supplied)
        context = self._context(task).model_copy(update={"revision": prep.binding_revision})
        proof = self._copies.recover(context, values.source_attachment_id, target)
        if proof is None:
            if not allow_copy:
                raise NotFoundError("This registration has no actual verified native copy")
            copier = self.copiers.get(task.capability_id)
            if copier is None:
                raise ProviderUnavailableError("Independent upload materialization is not composed")
            proof = copier.copy(
                context,
                values.source_attachment_id,
                target,
                writer_id=uuid5(
                    task.id, f"native-upload:{prep.binding_revision}:{values.source_attachment_id}:{target.object_ref}"
                ),
            )
        b = WorkflowWriteBinding(
            task_id=task.id,
            task_revision=prep.binding_revision,
            capability_id=task.capability_id,
            action_key=uuid5(prep.business_ref.id, "media-upload-patient-confirmation"),
            prepared_ref=prep.business_ref,
            expected_domain_revision=prep.domain_revision,
        )
        if task.capability_id == "gallery.photo.add":
            return RegisterPhoto(
                binding=b, values=values, copy_proof=proof, confirmed=True, reviewed=True, processing_consent=True
            )
        return RegisterPdf(binding=b, values=values, copy_proof=proof, confirmed=True)

    def _request(self, owner, task_id, revision, capability, medication_id, data, expected, confirmed):
        task = self._tasks.get(owner, task_id)
        if (
            task.capability_id != capability
            or task.save_mode != "allowed"
            or task.state == "suspended"
            or confirmed is not True
        ):
            raise StaleVersionError("Use the current independent upload review and explicit consent")
        values = validate_workflow_values(capability, task.fields)
        actual = {key: getattr(values, key) for key in expected}
        if medication_id != values.medication_id or actual != expected:
            raise StaleVersionError("Upload metadata differs from the reviewed saved draft")
        if task.state == "completed":
            applied = self._applied(task)
            prep_revision = applied.binding_revision - 1
            if revision not in {task.revision, prep_revision}:
                raise StaleVersionError("Refresh the current upload result")
        else:
            if task.state != "awaiting_confirmation" or task.revision != revision:
                raise StaleVersionError("Refresh the current upload review")
            prep_revision = revision
        prep = self._preparation(task, prep_revision)
        action = uuid5(prep.business_ref.id, "media-upload-patient-confirmation")
        prior = self._writes.lookup(owner, action)
        if prior is None and self._writes.revision(owner) != prep.domain_revision:
            raise StaleVersionError("Current upload inputs changed after patient review")
        cmd = self._command(task, prep, allow_copy=prior is None, supplied=data)
        return self._writes.apply(owner, cmd).result

    def upload_photo(
        self, owner, task_id, revision, medication_id, data, image_kind, description, reviewed, comparison, consent
    ):
        if reviewed is not True or consent is not True or comparison is not False:
            raise StaleVersionError("Confirm the reviewed photo and processing consent; comparison is separate")
        return self._request(
            owner,
            task_id,
            revision,
            "gallery.photo.add",
            medication_id,
            data,
            {"image_kind": image_kind, "source_description": description},
            True,
        )

    def upload_pdf(self, owner, task_id, revision, medication_id, data, filename, category, description, confirmed):
        result = self._request(
            owner,
            task_id,
            revision,
            "library.pdf.add",
            medication_id,
            data,
            {"filename": filename, "category": category, "description": description},
            confirmed,
        )
        return result.file, result.duplicate

    def project(self, task):
        photo = task.capability_id == "gallery.photo.add"
        family = "photo" if photo else "pdf"
        if task.state == "completed":
            receipt = self._applied(task)
            try:
                cmd = self._command(task, self._preparation(task, receipt.binding_revision - 1))
                if cmd.binding.action_key != receipt.action_key:
                    raise StaleVersionError("Upload confirmation differs from its receipt")
                actual = self._writes.read(task.owner, cmd)
                if actual.receipt != receipt:
                    raise StaleVersionError("Upload result belongs to another receipt")
                native = actual.result.photo if photo else actual.result.file
                keys = (
                    {
                        "id",
                        "medication_id",
                        "image_kind",
                        "source_description",
                        "metadata_version",
                        "eligibility",
                        "eligibility_reason",
                    }
                    if photo
                    else {
                        "id",
                        "medication_id",
                        "original_filename",
                        "display_title",
                        "category",
                        "description",
                        "version",
                        "byte_size",
                    }
                )
                visible = {family: native.model_dump(mode="json", include=keys), "duplicate": actual.result.duplicate}
            except (NotFoundError, ProviderUnavailableError, StaleVersionError):
                visible = {"actual_result_available": False, "historical_result": True}
            return Preparation(
                input_fields=task.fields,
                result_ref=receipt.business_ref,
                workflow_state="completed",
                prompt_key=f"assistant.{family}.completed" if family in visible else "assistant.media.historical",
                view_fields=visible,
            )
        if task.state != "awaiting_confirmation" or not task.business_refs:
            return None
        ref = task.business_refs[0]
        try:
            prep = self._preparation(task, task.revision)
            if prep.business_ref != ref or prep.domain_revision != self._writes.revision(task.owner):
                raise StaleVersionError("Upload inputs changed after review")
            values = validate_workflow_values(task.capability_id, task.fields)
            original = self._original(task, values)
            med = self._enrollment.get_medication(task.owner, values.medication_id)
            if med is None:
                raise NotFoundError("Owned medication unavailable")
        except (NotFoundError, StaleVersionError, ValidationError):
            return Preparation(
                input_fields=task.fields,
                result_ref=ref,
                workflow_state="failed_recoverable",
                prompt_key=f"assistant.{family}.changed",
            )
        return Preparation(
            input_fields=task.fields,
            result_ref=ref,
            workflow_state="awaiting_confirmation",
            prompt_key=f"assistant.{family}.review",
            view_fields={
                "original_id": str(original.id),
                "medication_name": med.display_name,
                "originals": [{"id": str(original.id)}],
                "upload_attempted": False,
            },
            actions=(
                ExistingReviewAction(component_key="existing_media_management", owned_ref=ref, expected_version=1),
            ),
        )
