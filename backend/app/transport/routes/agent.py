"""Patient-owned conversations and stateless model orchestration through typed tools.

History never restores executable confirmations or replaces structured patient facts.
Every response identifies Gemini or the deterministic fallback.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from ...application.assistant_navigation import resolve_navigation
from ...contracts.agent_context import RecentTurn
from ...contracts.assistant_workflows import WorkflowMessageInput, WorkflowMessageResult
from ...contracts.conversation_history import HistoryPage
from ...contracts.conversation_threads import (
    ConversationList,
    ConversationPage,
    ConversationResume,
)
from ...contracts.navigation_context import NavigationContext, NavigationInput
from ...domain.errors import NotFoundError
from ..auth import AuthenticatedPrincipal
from ..deps import ApplicationContainer, get_container, get_principal
from ..schemas import AgentMessageRequest, AgentMessageResponse, ToolTraceResponse
from ..workflow_binding import native_binding

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/navigation-context", response_model=NavigationContext)
def navigation_context(
    payload: NavigationInput,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    return resolve_navigation(container.enrollment, principal.patient_id, payload)


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
    binding=Depends(native_binding),
):
    def write():
        container.conversation_history.clear(principal.patient_id, confirmed=payload.confirmed)
        return {"cleared": True}
    if binding:
        if container.assistant_conversations is None:
            raise NotFoundError("Conversation workflows are unavailable")
        return container.assistant_conversations.run(principal.patient_id, *binding[:2], "conversation.clear",
            None, binding[2] and payload.confirmed, write, None)
    return write()


@router.get("/conversations", response_model=ConversationList)
def list_conversations(
    before: UUID | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    return container.conversation_threads.list(principal.patient_id, before, limit)


@router.get("/conversations/{conversation_id}", response_model=ConversationPage)
def read_conversation(
    conversation_id: UUID,
    before: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
):
    return container.conversation_threads.page(principal.patient_id, conversation_id, before, limit)


@router.post("/conversations/{conversation_id}/resume", response_model=ConversationResume)
def resume_conversation(
    conversation_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    container: ApplicationContainer = Depends(get_container),
    binding=Depends(native_binding),
):
    def write():
        container.conversation_threads.require(principal.patient_id, conversation_id)
        session = container.orchestrator.start_session(patient_id=principal.patient_id)
        return container.conversation_threads.resume(principal.patient_id, conversation_id, session.id)
    if binding:
        if container.assistant_conversations is None:
            raise NotFoundError("Conversation workflows are unavailable")
        return container.assistant_conversations.run(principal.patient_id, *binding[:2], "conversation.resume",
            conversation_id, binding[2], write, None)
    return write()


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
    result = container.messages().handle(
        principal.patient_id,
        WorkflowMessageInput(
            **payload.model_dump(exclude={"client_id"}),
            threaded="conversation_id" in payload.model_fields_set,
        ),
    )
    return message_response(result)


def message_response(result: WorkflowMessageResult) -> AgentMessageResponse:
    reply = result.reply
    return AgentMessageResponse(
        conversation_id=result.conversation_id,
        history_saved=result.history_saved,
        message=reply.message,
        medication_choice=reply.medication_choice,
        name_choice=reply.name_choice,
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
