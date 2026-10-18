"""Shared persistence budget; text windows never become medical authority."""

import json

from .agent_context import AgentContext


def bounded_context(context: AgentContext) -> AgentContext:
    # Read-choice metadata is disposable context, never the durable transcript.
    # A large candidate set must not crowd out the current patient's question.
    metadata = context.model_copy(update={"recent_turns": []})
    if len(json.dumps(metadata.model_dump(mode="json"), ensure_ascii=False).encode("utf-8")) > 12000:
        context = context.model_copy(update={"medication_dialogue": None})
    turns = list(context.recent_turns[-6:])
    while turns:
        candidate = context.model_copy(update={"recent_turns": turns})
        if len(json.dumps(candidate.model_dump(mode="json"), ensure_ascii=False).encode("utf-8")) <= 16000:
            break
        turns.pop(0)
    return context.model_copy(update={"recent_turns": turns})
