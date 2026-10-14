"""Agent conversation endpoint.

The orchestrator is real (state machine, bounded steps, confirmation gating,
traces); only the intent router is a deterministic rule engine standing in for
the unavailable LLM. Every response carries ``mode`` so the UI cannot present
this as live LLM behaviour.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from ...agent.orchestrator import AgentTurn
from ...contracts.agent_context import RecentTurn
from ...domain.errors import NotFoundError
from ..auth import AuthenticatedPrincipal
from ..deps import ApplicationContainer, get_container, get_principal
from ..schemas import AgentMessageRequest, AgentMessageResponse, ToolTraceResponse

router = APIRouter(prefix="/api/agent", tags=["agent"])


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
    )
    handler = container.ai_agent or container.orchestrator
    reply = handler.handle_turn(patient_id=patient_id, session_id=session_id, turn=turn)
    return AgentMessageResponse(
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
