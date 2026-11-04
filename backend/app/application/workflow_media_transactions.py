"""Typed patient media confirmations; native tombstones never prove physical cleanup."""

import json
from uuid import uuid5

from ..contracts.assistant_workflows import (
    BusinessRef,
    ExistingReviewAction,
    Preparation,
    WorkflowContext,
    WorkflowRepository,
    validate_workflow_values,
)
from ..contracts.workflow_coordination import BusinessReceiptReader
from ..contracts.workflow_media_writes import (
    DeletePhoto,
    EditPdf,
    EditPhoto,
    MediaWorkflowWritePort,
    PrepareMediaReview,
    RemovePhoto,
    RetirePhoto,
    TombstonePdf,
)
from ..contracts.workflow_persistence import WorkflowWriteBinding
from ..domain.errors import NotFoundError, ProviderUnavailableError, StaleVersionError, ValidationError
from .assistant_capabilities.media_drafts import MediaDrafts
from .preferences import PreferenceService
from .workflow_media_cleanup import MediaCleanupVerificationService


class MediaReviewTransactions:
    def __init__(
        self,
        *,
        writes: MediaWorkflowWritePort,
        tasks: WorkflowRepository,
        receipts: BusinessReceiptReader,
        preferences: PreferenceService,
    ):
        self._writes, self._tasks, self._receipts = writes, tasks, receipts
        self._preferences = preferences

    def _context(self, task):
        prefs = self._preferences.get(task.owner)
        return WorkflowContext(
            owner=task.owner,
            task_id=task.id,
            revision=task.revision,
            capability_id=task.capability_id,
            language=prefs.preferred_language,
            timezone=prefs.timezone,
            save_mode=task.save_mode,
        )

    def prepare(self, task, expected_revision, action_key, run_binding=None):
        if task.capability_id not in self.capability_ids or task.save_mode != "allowed":
            raise ValidationError("Use the saved media workflow")
        ref = BusinessRef(kind="media_review", id=action_key, version=1)
        prior = self._writes.lookup(task.owner, action_key)
        if prior is not None:
            if (
                prior.task_id != task.id
                or prior.capability_id != task.capability_id
                or prior.outcome != "prepared"
                or prior.binding_revision != expected_revision + 1
                or prior.business_ref != ref
            ):
                raise StaleVersionError("Media preparation belongs to another scope")
            return prior
        if task.revision != expected_revision:
            raise StaleVersionError("Media draft changed before preparation")
        b = WorkflowWriteBinding(
            task_id=task.id,
            task_revision=expected_revision,
            capability_id=task.capability_id,
            action_key=action_key,
            prepared_ref=ref,
            expected_domain_revision=self._writes.revision(task.owner),
            run_binding=run_binding,
        )
        actual = self._writes.prepare(task.owner, PrepareMediaReview(binding=b)).receipt
        if (
            actual.owner != task.owner
            or actual.task_id != task.id
            or actual.capability_id != task.capability_id
            or actual.action_key != action_key
            or actual.business_ref != ref
            or actual.outcome != "prepared"
            or actual.binding_revision != expected_revision + 1
        ):
            raise StaleVersionError("Actual media preparation differs from this task")
        return actual

    def _preparation(self, task, revision):
        rows = [
            r
            for r in self._receipts.task_receipts(task.owner, task.id)
            if r.capability_id == task.capability_id
            and r.outcome == "prepared"
            and r.binding_revision == revision
            and r.business_ref.kind == "media_review"
        ]
        if len(rows) != 1:
            raise StaleVersionError("Current independent media review unavailable")
        return rows[0]

    def _applied(self, task):
        rows = [
            r
            for r in self._receipts.task_receipts(task.owner, task.id)
            if r.capability_id == task.capability_id
            and r.outcome == "applied"
            and r.binding_revision <= task.revision
            and task.business_refs == (r.business_ref,)
        ]
        if len(rows) != 1:
            raise StaleVersionError("Actual native media receipt unavailable")
        return rows[0]


class MediaWorkflowTransactions(MediaReviewTransactions):
    commands = {
        "gallery.photo.edit": EditPhoto,
        "gallery.photo.remove": RemovePhoto,
        "gallery.photo.delete": DeletePhoto,
        "gallery.photo.retire": RetirePhoto,
        "library.pdf.edit": EditPdf,
        "library.pdf.delete": TombstonePdf,
    }
    capability_ids = frozenset(commands)

    def __init__(
        self,
        *,
        writes: MediaWorkflowWritePort,
        tasks: WorkflowRepository,
        receipts: BusinessReceiptReader,
        drafts: MediaDrafts,
        preferences: PreferenceService,
        cleanup_services: dict[str, MediaCleanupVerificationService] | None = None,
    ):
        super().__init__(writes=writes, tasks=tasks, receipts=receipts, preferences=preferences)
        self._drafts = drafts
        self.cleanup_services = dict(cleanup_services or {})

    def _command(self, task, prep):
        values = validate_workflow_values(task.capability_id, task.fields)
        b = WorkflowWriteBinding(
            task_id=task.id,
            task_revision=prep.binding_revision,
            capability_id=task.capability_id,
            action_key=uuid5(prep.business_ref.id, "media-patient-confirmation"),
            prepared_ref=prep.business_ref,
            expected_domain_revision=prep.domain_revision,
        )
        return self.commands[task.capability_id](binding=b, values=values, confirmed=True)

    def confirmation_command(self, owner, task_id, revision):
        task = self._tasks.get(owner, task_id)
        if task.capability_id not in self.capability_ids or task.save_mode != "allowed" or task.state == "suspended":
            raise StaleVersionError("Use the current saved patient media review")
        if task.state in {"completed", "outcome_unknown"}:
            receipt = self._applied(task)
            prep_revision = receipt.binding_revision - 1
            if revision not in {prep_revision, task.revision}:
                raise StaleVersionError("Refresh the current media result")
        else:
            prep_revision = revision
        return self._command(task, self._preparation(task, prep_revision))

    def apply_native(self, owner, task_id, revision, allowed, target, payload, confirmed):
        cmd = self.confirmation_command(owner, task_id, revision)
        task = self._tasks.get(owner, task_id)
        if task.capability_id not in allowed:
            raise StaleVersionError("Patient endpoint differs from this media workflow")
        expected_target = cmd.values.image_id if task.capability_id.startswith("gallery.") else cmd.values.file_id
        expected = self._drafts.payload(self._context(task), cmd.values)
        if (
            target != expected_target
            or confirmed is not True
            or json.dumps(payload, sort_keys=True) != json.dumps(expected, sort_keys=True)
        ):
            raise StaleVersionError("Confirm the exact media target and reviewed fields")
        result = self._writes.apply(owner, cmd)
        if cmd.kind in {"delete_photo", "tombstone_pdf"}:
            # Even response recovery must check the independent settlement, not
            # infer physical deletion from metadata cleanup_pending=False alone.
            cleanup = self.cleanup_services.get(task.capability_id)
            if cleanup is None:
                raise ProviderUnavailableError("Native deletion saved; independent cleanup verification is pending")
            result = cleanup.cleanup(owner, cmd.binding.action_key)
        return {"deleted": True} if cmd.kind == "tombstone_pdf" else result.result

    def project(self, task):
        if task.state in {"completed", "outcome_unknown"}:
            receipt = self._applied(task)
            try:
                cmd = self._command(task, self._preparation(task, receipt.binding_revision - 1))
                if cmd.binding.action_key != receipt.action_key:
                    raise StaleVersionError("Media confirmation differs from its receipt")
                actual = self._writes.read(task.owner, cmd)
                if actual.receipt != receipt:
                    raise StaleVersionError("Actual media read has another receipt")
                visible = {"saved_record": self._drafts.visible(actual.result)}
                if task.state == "outcome_unknown" and cmd.kind in {"delete_photo", "tombstone_pdf"}:
                    visible["media_review"] = self._drafts.review(self._context(task), cmd.values, partial_cleanup=True)
            except (NotFoundError, ProviderUnavailableError, StaleVersionError):
                visible = {"actual_result_available": False}
            return Preparation(
                input_fields=task.fields,
                result_ref=receipt.business_ref,
                workflow_state=task.state,
                prompt_key="assistant.media.completed"
                if task.state == "completed" and "saved_record" in visible
                else "assistant.media.check_result",
                view_fields=visible,
                actions=(
                    ExistingReviewAction(
                        component_key="existing_media_management",
                        owned_ref=receipt.business_ref,
                        expected_version=receipt.business_ref.version,
                    ),
                )
                if "media_review" in visible
                else (),
            )
        if task.state != "awaiting_confirmation" or not task.business_refs:
            return None
        ref = task.business_refs[0]
        try:
            prep = self._preparation(task, task.revision)
            if prep.business_ref != ref or prep.domain_revision != self._writes.revision(task.owner):
                raise StaleVersionError("Current media inputs changed after review")
            values = validate_workflow_values(task.capability_id, task.fields)
            review = self._drafts.review(self._context(task), values)
        except (NotFoundError, StaleVersionError, ValidationError):
            return Preparation(
                input_fields=task.fields,
                result_ref=ref,
                workflow_state="failed_recoverable",
                prompt_key="assistant.media.changed",
            )
        return Preparation(
            input_fields=task.fields,
            result_ref=ref,
            workflow_state="awaiting_confirmation",
            prompt_key="assistant.media.patient_review",
            view_fields={"media_review": review},
            actions=(
                ExistingReviewAction(component_key="existing_media_management", owned_ref=ref, expected_version=1),
            ),
        )
