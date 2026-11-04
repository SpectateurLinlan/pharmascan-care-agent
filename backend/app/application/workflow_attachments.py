"""Retain allowed originals before extraction; decoded processing bytes are derived."""

import hashlib
from collections.abc import Callable
from uuid import UUID, uuid5

from pydantic import ValidationError as SchemaValidationError

from ..contracts.assistant_workflows import (
    AttachmentRef,
    BusinessRef,
    ControlRepository,
    WorkflowContext,
    WorkflowRepository,
)
from ..contracts.ports import IdGenerator
from ..contracts.source_extraction import MedicationSourceExtractionDTO
from ..contracts.workflow_attachments import (
    STORE_ONLY_KINDS,
    AttachmentView,
    EphemeralImagePreview,
    ImageMime,
    OriginalAttachment,
    OriginalKind,
    OriginalMime,
    OriginalRepository,
    SourceKind,
    WorkflowAttachmentStore,
    WorkflowEnrollmentSource,
)
from ..domain.errors import NotFoundError, ProviderUnavailableError, StaleVersionError, ValidationError
from .enrollment import MedicationEnrollmentService
from .evidence_enrollment import EvidenceEnrollmentService
from .library_files import PDF_LIMIT, is_basic_pdf
from .preferences import PreferenceService
from .source_preview import SourcePreviewService
from .workflow_cleanup import WorkflowCleanupService
from .workflow_verification import WorkflowVerificationService


class WorkflowAttachmentService:
    def __init__(
        self,
        *,
        repository: OriginalRepository,
        storage: WorkflowAttachmentStore | None,
        tasks: WorkflowRepository,
        controls: ControlRepository,
        preferences: PreferenceService,
        ids: IdGenerator,
        normalize: Callable[[bytes], bytes],
        preview: SourcePreviewService | None = None,
        cleanup: WorkflowCleanupService | None = None,
        enrollment: MedicationEnrollmentService | None = None,
        verification: WorkflowVerificationService | None = None,
    ):
        self._repository, self._storage, self._tasks, self._controls = repository, storage, tasks, controls
        self._preferences, self._ids, self._normalize, self._preview = preferences, ids, normalize, preview
        self._cleanup = cleanup
        self._enrollment = enrollment
        self._verification = verification

    def protect_for_source(self, context: WorkflowContext, attachment_id: UUID, source_id: UUID) -> AttachmentView:
        """Server-side retention link; no source creation, identity claim or patient confirmation."""
        if self._enrollment is None:
            raise ProviderUnavailableError("Source protection cannot be verified")
        source = self._enrollment.get_source(context.owner, source_id)
        if source is None:
            raise NotFoundError("Source not found for this patient")
        if source.review_status.value not in {"user_reviewed", "professional_verified"}:
            raise ValidationError("Use the existing source review before linking a formal source")
        self._owned(context.owner, context.task_id, attachment_id)
        return self.view(
            self._repository.protect_source(
                context,
                attachment_id,
                BusinessRef(kind="source", id=source_id),
                self._ids.new_id(),
            )
        )

    def context(self, owner: UUID, task_id: UUID, expected_revision: int) -> WorkflowContext:
        control = self._controls.get(owner, task_id)
        preferences = self._preferences.get(owner)
        return WorkflowContext(
            owner=owner,
            task_id=task_id,
            capability_id=control.capability_id,
            revision=expected_revision,
            save_mode=control.mode,
            language=preferences.preferred_language,
            timezone=preferences.timezone,
        )

    def _storage_service(self) -> WorkflowAttachmentStore:
        if self._storage is None:
            raise ProviderUnavailableError("Original image storage is unavailable")
        return self._storage

    def preview_ephemeral(
        self,
        context: WorkflowContext,
        event_id: UUID,
        content: bytes,
        mime: ImageMime,
        processing_consent: bool,
        source_kind: SourceKind = "pharmacy_label",
    ) -> EphemeralImagePreview:
        if context.capability_id in {"image.compare", "source.preview"}:
            raise ValidationError("Photo comparison cannot use medication source recognition")
        if context.save_mode != "ephemeral":
            raise ValidationError("Use the saved original flow for this task")
        if not processing_consent:
            raise ValidationError("Agree to image processing before analyzing this photo")
        if not (
            (mime == "image/png" and content.startswith(b"\x89PNG\r\n\x1a\n"))
            or (mime == "image/jpeg" and content.startswith(b"\xff\xd8\xff"))
        ):
            raise ValidationError("Choose a valid PNG or JPEG photo")
        derived = self._normalize(content)
        self._controls.claim(
            context.owner, context.task_id, context.revision, event_id, context.capability_id, "ephemeral"
        )
        preview, reason, fields = None, None, None
        try:
            if self._preview is None:
                raise ProviderUnavailableError("Medication source extraction is unavailable")
            preview = self._preview.preview(content=derived, source_kind=source_kind, consent=True, demo_only=True)
            if context.capability_id == "medication.enroll":
                fields = EvidenceEnrollmentService.workflow_fields(preview).model_copy(
                    update={"page_photo_previewed": True}
                )
        except (ProviderUnavailableError, ValidationError, SchemaValidationError) as error:
            reason = "provider_unavailable" if isinstance(error, ProviderUnavailableError) else "extraction_rejected"
        control = self._controls.finish(context.owner, context.task_id, context.revision, event_id)
        return EphemeralImagePreview(
            task_id=context.task_id,
            revision=control.revision,
            capability_id=context.capability_id,
            outcome="failed" if reason else "success",
            reason=reason,
            preview=preview,
            fields=fields,
        )

    def enrollment_source(
        self, owner: UUID, task_id: UUID, attachment_id: UUID, *, verify_original: bool = False
    ) -> WorkflowEnrollmentSource:
        control = self._controls.get(owner, task_id)
        if control.mode != "allowed" or control.revoked:
            raise ValidationError("Enable saving before using a stored photo source")
        row = self._owned(owner, task_id, attachment_id)
        if row.source_kind in STORE_ONLY_KINDS:
            raise ValidationError("A gallery original is not a medication instruction source")
        if row.state != "saved" or row.extraction_status != "succeeded" or row.extraction is None:
            raise ValidationError("This original has no successful source extraction")
        if row.extraction.source_kind != row.source_kind:
            raise ValidationError("The extraction source type differs from the chosen original")
        if verify_original:
            self.read(owner, task_id, attachment_id)
        return WorkflowEnrollmentSource(
            owner=owner,
            task_id=task_id,
            attachment_id=attachment_id,
            original_checksum=row.original_checksum,
            source_kind=row.source_kind,
            extraction=row.extraction,
        )

    def _owned(self, owner: UUID, task_id: UUID, attachment_id: UUID) -> OriginalAttachment:
        self._tasks.get(owner, task_id)
        control = self._controls.get(owner, task_id)
        if control.mode != "allowed" or control.revoked:
            raise ValidationError("Saving permission changed for this original")
        return self._repository.get(owner, task_id, attachment_id)

    @staticmethod
    def view(row: OriginalAttachment) -> AttachmentView:
        return AttachmentView(**row.model_dump(include=set(AttachmentView.model_fields)))

    def accept(
        self,
        context: WorkflowContext,
        upload_id: UUID,
        content: bytes,
        mime: OriginalMime,
        processing_consent: bool,
        source_kind: OriginalKind = "pharmacy_label",
    ) -> AttachmentView:
        if context.save_mode != "allowed":
            raise ValidationError("This workflow is not saving originals; keep the photo on this page")
        reference = source_kind in STORE_ONLY_KINDS
        assigned = {"gallery.photo.add": "reference_photo", "library.pdf.add": "library_pdf",
                    "image.compare": "comparison_photo", "source.preview": "source_preview_photo"}
        if ((reference and source_kind != assigned.get(context.capability_id))
                or (not reference and context.capability_id in assigned)):
            raise ValidationError("Use the original kind assigned to this workflow")
        task = self._tasks.get(context.owner, context.task_id)
        if reference and task.business_refs:
            previous = self._repository.find_upload(context.owner, context.task_id, upload_id)
            if previous is None or previous.state != "saved":
                raise ValidationError("Edit the current photo draft before adding another original")
        storage = self._storage_service()
        self._validate_original(content, mime, source_kind)
        checksum = hashlib.sha256(content).hexdigest()
        publish_event = upload_id
        previous = self._repository.find_upload(context.owner, context.task_id, upload_id)
        if previous is not None:
            self._owned(context.owner, context.task_id, previous.id)
            if (previous.original_checksum, previous.content_type, previous.source_kind) != (
                checksum,
                mime,
                source_kind,
            ):
                from ..domain.errors import DuplicateEventError

                raise DuplicateEventError("Upload ID was reused for different original content")
            if previous.state == "saved":
                return self.view(previous)
            control = self._controls.get(context.owner, context.task_id)
            if (
                control.revision != context.revision
                or control.status != "interrupted"
                or control.processing_event_id != previous.operation_event_id
            ):
                raise StaleVersionError("Original saving is unresolved; check its outcome before retrying")
            try:
                self.read(context.owner, context.task_id, previous.id)
            except NotFoundError:
                # Absence does not prove the old writer stopped. An explicit retry
                # keeps its intent and immutable key, so both attempts can only
                # store the exact same bytes; old metadata publishes stay fenced.
                recovered = self._controls.recover(
                    context.owner,
                    context.task_id,
                    context.revision,
                    uuid5(upload_id, f"recover-write:{context.revision}"),
                )
                context = context.model_copy(update={"revision": recovered.revision})
                publish_event = uuid5(upload_id, f"retry-write:{context.revision}")
                row = self._repository.retry_reservation(context, previous.id, publish_event)
                row = row.model_copy(
                    update={
                    "extraction_status": "not_requested" if reference else
                        "pending" if processing_consent else "consent_required",
                        "reason": None if reference or processing_consent else "processing_consent_required",
                    }
                )
            else:
                return self.recover(context, previous.id, uuid5(upload_id, f"observe-write:{context.revision}"))
        else:
            attachment_id = self._ids.new_id()
            row = self._repository.reserve(
                context,
                OriginalAttachment(
                    id=attachment_id,
                    owner=context.owner,
                    task_id=context.task_id,
                    upload_id=upload_id,
                    binding_revision=context.revision,
                    object_ref=f"{context.owner}/workflow-originals/{context.task_id}/{attachment_id}",
                    original_checksum=checksum,
                    content_type=mime,
                    byte_size=len(content),
                    source_kind=source_kind,
                    extraction_status="not_requested" if reference else
                    "pending" if processing_consent else "consent_required",
                    reason=None if reference or processing_consent else "processing_consent_required",
                ),
            )
        if self._verification is not None:
            self._verification.save(context, row.id, publish_event, content)
            row = self._repository.get(context.owner, context.task_id, row.id)
        else:
            stored = storage.put_original(
                context.owner, context.task_id, upload_id, content, mime, object_ref=row.object_ref
            )
            if self._cleanup:
                if not self._cleanup.written(context.owner, context.task_id, row.id, publish_event):
                    raise StaleVersionError("Original upload finished after saving was cancelled")
            else:
                self._repository.note_written(context.owner, context.task_id, row.id, publish_event)
            if stored.checksum != checksum or stored.byte_size != len(content):
                raise ProviderUnavailableError("Original storage could not verify the received bytes")
            row = self._repository.publish(context, row, event_id=publish_event)
        if processing_consent and not reference:
            current = self.context(context.owner, context.task_id, context.revision + 1)
            try:
                self.preview(
                    current, row.id, processing_consent=True, event_id=uuid5(publish_event, "initial-extraction")
                )
            except (ProviderUnavailableError, ValidationError):
                pass  # The original is saved; extraction outcome is a separate visible field.
        return self.view(self._owned(context.owner, context.task_id, row.id))

    def preview(
        self,
        context: WorkflowContext,
        attachment_id: UUID,
        *,
        processing_consent: bool = False,
        event_id: UUID | None = None,
    ) -> MedicationSourceExtractionDTO:
        if not processing_consent:
            raise ValidationError("Agree to image processing before analyzing this original")
        row = self._owned(context.owner, context.task_id, attachment_id)
        if row.source_kind in STORE_ONLY_KINDS:
            raise ValidationError("Gallery originals cannot be sent to medication source recognition")
        event_id = event_id or self._ids.new_id()
        row = self._repository.begin_extraction(context, attachment_id, event_id)
        try:
            if self._preview is None:
                raise ProviderUnavailableError("Medication source extraction is unavailable")
            original, _ = self.read(context.owner, context.task_id, attachment_id)
            result = self._preview.preview(
                content=self._normalize(original), source_kind=row.source_kind, consent=True, demo_only=True
            )
            if len(result.candidates) == 1:
                EvidenceEnrollmentService.workflow_fields(result)
        except (ProviderUnavailableError, ValidationError, SchemaValidationError) as error:
            failed = row.model_copy(
                update={
                    "extraction_status": "failed",
                    "reason": (
                        "provider_unavailable" if isinstance(error, ProviderUnavailableError) else "extraction_rejected"
                    ),
                }
            )
            self._repository.finish_extraction(context, failed, event_id)
            if isinstance(error, SchemaValidationError):
                raise ValidationError("The photo did not contain valid medication details") from error
            raise
        self._repository.finish_extraction(
            context,
            row.model_copy(
                update={
                    "extraction_status": "succeeded",
                    "extraction": result,
                    "reason": None,
                }
            ),
            event_id,
        )
        return result

    def read(self, owner: UUID, task_id: UUID, attachment_id: UUID) -> tuple[bytes, OriginalMime]:
        row = self._owned(owner, task_id, attachment_id)
        content = self._storage_service().read(owner, row.object_ref)
        if hashlib.sha256(content).hexdigest() != row.original_checksum:
            raise ProviderUnavailableError("The saved original could not be verified")
        return content, row.content_type

    def recognize(
        self, context: WorkflowContext, attachment_id: UUID, event_id: UUID, *, processing_consent: bool
    ) -> AttachmentView:
        # Read ownership before consent and never retry an already claimed event.
        self._owned(context.owner, context.task_id, attachment_id)
        if not processing_consent:
            raise ValidationError("Agree to image processing before analyzing this original")
        try:
            self.preview(context, attachment_id, processing_consent=True, event_id=event_id)
        except ProviderUnavailableError:
            pass  # Extraction failure is separate from successfully retained bytes.
        return self.view(self._owned(context.owner, context.task_id, attachment_id))

    def retry_upload(
        self, context: WorkflowContext, attachment_id: UUID, content: bytes,
        mime: OriginalMime, processing_consent: bool
    ) -> AttachmentView:
        row = self._owned(context.owner, context.task_id, attachment_id)
        return self.accept(context, row.upload_id, content, mime, processing_consent, row.source_kind)

    def recover(self, context: WorkflowContext, attachment_id: UUID, event_id: UUID) -> AttachmentView:
        row = self._owned(context.owner, context.task_id, attachment_id)
        control = self._controls.get(context.owner, context.task_id)
        if row.state == "saved" and control.status == "idle":
            return self.view(row)
        if (
            control.revision != context.revision
            or control.status != "interrupted"
            or control.processing_event_id != row.operation_event_id
        ):
            raise StaleVersionError("Check the interrupted upload outcome before continuing")
        # Observe the immutable object; do not resubmit a lost write or re-run a provider.
        content = self._storage_service().read(context.owner, row.object_ref)
        if hashlib.sha256(content).hexdigest() != row.original_checksum:
            raise ProviderUnavailableError("The saved original could not be verified")
        self._validate_original(content, row.content_type, row.source_kind)
        recovered = self._controls.recover(context.owner, context.task_id, context.revision, event_id)
        action_id = uuid5(event_id, "publish-recovered-original")
        current = context.model_copy(update={"revision": recovered.revision})
        if row.state == "saved" and row.source_kind not in STORE_ONLY_KINDS:
            row = self._repository.begin_extraction(current, row.id, action_id)
            updated = self._repository.finish_extraction(
                current,
                row.model_copy(update={"extraction_status": "interrupted", "reason": "extraction_interrupted"}),
                action_id,
            )
            return self.view(updated)
        row = self._repository.retry_reservation(current, row.id, action_id, starts_writer=False)
        self._repository.note_written(current.owner, current.task_id, attachment_id)
        saved = self._repository.publish(
            current,
            row.model_copy(
                update={
                    "extraction_status": "not_requested"
                    if row.source_kind in STORE_ONLY_KINDS
                    else "consent_required",
                    "reason": None if row.source_kind in STORE_ONLY_KINDS
                    else "processing_consent_required",
                }
            ),
            event_id=action_id,
        )
        return self.view(saved)

    def reference_original(self, owner: UUID, task_id: UUID, attachment_id: UUID) -> AttachmentView:
        """Owned saved gallery-original metadata only; no provider or binary read."""
        row = self._owned(owner, task_id, attachment_id)
        if row.source_kind != "reference_photo" or row.state != "saved":
            raise ValidationError("Choose a saved original reference photo")
        return self.view(row)

    def pdf_original(self, owner: UUID, task_id: UUID, attachment_id: UUID) -> AttachmentView:
        """Owned saved PDF metadata only; no extraction or binary read."""
        row = self._owned(owner, task_id, attachment_id)
        if row.source_kind != "library_pdf" or row.content_type != "application/pdf" or row.state != "saved":
            raise ValidationError("Choose a saved original PDF")
        return self.view(row)

    def _validate_original(self, content: bytes, mime: OriginalMime, kind: OriginalKind) -> None:
        if kind == "library_pdf":
            if mime != "application/pdf" or not 0 < len(content) <= PDF_LIMIT or not is_basic_pdf(content):
                raise ValidationError("Choose a valid PDF no larger than 10 MB")
            return
        if mime not in {"image/png", "image/jpeg"} or len(content) > 8_000_000 or not (
            (mime == "image/png" and content.startswith(b"\x89PNG\r\n\x1a\n"))
            or (mime == "image/jpeg" and content.startswith(b"\xff\xd8\xff"))
        ):
            raise ValidationError("Choose a PNG/JPEG photo matching its content type and size limit")
        self._normalize(content)

    def comparison_original(self, owner: UUID, task_id: UUID, attachment_id: UUID) -> AttachmentView:
        """Owned saved comparison image metadata; no recognition or binary read."""
        row = self._owned(owner, task_id, attachment_id)
        if row.source_kind != "comparison_photo" or row.content_type == "application/pdf" or row.state != "saved":
            raise ValidationError("Choose a saved original comparison photo")
        return self.view(row)

    def preview_original(self, owner: UUID, task_id: UUID, attachment_id: UUID) -> AttachmentView:
        """Owned saved preview image metadata only, never reviewed source evidence."""
        row = self._owned(owner, task_id, attachment_id)
        if row.source_kind != "source_preview_photo" or row.content_type == "application/pdf" or row.state != "saved":
            raise ValidationError("Choose a saved original for source preview")
        return self.view(row)

    def assets(self, owner: UUID, task_id: UUID) -> tuple[AttachmentRef, ...]:
        task = self._tasks.get(owner, task_id)
        return tuple(
            AttachmentRef(
                id=row.id,
                task_id=task_id,
                original_checksum=row.original_checksum,
                content_type=row.content_type,
                extraction_status=row.extraction_status,
            )
            for row in self._repository.list(owner, task_id)
            if row.state == "saved" and row.id in task.attachment_ids
        )

    def originals(self, owner: UUID) -> tuple[OriginalAttachment, ...]:
        return self._repository.list(owner)

    def list_views(self, owner: UUID, task_id: UUID) -> tuple[AttachmentView, ...]:
        self._tasks.get(owner, task_id)
        return tuple(self.view(self._owned(owner, task_id, row.id)) for row in self._repository.list(owner, task_id))
