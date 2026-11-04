"""Pure photo check preparation; processing is an independent explicit request."""

from ...contracts.assistant_workflows import ChoiceAction, ChoiceOption, OperationResult, Preparation
from ...contracts.enums import RegimenState
from ...contracts.image_comparison import CompareFields
from ...domain.errors import NotFoundError, ValidationError


class ImageCompareAdapter:
    def __init__(self, *, enrollment, attachments):
        self.enrollment, self.attachments = enrollment, attachments

    def original(self, context, values, assets):
        selected = values.source_attachment_id or (assets[0].id if len(assets) == 1 else None)
        if selected is None:
            return None
        if selected not in {row.id for row in assets}:
            raise NotFoundError("Original not found in this patient task")
        return self.attachments.comparison_original(context.owner, context.task_id, selected)

    def selected(self, owner, values):
        if values.regimen_id is None:
            return None
        regimen = self.enrollment.get_regimen(owner, values.regimen_id)
        if regimen is None:
            raise NotFoundError("Selected regimen not found for this patient")
        if regimen.state != RegimenState.ACTIVE:
            raise ValidationError("Select a current reviewed active regimen")
        med = self.enrollment.get_medication(owner, regimen.patient_medication_id)
        if med is None:
            raise NotFoundError("Medication not found for this patient")
        return med.display_name

    def prepare(self, context, values, assets, results=()):
        if not isinstance(values, CompareFields) or results:
            raise ValidationError("Use the typed image check without a business result")
        name = self.selected(context.owner, values)
        inputs = values.model_dump(mode="json", exclude_none=True)
        original = self.original(context, values, assets) if context.save_mode == "allowed" else None
        if context.save_mode == "ephemeral":
            inputs.pop("source_attachment_id", None)
        elif original:
            inputs["source_attachment_id"] = str(original.id)
        meds = self.enrollment.list_medications(context.owner) if values.intent == "personal" else []
        plans = [(med, self.enrollment.find_active_regimen(context.owner, med.id)) for med in meds]
        plans = [(med, plan) for med, plan in plans if plan is not None and plan.state == RegimenState.ACTIVE]
        pages = max(1, (len(plans) + 9) // 10)
        page = values.page if values.page < pages else 0
        actions = [ChoiceAction(action_id="compare.intent", options=(
            ChoiceOption(value="personal", label_key="assistant.compare.personal"),
            ChoiceOption(value="identify", label_key="assistant.compare.identify"),
        ))]
        if values.intent == "personal":
            actions.append(ChoiceAction(action_id="compare.regimen", options=(
                ChoiceOption(value="all", label_key="assistant.compare.all"),
                *(ChoiceOption(value=str(plan.id), label_key="assistant.compare.select",
                               label_text=med.display_name[:200])
                  for med, plan in plans[page * 10:(page + 1) * 10]),
            )))
        missing = ("source_image",) if context.save_mode == "allowed" and original is None else ()
        return Preparation(input_fields=inputs, missing_fields=missing,
                           workflow_state="collecting" if missing else "ready_for_review",
                           prompt_key="assistant.compare.collect" if missing else "assistant.compare.ready",
                           view_fields={"selected_medication": name, "page": page, "page_count": pages,
                                        "originals": [{"id": str(row.id)} for row in assets]}, actions=tuple(actions))

    def observe(self, context, result_ref):
        return OperationResult(state="failed", reason="comparison_results_are_page_only")
