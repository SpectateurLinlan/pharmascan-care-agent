"""Typed projection of a care draft through existing public contracts."""

from datetime import timedelta
from uuid import UUID

from ...contracts.assistant_workflows import WorkflowContext
from ...contracts.care_workflow import CARE_CHANGE_STATUS
from ...contracts.long_term import BarrierInput, CareReview, CareTaskInput, StockInput, TaskUpdate
from ...contracts.observations import ObservationInput
from ...contracts.ports import Clock
from ...domain.errors import NotFoundError, StaleVersionError, ValidationError
from ..enrollment import MedicationEnrollmentService
from ..long_term import LongTermCareService
from ..observations import ObservationService


class CareDrafts:
    def __init__(
        self,
        *,
        enrollment: MedicationEnrollmentService,
        observations: ObservationService,
        care: LongTermCareService,
        clock: Clock,
    ):
        self.enrollment, self.observations, self.care, self.clock = enrollment, observations, care, clock

    def task(self, owner, task_id):
        row = next((row for row in self.care.tasks(owner) if row.id == task_id), None)
        if row is None:
            raise NotFoundError("Follow-up not found for this patient")
        return row

    def associations(self, owner, values):
        medicine = getattr(values, "medication_id", None)
        regimen = getattr(values, "regimen_id", None)
        if medicine and self.enrollment.get_medication(owner, medicine) is None:
            raise NotFoundError("Medication not found for this patient")
        if regimen:
            plan = self.enrollment.get_regimen(owner, regimen)
            if plan is None:
                raise NotFoundError("Regimen not found for this patient")
            if medicine and plan.patient_medication_id != medicine:
                raise ValidationError("Regimen and medication do not agree")
        followup = getattr(values, "follow_up_task_id", None)
        if followup:
            self.task(owner, followup)

    def missing(self, context, values):
        capability = context.capability_id
        required = {
            "observation.add": ["description", "occurred_at"],
            "observation.delete": ["observation_id"],
            "observation.edit": ["observation_id", "description", "occurred_at"],
            "inventory.count": ["medication_id", "quantity", "unit"],
            "inventory.view": ["medication_id"],
            "barrier.add": ["category", "occurred_at"],
            "followup.add": ["title", "due_at"],
            **dict.fromkeys((*CARE_CHANGE_STATUS, "followup.edit"), ["task_id", "expected_version"]),
        }.get(capability, [])
        if capability in {"observation.add", "observation.edit"} and values.kind != "note":
            required += ["value", "unit"]
            if values.kind == "blood_pressure":
                required += ["secondary_value"]
        if capability == "followup.defer":
            required = [*required, "due_at"]
        return tuple(key for key in required if getattr(values, key, None) is None)

    def review(self, context: WorkflowContext, values, request_id: UUID):
        self.associations(context.owner, values)
        capability = context.capability_id
        raw = values.model_dump(exclude={"page"})
        target = None
        if capability in {"observation.add", "observation.edit"}:
            selected = raw.pop("observation_id", None)
            target = request_id if capability == "observation.add" else selected
            if capability == "observation.add" and selected is not None:
                raise ValidationError("Use the separate edit action to change a health note")
            if capability == "observation.edit" and self.observations.get(context.owner, target) is None:
                raise NotFoundError("Health note not found for this patient")
            body = ObservationInput(id=target, **raw)
            if body.occurred_at > self.clock.now() + timedelta(minutes=5):
                raise ValidationError("A health note cannot describe a future observation")
        elif capability == "observation.delete":
            target = values.observation_id
            if self.observations.get(context.owner, target) is None:
                raise NotFoundError("Health note not found for this patient")
            return {"target_id": str(target), "payload": {}}
        elif capability == "inventory.count":
            target = raw.pop("medication_id")
            body = StockInput(id=request_id, **raw)
        elif capability == "barrier.add":
            body = BarrierInput(id=request_id, **raw)
            if body.occurred_at > self.clock.now() + timedelta(minutes=5):
                raise ValidationError("A reported difficulty cannot be in the future")
        elif capability == "followup.add":
            body = CareTaskInput(id=request_id, **raw)
        else:
            target = raw.pop("task_id")
            previous = self.task(context.owner, target)
            if previous.version != values.expected_version:
                raise StaleVersionError("This follow-up changed; select its current version")
            raw = self.change_fields(context.owner, values, previous.notes)
            if capability != "followup.edit" and (
                values.status is not None
                or set(raw) & {"title", "category", "medication_id", "regimen_id", "reminder_minutes"}
            ):
                raise ValidationError("Use the separate edit action to change follow-up details")
            if previous.status in {"completed", "cancelled"} and capability != "followup.edit":
                raise StaleVersionError("Reopen and reschedule the follow-up before changing its status")
            status = CARE_CHANGE_STATUS.get(
                capability,
                values.status or ("open" if previous.status in {"completed", "cancelled"} else previous.status),
            )
            raw.pop("status", None)
            if (
                capability == "followup.edit"
                and previous.source == "stock_estimate"
                and set(raw) & {"title", "category"}
            ):
                raise ValidationError("Supply follow-ups keep their original medication and type")
            body = TaskUpdate(id=request_id, status=status, **raw)
            if status == "deferred" and (body.due_at is None or body.due_at <= self.clock.now()):
                raise ValidationError("Choose a future follow-up time")
        return {
            "target_id": str(target) if target else None,
            "payload": body.model_dump(
                mode="json", exclude_unset=capability.startswith("followup.") and capability != "followup.add"
            ),
        }

    def change_fields(self, owner, values, original_notes):
        raw = values.model_dump(
            exclude_none=True, exclude={"page", "task_id", "status", "clear_plan", "disable_reminder"}
        )
        raw.setdefault("notes", original_notes)
        if values.clear_plan:
            raw.update(medication_id=None, regimen_id=None)
        elif values.regimen_id:
            raw["medication_id"] = self.enrollment.get_regimen(owner, values.regimen_id).patient_medication_id
        if values.disable_reminder:
            raw["reminder_minutes"] = None
        return raw

    def care_proposal(self, capability, review):
        payload = review["payload"]
        target = UUID(review["target_id"]) if review["target_id"] else None
        if capability == "inventory.count":
            return CareReview(action="stock", medication_id=target, stock=StockInput.model_validate(payload))
        if capability == "barrier.add":
            return CareReview(action="barrier", barrier=BarrierInput.model_validate(payload))
        if capability == "followup.add":
            return CareReview(action="task", task=CareTaskInput.model_validate(payload))
        return CareReview(action="task_update", task_id=target, task_update=TaskUpdate.model_validate(payload))
