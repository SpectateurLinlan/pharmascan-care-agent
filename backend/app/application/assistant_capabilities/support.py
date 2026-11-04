"""Static patient device/navigation actions; preparation never uses device APIs."""

from ...contracts.assistant_workflows import DeviceAction, NavigateAction, Preparation
from ...contracts.conversation_workflow import SUPPORT_SCHEMAS
from ...domain.errors import NotFoundError, ValidationError
from ..enrollment import MedicationEnrollmentService
from ..long_term import LongTermCareService


class SupportAdapter:
    capability_ids = frozenset(SUPPORT_SCHEMAS) - {"feedback.submit"}

    def __init__(self, *, enrollment: MedicationEnrollmentService, care: LongTermCareService):
        self.enrollment, self.care = enrollment, care

    def prepare(self, context, values, assets, results=()):
        if assets or results or context.capability_id not in self.capability_ids:
            raise ValidationError("Use a current patient support action")
        name = context.capability_id
        inputs = values.model_dump(mode="json", exclude_none=True)
        visible = {}
        if name.startswith("speech."):
            action = DeviceAction(action="microphone" if name == "speech.input" else "speech_playback")
        elif name in {"help.open", "guide.start"}:
            action = NavigateAction(route="help")
        elif values.destination is None:
            return Preparation(input_fields=inputs, missing_fields=("destination",),
                               prompt_key="assistant.support.destination")
        else:
            action = values.destination
            query = {}
            if values.regimen_id:
                if action.route not in {"medicine-detail", "medicine-history", "edit-medication", "check"}:
                    raise ValidationError("This destination does not accept a regimen")
                if self.enrollment.get_regimen(context.owner, values.regimen_id) is None:
                    raise NotFoundError("The selected medication plan is unavailable")
                query["id"] = str(values.regimen_id)
            if values.medication_id:
                if action.route not in {"gallery", "medication-inventory"} or query:
                    raise ValidationError("This destination does not accept this medication")
                if self.enrollment.get_medication(context.owner, values.medication_id) is None:
                    raise NotFoundError("The selected medication is unavailable")
                query["id"] = str(values.medication_id)
            if values.care_task_id:
                if action.route != "care-tasks" or query:
                    raise ValidationError("This destination does not accept a follow-up target")
                if not any(row.id == values.care_task_id for row in self.care.tasks(context.owner)):
                    raise NotFoundError("The selected follow-up is unavailable")
                query["task"] = str(values.care_task_id)
            visible["navigation_query"] = query
        return Preparation(input_fields=inputs, prompt_key="assistant.support.patient_action",
                           view_fields=visible, actions=(action,))

    def observe(self, context, result_ref):
        raise ValidationError("This action has no application business result")
