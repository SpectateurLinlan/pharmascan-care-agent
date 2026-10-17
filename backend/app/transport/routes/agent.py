"""Patient-owned conversations and stateless model orchestration through typed tools.

History never restores executable confirmations or replaces structured patient facts.
Every response identifies Gemini or the deterministic fallback.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from ...agent.orchestrator import AgentTurn
from ...contracts.agent_context import RecentTurn
from ...contracts.conversation_history import HistoryPage
from ...domain.errors import DomainError, NotFoundError
from ..auth import AuthenticatedPrincipal
from ..deps import ApplicationContainer, get_container, get_principal
from ..schemas import AgentMessageRequest, AgentMessageResponse, ToolTraceResponse

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.get("/history", response_model=HistoryPage)
def conversation_history(
    before: UUID | None = None,
    limit: int = Query(default=20, ge=1, le=20),
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    return container.conversation_history.page(principal.patient_id, before, limit)


class ClearHistory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: bool


@router.delete("/history")
def clear_history(
    payload: ClearHistory,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    container.conversation_history.clear(principal.patient_id, confirmed=payload.confirmed)
    return {"cleared": True}


@router.get("/sessions/{session_id}/recent-turns", response_model=list[RecentTurn])
def recent_turns(
    session_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    session = container.orchestrator.get_session(patient_id=principal.patient_id, session_id=session_id)
    if session is None:
        raise NotFoundError("Assistant session not found for this patient")
    return session.context.recent_turns


@router.post("/messages", response_model=AgentMessageResponse)
def send_message(
    payload: AgentMessageRequest,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
) -> AgentMessageResponse:
    patient_id = principal.patient_id
    key = str(payload.slots.get("idempotency_key", f"turn-{payload.client_turn_id}"))
    prior = container.self_report.find_confirmation(patient_id=patient_id, idempotency_key=key)
    session_id: UUID = payload.session_id or (
        prior.session_id
        if prior is not None and prior.action == "record_self_report"
        else container.orchestrator.start_session(patient_id=patient_id).id
    )

    turn = AgentTurn(
        text=payload.text,
        language=container.preferences.get(patient_id).preferred_language
        if container.preferences
        else payload.language,
        slots={**payload.slots, "client_turn_id": payload.client_turn_id},
        photo_context=payload.photo_context,
    )
    handler = container.ai_agent or container.orchestrator
    reply = handler.handle_turn(patient_id=patient_id, session_id=session_id, turn=turn)
    history_saved = None
    if container.conversation_history and container.preferences.get(patient_id).conversation_history_enabled:
        try:
            container.conversation_history.append(
                patient_id, reply.session_id, payload.client_turn_id, turn.patient_text, reply.message
            )
            history_saved = True
        except DomainError as error:
            # The actual reply/confirmation must survive a history-storage failure.
            logging.getLogger("pharmascan.history").warning("History unavailable: %s", type(error).__name__)
            history_saved = False
    return AgentMessageResponse(
        history_saved=history_saved,
        message=reply.message,
        intent=reply.intent.value,
        session_id=reply.session_id,
        session_state=reply.session_state,
        requires_confirmation=reply.requires_confirmation,
        mode=reply.mode,
        pending_report=reply.pending_report,
        usage=reply.usage,
        visual_check_request=reply.visual_check_request,
        health_note_request=reply.health_note_request,
        care_request=reply.care_request,
        tool_traces=[
            ToolTraceResponse(
                tool_name=r.tool_name.value,
                status=r.status.value,
                error_code=r.error_code,
                requires_confirmation=r.requires_confirmation,
                clarification_question=r.clarification_question,
                payload=dict(r.payload),
            )
            for r in reply.tool_results
        ],
    )
