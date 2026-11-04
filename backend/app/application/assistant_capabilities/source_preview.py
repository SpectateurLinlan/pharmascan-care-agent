"""Prepare source type and owned raw original without running extraction."""

from ...contracts.assistant_workflows import ChoiceAction, ChoiceOption, OperationResult, Preparation
from ...contracts.source_preview_workflow import SourcePreviewFields
from ...domain.errors import NotFoundError, ValidationError


class SourcePreviewAdapter:
    def __init__(self, *, attachments):
        self.attachments = attachments

    def original(self, context, values, assets):
        selected = values.source_attachment_id or (assets[0].id if len(assets) == 1 else None)
        if selected is None:
            return None
        if selected not in {row.id for row in assets}:
            raise NotFoundError("Original not found in this patient task")
        return self.attachments.preview_original(context.owner, context.task_id, selected)

    def prepare(self, context, values, assets, results=()):
        if not isinstance(values, SourcePreviewFields) or results:
            raise ValidationError("Source preview has no business result or reviewed instructions")
        inputs = values.model_dump(mode="json", exclude_none=True)
        original = self.original(context, values, assets) if context.save_mode == "allowed" else None
        if context.save_mode == "ephemeral":
            inputs.pop("source_attachment_id", None)
        elif original:
            inputs["source_attachment_id"] = str(original.id)
        missing = ("source_image",) if context.save_mode == "allowed" and original is None else ()
        return Preparation(input_fields=inputs, missing_fields=missing,
                           workflow_state="collecting" if missing else "ready_for_review",
                           prompt_key="assistant.source_preview.collect" if missing
                           else "assistant.source_preview.ready",
                           view_fields={"originals": [{"id": str(row.id)} for row in assets]}, actions=(
                               ChoiceAction(action_id="preview.source_kind", options=(
                                   ChoiceOption(value="pharmacy_label", label_key="assistant.preview.label"),
                                   ChoiceOption(value="package", label_key="assistant.preview.package"),
                                   ChoiceOption(value="prescription", label_key="assistant.preview.prescription"),
                               )),
                           ))

    def observe(self, context, result_ref):
        return OperationResult(state="failed", reason="source_preview_results_are_page_only")
