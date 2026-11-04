"""Owned bounded conversation projections; historical text is never executable input."""

from collections.abc import Callable
from uuid import UUID

from ...contracts.assistant_workflows import ChoiceAction, ChoiceOption, ConversationAction, Preparation
from ...contracts.conversation_workflow import CONVERSATION_SCHEMAS
from ...contracts.quota import Usage
from ...domain.errors import ValidationError
from ..conversation_threads import ConversationThreadService


class ConversationAdapter:
    capability_ids = frozenset(CONVERSATION_SCHEMAS)

    def __init__(self, *, conversations: ConversationThreadService, usage: Callable[[UUID], Usage | None]):
        self.conversations, self.usage = conversations, usage

    def prepare(self, context, values, assets, results=()):
        if assets or results or context.capability_id not in self.capability_ids:
            raise ValidationError("Use a current owned conversation action")
        inputs = values.model_dump(mode="json", exclude_none=True)
        if context.capability_id == "assistant.usage":
            usage = self.usage(context.owner)
            visible = {"usage_available": usage is not None}
            if usage:
                visible.update(usage.model_dump(mode="json", exclude={"patient_id"}))
                visible["remaining"] = max(0, usage.limit - usage.llm_user_turns)
            return Preparation(input_fields={}, prompt_key="assistant.conversation.read", view_fields=visible)
        if context.capability_id in {"conversation.new", "conversation.clear"}:
            return Preparation(input_fields={}, prompt_key="assistant.conversation.patient_action", actions=(
                ConversationAction(action=context.capability_id.split(".")[1]),))
        selected = getattr(values, "conversation_id", None)
        if selected:
            row = self.conversations.require(context.owner, selected)
            if context.capability_id == "conversation.resume":
                return Preparation(input_fields=inputs, prompt_key="assistant.conversation.patient_action",
                    view_fields={"conversation": row.model_dump(mode="json")}, actions=(
                        ConversationAction(action="resume", conversation_id=selected),))
            page = self.conversations.page(context.owner, selected, values.before, 20)
            return Preparation(input_fields=inputs, prompt_key="assistant.conversation.read", view_fields={
                "conversation": row.model_dump(mode="json"),
                "entries": [{**entry.model_dump(mode="json", include={"id", "created_at", "photo_attached"}),
                    "user_text": entry.user_text[:1000], "assistant_text": entry.assistant_text[:2000]}
                    for entry in page.entries], "next_before": str(page.next_before) if page.next_before else None})
        page = self.conversations.list(context.owner, values.before, 10)
        rows = page.entries
        return Preparation(input_fields=inputs, prompt_key="assistant.conversation.read",
            missing_fields=("conversation_id",) if context.capability_id != "conversation.list" else (),
            view_fields={"conversations": [row.model_dump(mode="json") for row in rows],
                         "next_before": str(page.next_before) if page.next_before else None},
            actions=(ChoiceAction(action_id="conversation.target", options=tuple(ChoiceOption(
                value=str(row.id), label_key="assistant.conversation.select", label_text=row.title[:120])
                for row in rows)),) if rows and context.capability_id != "conversation.list" else ())

    def observe(self, context, result_ref):
        raise ValidationError("Conversation results stay in the native client session")
