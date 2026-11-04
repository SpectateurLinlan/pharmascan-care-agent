"""Idempotent unactivated draft preparation over the existing clinical use case."""

import hashlib
import json
from uuid import UUID

from ..contracts.dto import EnrollmentResultDTO
from ..contracts.enrollment_operations import (
    EnrollmentOperationInput,
    EnrollmentRecordRef,
    EnrollmentWritePort,
    PlanChangeOperationInput,
    PreparedEnrollment,
)
from ..contracts.enrollment_workflow import EnrollmentFields
from ..contracts.enums import SourceKind
from ..contracts.medication_evidence import EnrollmentTask
from ..contracts.medication_plan_changes import PlanChangeDetails, PlanChangePreview, PlanTargetState
from ..contracts.workflow_attachments import WorkflowEnrollmentSource
from ..domain.enrollment_inputs import normalise_enrollment_name
from ..domain.errors import DuplicateEventError, NotFoundError, StaleVersionError, ValidationError
from .enrollment import MedicationEnrollmentService
from .enrollment_preview import EnrollmentPreviewService
from .evidence_enrollment import EvidenceEnrollmentService


class EnrollmentOperationService:
    def __init__(self, enrollment: MedicationEnrollmentService, writer: EnrollmentWritePort):
        self._enrollment, self._writer = enrollment, writer
        self._preview = EnrollmentPreviewService(enrollment)

    def lookup(self, owner: UUID, action_key: UUID) -> EnrollmentResultDTO | None:
        receipt = self._writer.lookup(owner, action_key)
        return self._enrollment.read_enrollment_result(owner, receipt.regimen_id) if receipt else None

    def receipt(self, owner: UUID, action_key: UUID) -> EnrollmentRecordRef | None:
        return self._writer.lookup(owner, action_key)

    def binding(self, owner: UUID, regimen_id: UUID) -> EnrollmentRecordRef | None:
        return self._writer.for_regimen(owner, regimen_id)

    def plan_change_preview(
        self,
        owner: UUID,
        predecessor_id: UUID,
        expected_version: int,
        expected_state: PlanTargetState,
        details: PlanChangeDetails | None,
    ) -> PlanChangePreview:
        target = self._enrollment.get_regimen(owner, predecessor_id)
        if target is None:
            raise NotFoundError("Medication plan not found")
        if target.version_no != expected_version or target.state.value != expected_state:
            raise StaleVersionError("The recorded plan changed; select its current version")
        if target.state.value not in {"active", "ended", "superseded"}:
            raise ValidationError("Continue the unfinished draft instead of changing it as a recorded plan")
        base = self._enrollment.review_inputs(owner, target.id).model_dump(mode="json", exclude_none=True)
        # Editing instructions does not replace product identity or manufacture
        # a fresh photo authority. The original source and its strength stay intact.
        base.update(method="manual", dose_basis=None)
        rule = base.get("frequency_rule")
        if rule and rule.get("kind") == "interval":
            default = (rule.get("interval_anchor") or {}).get("time_source") == "default_0800"
            base["frequency_rule"] = {
                **rule,
                "local_times": [] if default else rule.get("local_times", []),
                "interval_anchor": None,
            }
        changes = details.model_dump(mode="json") if details is not None else {}
        fields = EnrollmentFields.model_validate({**base, **changes})
        preview = self._preview.preview_enrollment(owner, fields)
        original_rule = target.frequency_rule or None
        normalized = preview.normalized_draft
        compare = (
            "dose_amount",
            "dose_unit",
            "is_prn",
            "route",
            "food_instruction",
            "course_start_date",
            "course_end_date",
        )
        if normalized:
            changed = (
                any(getattr(normalized, name) != getattr(target, name) for name in compare)
                or (normalized.frequency_rule.model_dump(mode="json") if normalized.frequency_rule else None)
                != original_rule
            )
        else:
            changed = bool(changes)
        return PlanChangePreview(target=target, fields=fields, preview=preview, changed=changed)

    def prepare_plan_change_once(self, owner: UUID, values: PlanChangeOperationInput) -> EnrollmentResultDTO:
        digest = hashlib.sha256(json.dumps(values.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
        prior = self._writer.lookup(owner, values.action_key)
        if prior is not None:
            if prior.binding_digest != digest:
                raise DuplicateEventError("Plan change action key is bound to different inputs")
            return self._enrollment.read_enrollment_result(owner, prior.regimen_id)
        revision = self._writer.revision(owner)
        proposed = self.plan_change_preview(
            owner, values.predecessor_id, values.expected_version, values.expected_state, values.fields
        )
        if not proposed.changed:
            raise ValidationError("Enter the changed instructions before preparing a new plan version")
        if proposed.preview.missing_fields or proposed.preview.conflicts or proposed.preview.normalized_draft is None:
            raise ValidationError("Complete and check the changed dose and schedule instructions")
        draft = proposed.preview.normalized_draft.model_copy(
            update={
                "patient_edited": True,
                "supersedes_regimen_id": proposed.target.id if proposed.target.state.value == "active" else None,
            }
        )
        prepared = self._enrollment.prepare_draft(
            patient_id=owner, draft=draft, existing_medication_id=proposed.target.patient_medication_id
        )
        prepared = prepared.model_copy(
            update={"workflow_task_id": values.workflow_task_id, "workflow_revision": values.workflow_revision}
        )
        receipt = self._writer.create_once(owner, values.action_key, digest, prepared, expected_revision=revision)
        return self._enrollment.read_enrollment_result(owner, receipt.regimen_id)

    def bind_source_once(
        self,
        owner: UUID,
        source_task: EnrollmentTask,
        *,
        action_key: UUID,
        workflow_task_id: UUID,
        workflow_revision: int,
    ) -> EnrollmentRecordRef:
        if source_task.patient_id != owner or source_task.draft_regimen_id is None:
            raise ValidationError("The source review has no owned prepared plan")
        actual = self._enrollment.resume_draft(owner, source_task.draft_regimen_id)
        if actual.regimen.evidence_task_id != source_task.id or actual.medication.id != source_task.medication_id:
            raise ValidationError("The prepared plan does not belong to this source registration")
        return self.bind_existing_once(
            owner,
            actual.regimen.id,
            actual.regimen.version_no,
            action_key=action_key,
            workflow_task_id=workflow_task_id,
            workflow_revision=workflow_revision,
        )

    def bind_existing_once(
        self,
        owner: UUID,
        regimen_id: UUID,
        version: int,
        *,
        action_key: UUID,
        workflow_task_id: UUID,
        workflow_revision: int,
    ) -> EnrollmentRecordRef:
        """Associate an unbound unfinished draft without changing its clinical facts."""
        digest = hashlib.sha256(f"resume:{regimen_id}:{version}:{workflow_task_id}".encode()).hexdigest()
        prior = self._writer.lookup(owner, action_key)
        if prior:
            if prior.binding_digest != digest:
                raise DuplicateEventError("Recovery receipt is bound to different inputs")
            return prior
        revision = self._writer.revision(owner)
        result = self._enrollment.resume_draft(owner, regimen_id)
        if result.regimen.version_no != version:
            raise ValidationError("Draft version changed")
        source = self._enrollment.get_source(owner, result.regimen.source_id)
        if source is None:
            raise ValidationError("The original source is unavailable")
        prepared = PreparedEnrollment(
            workflow_task_id=workflow_task_id,
            workflow_revision=workflow_revision,
            source=source,
            result=result,
            create_medication=False,
            already_persisted=True,
        )
        return self._writer.create_once(owner, action_key, digest, prepared, expected_revision=revision)

    def prepare_once(self, owner: UUID, values: EnrollmentOperationInput) -> EnrollmentResultDTO:
        if values.fields.method != "manual":
            raise ValidationError("Photo enrollment needs verified source preparation")
        return self._prepare_once(owner, values)

    def prepare_from_attachment(
        self, owner: UUID, values: EnrollmentOperationInput, source: WorkflowEnrollmentSource
    ) -> EnrollmentResultDTO:
        if (
            source.owner != owner
            or source.task_id != values.workflow_task_id
            or source.attachment_id != values.fields.source_attachment_id
        ):
            raise ValidationError("The photo source does not belong to this enrollment")
        EvidenceEnrollmentService.validate_workflow_fields(source.extraction, values.fields)
        return self._prepare_once(owner, values, source)

    def _prepare_once(
        self, owner: UUID, values: EnrollmentOperationInput, source: WorkflowEnrollmentSource | None = None
    ) -> EnrollmentResultDTO:
        binding = {
            "input": values.model_dump(mode="json"),
            "original_checksum": source.original_checksum if source else None,
        }
        digest = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
        prior = self._writer.lookup(owner, values.action_key)
        if prior:
            if prior.binding_digest != digest:
                raise DuplicateEventError("Enrollment action key is bound to different inputs")
            return self._enrollment.read_enrollment_result(owner, prior.regimen_id)
        revision = self._writer.revision(owner)
        preview = self._preview.preview_enrollment(owner, values.fields)
        if preview.conflicts or values.fields.draft is None:
            raise ValidationError("Resolve the medication name or record choice before preparing a draft")
        draft = values.fields.draft
        if values.fields.existing_medication_id:
            owned = self._enrollment.get_medication(owner, values.fields.existing_medication_id)
            if owned is None or normalise_enrollment_name(owned.display_name) != normalise_enrollment_name(
                draft.medication_name
            ):
                raise ValidationError("The selected owned product name changed")
            draft = draft.model_copy(update={"medication_name": owned.display_name})
        prepared = self._enrollment.prepare_draft(
            source_kind=SourceKind(source.source_kind) if source else SourceKind.USER_MANUAL,
            extraction_evidence=source.extraction.model_copy(
                update={"candidates": [source.extraction.candidates[values.fields.source_candidate_index]]}
            )
            if source
            else None,
            patient_id=owner,
            draft=draft,
            dose_basis=values.fields.dose_basis,
            existing_medication_id=values.fields.existing_medication_id,
            evidence_task_id=values.evidence_task_id,
        )
        prepared = prepared.model_copy(
            update={
                "workflow_task_id": values.workflow_task_id,
                "workflow_revision": values.workflow_revision,
                "attachment_ids": (source.attachment_id,) if source else (),
                "source_candidate_index": values.fields.source_candidate_index if source else None,
            }
        )
        receipt = self._writer.create_once(owner, values.action_key, digest, prepared, expected_revision=revision)
        return self._enrollment.read_enrollment_result(owner, receipt.regimen_id)
