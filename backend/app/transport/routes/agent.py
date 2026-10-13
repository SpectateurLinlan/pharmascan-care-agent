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
from ..auth import AuthenticatedPrincipal
from ..deps import ApplicationContainer, get_container, get_principal
from ..schemas import AgentMessageRequest, AgentMessageResponse, ToolTraceResponse

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/messages", response_model=AgentMessageResponse)
def send_message(
    payload: AgentMessageRequest,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
) -> AgentMessageResponse:
    patient_id = principal.patient_id
    session_id: UUID = payload.session_id or container.orchestrator.start_session(
        patient_id=patient_id
    ).id

    turn = AgentTurn(text=payload.text, slots=dict(payload.slots))
    reply = container.orchestrator.handle_turn(
        patient_id=patient_id, session_id=session_id, turn=turn
    )
    return AgentMessageResponse(
        message=reply.message,
        intent=reply.intent.value,
        session_id=reply.session_id,
        session_state=reply.session_state,
        requires_confirmation=reply.requires_confirmation,
        mode=reply.mode,
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
