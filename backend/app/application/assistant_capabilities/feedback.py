"""Feedback drafts cannot send email or make a clinical communication."""

from ...contracts.assistant_workflows import Preparation
from ...contracts.conversation_workflow import FeedbackFields
from ...contracts.patient_feedback import FeedbackInput
from ...domain.errors import StaleVersionError
from ..patient_feedback import FeedbackService


class FeedbackDrafts:
    schemas = {"feedback.submit": FeedbackFields}
    read_ids = frozenset()
    prompt = "assistant.feedback"
    review_component = "existing_feedback_review"

    def __init__(self, feedback: FeedbackService):
        self.feedback = feedback

    def target(self, context, values, review_id):
        return review_id

    def current(self, context, values, review_id=None):
        row = self.feedback.get(context.owner, review_id) if review_id else None
        return row.model_dump(mode="json", exclude={"patient_id"}) if row else None

    def payload(self, context, values, review_id):
        return FeedbackInput(id=review_id, category=values.category, message=values.message).model_dump(mode="json")

    def unchanged(self, context, values, review_id=None):
        return self.current(context, values, review_id) is None

    def check(self, context, values, review_id=None):
        if not values.message or not self.unchanged(context, values, review_id):
            raise StaleVersionError("Complete the feedback draft or check its earlier native result")

    def collect(self, context, values):
        return Preparation(input_fields=values.model_dump(mode="json", exclude_none=True),
            missing_fields=() if values.message else ("message",),
            workflow_state="ready_for_review" if values.message else "collecting",
            prompt_key="assistant.feedback.collect")

    def visible(self, context, values, review_id):
        return {"current_feedback": self.current(context, values, review_id)}

    def native_result(self, context, values, review_id):
        row = self.feedback.get(context.owner, review_id)
        return {"id": row.id, "created_at": row.created_at, "status": "received"} if row else None

    def verify(self, context, values, review_id, result):
        row = self.feedback.get(context.owner, review_id)
        return bool(row and self.native_result(context, values, review_id) == result
                    and row.category == values.category and row.message == values.message)
