"""Pure local name preparation; task reads never contact knowledge providers."""

from ...contracts.assistant_workflows import AttachmentRef, BusinessRef, OperationResult, Preparation, WorkflowContext
from ...contracts.knowledge_workflow import KnowledgeFields
from ...contracts.medication_names import NameQuery
from ...domain.errors import ValidationError
from ..medication_names import MedicationNameResolver


class KnowledgeAdapter:
    def __init__(self, *, resolver: MedicationNameResolver):
        self.resolver = resolver

    def prepare(
        self,
        context: WorkflowContext,
        values: KnowledgeFields,
        assets: tuple[AttachmentRef, ...],
        results: tuple[BusinessRef, ...] = (),
    ) -> Preparation:
        if assets or results or context.capability_id != "medication.knowledge":
            raise ValidationError("General knowledge accepts a medicine name, never a patient write or result")
        inputs = values.model_dump(mode="json", exclude_none=True)
        if not values.medication_name:
            return Preparation(
                input_fields=inputs, prompt_key="assistant.knowledge.name", missing_fields=("medication_name",)
            )
        resolution = self.resolver.resolve(NameQuery(text=values.medication_name, purpose="general_use"), ())
        return Preparation(
            input_fields=inputs,
            workflow_state="ready_for_review",
            prompt_key="assistant.knowledge.confirm_name"
            if resolution.status in {"needs_confirmation", "ambiguous"}
            else "assistant.knowledge.ready",
            view_fields={
                "medication_name": values.medication_name,
                "name_resolution": resolution.model_dump(mode="json"),
            },
        )

    def observe(self, context, result_ref):
        return OperationResult(state="failed", reason="knowledge_results_are_page_only")
