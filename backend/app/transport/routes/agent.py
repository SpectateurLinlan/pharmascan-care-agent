"""Patient-owned conversations and stateless model orchestration through typed tools.

History never restores executable confirmations or replaces structured patient facts.
Every response identifies Gemini or the deterministic fallback.
"""

from __future__ import annotations

import hashlib
import json
import logging
from uuid import UUID, uuid5

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as SchemaValidationError

from ...agent.orchestrator import AgentTurn
from ...application.assistant_navigation import resolve_navigation
from ...contracts.agent_context import RecentTurn
from ...contracts.conversation_history import HistoryPage
from ...contracts.conversation_threads import (
    ConversationList,
    ConversationMessage,
    ConversationPage,
    ConversationResume,
)
from ...contracts.navigation_context import NavigationContext, NavigationInput
from ...domain.errors import DomainError, NotFoundError, ValidationError
from ..auth import AuthenticatedPrincipal
from ..deps import ApplicationContainer, get_container, get_principal
from ..schemas import AgentMessageRequest, AgentMessageResponse, ToolTraceResponse

router = APIRouter(prefix="/api/agent", tags=["agent"])


def _mark_failed(service, patient_id, turn_id):
    try:
        service.fail(patient_id, turn_id)
    except DomainError as error:
        # A storage outage must not erase an already produced patient answer.
        logging.getLogger("pharmascan.history").warning("Claim update unavailable: %s", type(error).__name__)


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
):
    container.conversation_history.clear(principal.patient_id, confirmed=payload.confirmed)
    return {"cleared": True}


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
):
    container.conversation_threads.require(principal.patient_id, conversation_id)
    session = container.orchestrator.start_session(patient_id=principal.patient_id)
    return container.conversation_threads.resume(principal.patient_id, conversation_id, session.id)


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
    navigation = (
        resolve_navigation(container.enrollment, patient_id, payload.navigation_context)
        if payload.navigation_context
        else None
    )
    threaded = "conversation_id" in payload.model_fields_set
    thread_service = container.conversation_threads
    saving = bool(container.preferences.get(patient_id).conversation_history_enabled)
    conversation_id = payload.conversation_id if threaded else None
    if conversation_id:
        thread_service.require(patient_id, conversation_id)
    if threaded and saving and conversation_id is None:
        conversation_id = uuid5(patient_id, "conversation:" + payload.client_turn_id)
        thread_service.create(patient_id, conversation_id, payload.text, bool(payload.photo_context))
    key = str(payload.slots.get("idempotency_key", f"turn-{payload.client_turn_id}"))
    prior = container.self_report.find_confirmation(patient_id=patient_id, idempotency_key=key)
    session_id: UUID = payload.session_id or (
        prior.session_id
        if prior is not None and prior.action == "record_self_report"
        else container.orchestrator.start_session(patient_id=patient_id).id
    )
    if threaded and conversation_id:
        session = container.orchestrator.get_session(patient_id=patient_id, session_id=session_id)
        if session is None or session.state == "expired" or session.expires_at <= container.clock.now():
            session = container.orchestrator.start_session(patient_id=patient_id)
            session_id = session.id
        if session.conversation_id is None:
            # Never bind an existing executable confirmation from another context.
            if session.state != "collecting" or session.context.recent_turns:
                session = container.orchestrator.start_session(patient_id=patient_id)
                session_id = session.id
            thread_service.bind(patient_id, conversation_id, session_id, restore=True)
        elif session.conversation_id != conversation_id:
            raise ValidationError("Session belongs to another conversation")
    turn_id = uuid5(conversation_id, payload.client_turn_id) if threaded and conversation_id else None
    if turn_id and saving:
        digest = hashlib.sha256(
            json.dumps(
                payload.model_dump(mode="json", exclude={"session_id", "client_id", "conversation_id"}), sort_keys=True
            ).encode()
        ).hexdigest()
        claimed = thread_service.claim(patient_id, conversation_id, turn_id, digest)
        if claimed == "completed":
            saved = thread_service.message(patient_id, turn_id)
            if saved is None:
                raise NotFoundError("Saved message unavailable for this patient")
            return AgentMessageResponse(
                conversation_id=conversation_id,
                history_saved=True,
                message=saved.assistant_text,
                intent="clarification",
                session_id=session_id,
                session_state="collecting",
                requires_confirmation=False,
                mode="records_only",
            )
        if claimed != "new":
            raise ValidationError(
                "This message is already processing or failed. Check the conversation before sending again."
            )

    turn = AgentTurn(
        text=payload.text,
        language=container.preferences.get(patient_id).preferred_language
        if container.preferences
        else payload.language,
        slots={**payload.slots, "client_turn_id": payload.client_turn_id},
        photo_context=payload.photo_context,
        navigation_context=navigation,
        medication_selection=payload.medication_selection,
    )
    handler = container.ai_agent or container.orchestrator
    try:
        reply = handler.handle_turn(patient_id=patient_id, session_id=session_id, turn=turn)
    except Exception:
        if turn_id and saving:
            _mark_failed(thread_service, patient_id, turn_id)
        raise
    history_saved = None
    if threaded and saving:
        try:
            thread_service.append(
                patient_id,
                reply.session_id,
                ConversationMessage(
                    id=turn_id,
                    conversation_id=conversation_id,
                    user_text=payload.text,
                    assistant_text=reply.message,
                    photo_attached=bool(payload.photo_context),
                    created_at=container.clock.now(),
                ),
            )
            history_saved = True
        except (DomainError, SchemaValidationError) as error:
            logging.getLogger("pharmascan.history").warning("Thread save unavailable: %s", type(error).__name__)
            _mark_failed(thread_service, patient_id, turn_id)
            history_saved = False
    elif not threaded and container.conversation_history and saving:
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
        conversation_id=conversation_id,
        history_saved=history_saved,
        message=reply.message,
        medication_choice=reply.medication_choice,
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
