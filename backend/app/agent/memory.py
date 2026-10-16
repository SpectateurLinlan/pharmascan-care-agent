"""Only successful typed tool results may establish patient references."""

from uuid import UUID

from ..contracts.agent_context import AgentContext, CareClarification, RecentTurn
from ..contracts.enums import ToolName, ToolStatus
from ..contracts.privacy import bounded_text as bounded_text
from .tools import ToolResult


def record_context(
    context: AgentContext, *, text: str, message: str, intent: str, language: str, results: list[ToolResult]
) -> AgentContext:
    values = {
        "active_task": intent,
        "last_intent": intent,
        "preferred_language": language,
        "recent_turns": [
            *context.recent_turns,
            RecentTurn(user=bounded_text(text, 500), assistant=bounded_text(message, 700)),
        ][-6:],
    }
    for result in results:
        if result.status != ToolStatus.SUCCESS:
            continue
        if result.tool_name in (ToolName.GET_LONG_TERM_CARE, ToolName.PREPARE_CARE_ACTION):
            action = result.payload.get("action")
            if isinstance(action, str) and len(action) <= 50:
                values["active_task"] = action
            clarification = result.payload.get("care_clarification")
            values["care_clarification"] = CareClarification.model_validate(clarification) if clarification else None
        rows = result.payload.get("schedule", result.payload.get("due_doses", []))
        if result.tool_name == ToolName.LIST_ACTIVE_MEDICATIONS:
            rows = result.payload.get("medications", [])
        if result.tool_name == ToolName.GET_DOSE_STATUS:
            rows = [result.payload]
        if len(rows) != 1:
            if result.tool_name == ToolName.CHECK_DUE_DOSE:
                values.update(referenced_medication_id=None, referenced_regimen_id=None, referenced_occurrence_id=None)
            continue
        row = rows[0]
        if row.get("medication_id") and str(context.referenced_medication_id) != str(row["medication_id"]):
            values["referenced_occurrence_id"] = None
        for key in ["medication_id", "regimen_id", "occurrence_id"]:
            if row.get(key):
                values["referenced_" + key] = UUID(str(row[key]))
    # Summary is deterministic task state, never LLM-authored permanent facts.
    values["conversation_summary"] = (
        f"Last verified task: {intent}. References are tool-derived; self-report needs explicit confirmation."
    )
    return context.model_copy(update=values)
