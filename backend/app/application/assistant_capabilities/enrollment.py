"""Enrollment collection; existing services retain review/activation authority."""

from uuid import UUID

from pydantic import JsonValue
from pydantic import ValidationError as SchemaValidationError

from ...contracts.assistant_workflows import (
    AttachmentRef,
    BusinessRef,
    ChoiceAction,
    ChoiceOption,
    ExistingReviewAction,
    FieldFormAction,
    OperationResult,
    Preparation,
    UploadAction,
    WorkflowContext,
)
from ...contracts.enrollment_operations import EnrollmentOperationInput
from ...contracts.enrollment_workflow import EnrollmentFields
from ...contracts.workflow_attachments import WorkflowEnrollmentSource
from ...domain.errors import NotFoundError, ValidationError
from ..enrollment import MedicationEnrollmentService
from ..enrollment_operations import EnrollmentOperationService
from ..enrollment_preview import EnrollmentPreviewService
from ..evidence_enrollment import EvidenceEnrollmentService
from ..workflow_attachments import WorkflowAttachmentService


class EnrollmentAdapter:
    def __init__(
        self,
        enrollment: MedicationEnrollmentService,
        operations: EnrollmentOperationService | None = None,
        attachments: WorkflowAttachmentService | None = None,
    ):
        self._enrollment = enrollment
        self._preview = EnrollmentPreviewService(enrollment)
        self._operations = operations
        self._attachments = attachments

    def prepare(
        self,
        context: WorkflowContext,
        values: EnrollmentFields,
        assets: tuple[AttachmentRef, ...],
        results: tuple[BusinessRef, ...] = (),
    ) -> Preparation:
        if results:
            ref = next((row for row in results if row.kind == "regimen"), None)
            regimen = self._enrollment.get_regimen(context.owner, ref.id) if ref else None
            if regimen is None or ref.version != regimen.version_no:
                return Preparation(
                    workflow_state="failed_recoverable",
                    prompt_key="assistant.enrollment.result_changed",
                    result_ref=ref,
                )
            fields = self._enrollment.review_inputs(context.owner, ref.id).model_dump(mode="json", exclude_none=True)
            if regimen.state.value == "active":
                return Preparation(
                    workflow_state="completed",
                    prompt_key="assistant.enrollment.completed",
                    view_fields=fields,
                    result_ref=ref,
                )
            if regimen.state.value not in {"draft", "pending_clarification"}:
                return Preparation(
                    workflow_state="failed_recoverable",
                    prompt_key="assistant.enrollment.result_changed",
                    view_fields=fields,
                    result_ref=ref,
                )
            return Preparation(
                workflow_state="awaiting_confirmation",
                prompt_key="assistant.enrollment.patient_review",
                view_fields=fields,
                result_ref=ref,
                actions=(
                    ExistingReviewAction(
                        component_key="existing_activation", owned_ref=ref, expected_version=regimen.version_no
                    ),
                ),
            )
        visible = values.model_dump(mode="json", exclude_none=True)
        if values.method is None:
            return Preparation(
                view_fields=visible,
                missing_fields=("method",),
                workflow_state="choose_method",
                prompt_key="assistant.enrollment.choose_method",
                actions=(
                    ChoiceAction(
                        action_id="enrollment.method",
                        options=(
                            ChoiceOption(value="manual", label_key="assistant.enrollment.manual"),
                            ChoiceOption(value="photo", label_key="assistant.enrollment.photo"),
                        ),
                    ),
                ),
            )
        page_preview = context.save_mode == "ephemeral" and values.page_photo_previewed
        if values.method == "photo" and not assets and not page_preview:
            return Preparation(
                view_fields=visible,
                missing_fields=("source_image",),
                prompt_key="assistant.enrollment.upload_source",
                actions=(
                    UploadAction(
                        action_id="source_image",
                    ),
                ),
            )
        if values.method == "photo" and assets:
            if all(asset.extraction_status == "failed" for asset in assets):
                return Preparation(
                    view_fields=visible,
                    missing_fields=("source_extraction",),
                    workflow_state="failed_recoverable",
                    prompt_key="assistant.enrollment.extraction_failed",
                    actions=(UploadAction(action_id="source_image"),),
                )
            if not any(asset.extraction_status == "succeeded" for asset in assets):
                return Preparation(
                    view_fields=visible,
                    missing_fields=("processing_consent",),
                    prompt_key="assistant.enrollment.processing_consent",
                    actions=(UploadAction(action_id="source_image"),),
                )
            if self._attachments is None:
                raise ValidationError("Source preparation is unavailable")
            sources = [
                self._attachments.enrollment_source(context.owner, context.task_id, asset.id)
                for asset in assets
                if asset.extraction_status == "succeeded"
            ]
            if any(len(row.extraction.candidates) > 20 for row in sources):
                return Preparation(
                    view_fields=visible,
                    missing_fields=("source_product_limit",),
                    workflow_state="failed_recoverable",
                    prompt_key="assistant.enrollment.too_many_products",
                    actions=(UploadAction(action_id="source_image"),),
                )
            selected = next((row for row in sources if row.attachment_id == values.source_attachment_id), None)
            if selected is None and values.source_attachment_id is not None:
                raise ValidationError("Choose an original belonging to the current task")
            if selected is None and len(sources) == 1 and len(sources[0].extraction.candidates) == 1:
                selected = sources[0]
            if selected is None or len(selected.extraction.candidates) != 1 and values.source_candidate_index is None:
                options = tuple(
                    ChoiceOption(
                        value=f"{row.attachment_id}:{index}",
                        label_key="assistant.enrollment.source_product",
                        label_text=(
                            f"{candidate.product.name[:130]} {candidate.product.strength or ''} — {position + 1}"
                        )[:200],
                    )
                    for position, row in enumerate(sources)
                    for index, candidate in enumerate(row.extraction.candidates)
                )
                if not options:
                    return Preparation(
                        view_fields=visible,
                        workflow_state="failed_recoverable",
                        missing_fields=("source_extraction",),
                        prompt_key="assistant.enrollment.extraction_failed",
                        actions=(UploadAction(action_id="source_image"),),
                    )
                return Preparation(
                    view_fields=visible,
                    missing_fields=("source_product_choice",),
                    prompt_key="assistant.enrollment.choose_source_product",
                    actions=tuple(
                        ChoiceAction(action_id="enrollment.source_product", options=options[start : start + 10])
                        for start in range(0, len(options), 10)
                    ),
                )
            try:
                values = self._photo_fields(values, selected)
            except (ValidationError, SchemaValidationError):
                return Preparation(
                    view_fields=visible,
                    workflow_state="failed_recoverable",
                    missing_fields=("source_extraction",),
                    prompt_key="assistant.enrollment.extraction_failed",
                    actions=(UploadAction(action_id="source_image"),),
                )
            visible = values.model_dump(mode="json", exclude_none=True)
        preview = self._preview.preview_enrollment(context.owner, values)
        if {
            "possible_duplicate_medication",
            "stale_medication_selection",
            "distinct_product_not_verified",
        }.intersection(preview.conflicts):
            sources = {
                row.id: row
                for row in self._enrollment.get_sources(
                    context.owner, [row.source_id for row in preview.medication_candidates if row.source_id]
                )
            }
            options = []
            for row in preview.medication_candidates:
                source = sources.get(row.source_id)
                strength = source.dose_basis.strength_text if source and source.dose_basis else ""
                detail = f" — {strength}" if strength else ""
                # Same names need a stable record discriminator even without recorded strength.
                if len(preview.medication_candidates) > 1:
                    detail += f" [{str(row.id)[-12:]}]"
                options.append(
                    ChoiceOption(
                        value=str(row.id),
                        label_key="assistant.enrollment.reuse_existing",
                        label_text=f"{row.display_name[:140]}{detail}"[:200],
                    )
                )
            different = ChoiceOption(value="different_product", label_key="assistant.enrollment.different_product")
            alternatives = (
                (ChoiceOption(value="distinct_product", label_key="assistant.enrollment.distinct_product"), different)
                if preview.distinct_product_available
                else (different,)
            )
            count = 10 - len(alternatives)
            groups = [
                tuple(options[start : start + count]) + alternatives for start in range(0, max(1, len(options)), count)
            ]
            return Preparation(
                view_fields=visible,
                missing_fields=("existing_medication_choice", *preview.missing_fields),
                prompt_key="assistant.enrollment.duplicate",
                actions=tuple(ChoiceAction(action_id="enrollment.duplicate", options=group) for group in groups),
            )
        missing = preview.missing_fields
        ready = not missing and not preview.conflicts
        return Preparation(
            view_fields=visible,
            missing_fields=missing,
            workflow_state="ready_for_review" if ready else "collecting",
            prompt_key="assistant.enrollment.provide_fields"
            if missing
            else "assistant.enrollment.duplicate"
            if preview.conflicts
            else "assistant.enrollment.interval_default"
            if preview.defaults
            else "assistant.enrollment.review_inputs",
            actions=(FieldFormAction(schema_id="medication.enroll:v1", field_names=missing),) if missing else (),
        )

    @staticmethod
    def _photo_fields(values: EnrollmentFields, source: WorkflowEnrollmentSource) -> EnrollmentFields:
        proposed = EvidenceEnrollmentService.workflow_fields(source.extraction, values.source_candidate_index)
        merged = {
            **proposed.model_dump(mode="json", exclude_none=True),
            **values.model_dump(mode="json", exclude_none=True),
        }
        merged.update(
            source_attachment_id=str(source.attachment_id), source_candidate_index=proposed.source_candidate_index
        )
        return EnrollmentFields.model_validate(merged)

    def reconcile(self, context: WorkflowContext, action_key: UUID) -> BusinessRef | None:
        binding = (
            self._operations.receipt(context.owner, action_key)
            if self._operations and context.save_mode == "allowed"
            else None
        )
        if binding is None:
            return None
        if binding is None or binding.workflow_task_id != context.task_id:
            raise ValidationError("Enrollment receipt belongs to a different task")
        return BusinessRef(kind="regimen", id=binding.regimen_id, version=binding.version_no)

    def prepare_once(
        self, context: WorkflowContext, values: EnrollmentFields, assets: tuple[AttachmentRef, ...], action_key: UUID
    ) -> BusinessRef:
        if context.save_mode != "allowed" or self._operations is None:
            raise ValidationError("Enable saving before preparing an enrollment")
        source = None
        if values.method == "photo":
            prepared = self.prepare(context, values, assets)
            values = EnrollmentFields.model_validate(prepared.view_fields)
            if values.source_attachment_id is None or self._attachments is None:
                raise ValidationError("Choose a verified original source before preparation")
            source = self._attachments.enrollment_source(
                context.owner, context.task_id, values.source_attachment_id, verify_original=True
            )
        elif values.method != "manual":
            raise ValidationError("Choose an enrollment method")
        preview = self._preview.preview_enrollment(context.owner, values)
        if preview.missing_fields or preview.conflicts:
            raise ValidationError("Complete the missing details before preparing review")
        operation = EnrollmentOperationInput(
            action_key=action_key, fields=values, workflow_task_id=context.task_id, workflow_revision=context.revision
        )
        result = (
            self._operations.prepare_from_attachment(context.owner, operation, source)
            if source
            else self._operations.prepare_once(context.owner, operation)
        )
        return BusinessRef(kind="regimen", id=result.regimen.id, version=result.regimen.version_no)

    def revise_inputs(self, context: WorkflowContext, result_ref: BusinessRef) -> dict[str, JsonValue]:
        row = self._enrollment.get_regimen(context.owner, result_ref.id)
        if (
            row is None
            or row.version_no != result_ref.version
            or row.state.value not in {"draft", "pending_clarification"}
        ):
            raise ValidationError("The prepared plan changed; its review cannot be edited")
        source = self._enrollment.get_source(context.owner, row.source_id)
        if source is None or source.reviewed_at is not None:
            raise ValidationError("Reviewed instructions are preserved. Use the plan-version workflow for changes")
        fields = self._enrollment.review_inputs(context.owner, row.id).model_dump(mode="json", exclude_none=True)
        rule = fields.get("frequency_rule")
        if isinstance(rule, dict) and (rule.get("interval_anchor") or {}).get("time_source") == "default_0800":
            fields["frequency_rule"] = {**rule, "local_times": [], "interval_anchor": None}
        binding = self._operations.binding(context.owner, row.id) if self._operations else None
        if binding and binding.attachment_ids and self._attachments:
            original = self._attachments.enrollment_source(context.owner, context.task_id, binding.attachment_ids[0])
            proposal = EvidenceEnrollmentService.workflow_fields(original.extraction, binding.source_candidate_index)
            fields.update(
                method="photo",
                source_attachment_id=str(original.attachment_id),
                source_candidate_index=proposal.source_candidate_index,
                times_per_day=proposal.times_per_day,
                printed_course_days=proposal.printed_course_days,
            )
        return fields

    def observe(self, context: WorkflowContext, result_ref: BusinessRef) -> OperationResult:
        if result_ref.kind != "regimen":
            raise ValidationError("Enrollment result must reference a regimen")
        regimen = self._enrollment.get_regimen(context.owner, result_ref.id)
        if regimen is None:
            raise NotFoundError("Enrollment result not found for this patient")
        if result_ref.version is not None and regimen.version_no != result_ref.version:
            return OperationResult(state="failed", reason="stale_regimen_version")
        return OperationResult(
            state="succeeded" if regimen.state.value == "active" else "pending",
            business_ref=result_ref,
        )
