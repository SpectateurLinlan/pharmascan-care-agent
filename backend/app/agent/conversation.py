"""Bounded model orchestration over the existing tools/session/safety system."""

import json
import logging
import re
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import ValidationError as SchemaError

from ..contracts.agent_execution import ExecutionStopped, current_execution, execution_step
from ..contracts.context_bounds import bounded_context
from ..contracts.dto import AgentSessionDTO
from ..contracts.enums import AgentIntent, ToolName, ToolStatus
from ..contracts.medication_dialogue import MedicationDialogue
from ..contracts.medication_names import NameChoice, NameResolution
from ..contracts.model import ConversationalModel, ModelProviderError
from ..contracts.ports import AgentSessionRepository, IdGenerator
from ..contracts.temporal import calendar_selection
from ..domain.errors import (
    AuthenticationRequiredError,
    DomainError,
    NotFoundError,
    ProviderUnavailableError,
    ValidationError,
)
from ..domain.health_safety import needs_urgent_help_notice
from .current_medication import current_medication_question, read_current_medication_uses
from .instructions import INSTRUCTION
from .knowledge_intent import medication_question
from .memory import bounded_text, record_context
from .model_tools import ModelTools, model_tool_schemas
from .orchestrator import AgentOrchestrator, AgentReply, AgentTurn
from .patient_read_reply import medication_knowledge_batch_reply
from .read_dialogue import ReadAnswer, ReadDialogue, medication_candidate_version
from .tools import ToolResult

LOGGER = logging.getLogger("pharmascan.agent.model")


def grounded_message(model_text: str, summary: str) -> str:
    """Allow model-generated tone only around an exact authoritative summary."""
    core = model_text.strip()
    for opening in ["Here is your reviewed record: ", "我帮您查看了已核对的记录。"]:
        core = core.removeprefix(opening)
    for closing in [" Would you like to review your history?", "需要查看用药记录吗？"]:
        core = core.removesuffix(closing)
    return core if core == summary.strip() else summary


class ConversationService:
    def medication_fallback(
        self,
        *,
        patient_id: UUID,
        session_id: UUID,
        turn: AgentTurn,
        arguments: dict | None = None,
    ) -> AgentReply | None:
        """Use the existing audited read tool if AI cannot answer an explicit education request."""
        arguments = arguments if arguments is not None else medication_question(turn.text)
        if arguments is None:
            return None
        session = self._fallback.get_session(patient_id=patient_id, session_id=session_id)
        if session is None or session.state == "expired":
            raise ValidationError("Reopen your assistant session")
        try:
            executed = self._tools.execute(
                name="get_medication_understanding",
                arguments=arguments,
                patient_id=patient_id,
                session_id=session_id,
                correlation_id=self._ids.new_id(),
                client_turn_id=str(turn.slots.get("client_turn_id", "turn-1")),
                turn=turn,
            )
        except (AuthenticationRequiredError, ExecutionStopped):
            raise
        except DomainError as error:
            LOGGER.warning(
                "Medication education unavailable error_type=%s code=%s", type(error).__name__, error.code.value
            )
            if isinstance(error, ProviderUnavailableError):
                message = (
                    "药物资料服务暂时无法访问，请稍后重试。这不代表您没有登记该药物。"
                    if turn.language == "zh"
                    else "Medication information is temporarily unavailable. Please retry later. "
                    "This does not mean the medicine is missing from your records."
                )
            elif isinstance(error, NotFoundError):
                message = (
                    "无法读取所选药物的资料，请从您的药物列表重新选择后重试。"
                    if turn.language == "zh"
                    else "The selected medicine's information could not be read. Please select it again in Medicines."
                )
            else:
                message = (
                    "未能完成药物资料查询，请核对药名、规格及原始标签后重试。"
                    if turn.language == "zh"
                    else "The medication lookup could not be completed. "
                    "Check the name, strength and original label, then retry."
                )
            return AgentReply(
                message=message,
                intent=AgentIntent.CLARIFICATION,
                session_id=session_id,
                session_state=session.state,
                mode="records_only",
                tool_results=[
                    ToolResult(
                        tool_name=ToolName.GET_LONG_TERM_CARE,
                        status=ToolStatus.BLOCKED,
                        error_code=error.code.value,
                        payload={"action": "get_medication_understanding"},
                    )
                ],
            )
        name_choice = None
        if executed.data.get("name_resolution"):
            resolution = NameResolution.model_validate(executed.data["name_resolution"])
            if resolution.status in {"needs_confirmation", "ambiguous"} and resolution.candidates:
                now = datetime.fromisoformat(str(self._tools.context_metadata(patient_id)["current_time"]))
                name_choice = NameChoice(
                    id=self._ids.new_id(),
                    original=resolution.original,
                    expires_at=now + timedelta(minutes=10),
                    options=resolution.candidates,
                )
        if executed.data.get("clarification_required") and name_choice is None:
            read = self._reads.run(patient_id, session, turn)
            if read is not None:
                return self._read_reply(session, turn, replace(read, results=[*executed.results, *read.results]))
        summary = str(executed.data["patient_safe_summary"])
        if name_choice:
            summary += " " + ", ".join(row.display_name for row in name_choice.options)
        context = record_context(
            session.context,
            text=turn.patient_text,
            message=summary,
            intent=executed.intent.value,
            language=turn.language,
            results=executed.results,
        )
        dialogue = (session.context.medication_dialogue or MedicationDialogue()).model_copy(
            update={
                "topic": "medication",
                "choice": None,
                "name_choice": name_choice,
                "subject_name": arguments.get("medication_name"),
                "conversation_id": session.conversation_id,
            }
        )
        context = bounded_context(
            context.model_copy(update={"medication_dialogue": dialogue, "active_task": "medication_education"})
        )
        if turn.persistence.save_context:
            turn.persistence.persist_session(self._sessions, session.model_copy(update={"context": context}))
        return AgentReply(
            name_choice=name_choice,
            message=summary,
            intent=executed.intent,
            session_id=session_id,
            session_state=session.state,
            tool_results=executed.results,
            mode="records_only",
        )

    def name_selection_turn(self, *, patient_id: UUID, session_id: UUID, turn: AgentTurn) -> AgentReply | None:
        session = self._fallback.get_session(patient_id=patient_id, session_id=session_id)
        dialogue = session.context.medication_dialogue if session else None
        pending = dialogue.name_choice if dialogue else None
        selection = turn.name_selection
        if dialogue is not None and dialogue.topic != "medication":
            pending = None
        if not selection:
            if pending is None or medication_question(turn.text) or turn.photo_context or turn.medication_selection:
                return None
            text = turn.text.strip().casefold()
            matches = [row for row in pending.options if self._tools.validate_name_candidate(row, text=text)]
            if len(pending.options) == 1 and text in {"yes", "yes please", "是", "是的", "确认", "确认药名", "第一个"}:
                matches = list(pending.options)
            if len(matches) != 1:
                return None
            candidate = matches[0]
        else:
            if pending is None or selection.choice_id != pending.id or selection.expected_version != pending.version:
                raise ValidationError("Medicine name choice is stale or unavailable; ask the question again")
            candidate = next((row for row in pending.options if row.id == selection.candidate_id), None)
            if candidate is None:
                raise ValidationError("Medicine name is not an offered choice")
        now = datetime.fromisoformat(str(self._tools.context_metadata(patient_id)["current_time"]))
        if pending.expires_at <= now or dialogue.conversation_id != session.conversation_id:
            raise ValidationError("Medicine name choice expired; ask the question again")
        if not self._tools.validate_name_candidate(candidate):
            raise ValidationError("Medicine name sources changed; ask the question again")
        return self.medication_fallback(
            patient_id=patient_id,
            session_id=session_id,
            turn=turn,
            arguments={"question": pending.question, "medication_name": candidate.canonical_name},
        )

    def _read_reply(self, session: AgentSessionDTO, turn: AgentTurn, read: ReadAnswer) -> AgentReply:
        # ReadDialogue never creates public-name candidates. Any independently
        # answered history/list/health/source turn invalidates the old proposal.
        read = replace(read, dialogue=read.dialogue.model_copy(update={"name_choice": None}))
        context = record_context(
            session.context,
            text=turn.patient_text,
            message=read.message,
            intent=read.intent.value,
            language=turn.language,
            results=read.results,
        )
        values = {
            "medication_dialogue": read.dialogue,
            "referenced_medication_id": None,
            "referenced_regimen_id": None,
            "referenced_occurrence_id": None,
        }
        if read.dialogue.topic == "medication":
            values["active_task"] = "medication_education_choice" if read.dialogue.choice else "medication_education"
        if read.selected:
            values.update(
                referenced_medication_id=read.selected.medication_id, referenced_regimen_id=read.selected.regimen_id
            )
        context = bounded_context(context.model_copy(update=values))
        if turn.persistence.save_context:
            turn.persistence.persist_session(self._sessions, session.model_copy(update={"context": context}))
        return AgentReply(
            message=read.message,
            intent=read.intent,
            session_id=session.id,
            session_state=session.state,
            tool_results=read.results,
            mode="records_only",
            medication_choice=context.medication_dialogue.choice if context.medication_dialogue else None,
        )

    def __init__(
        self,
        *,
        model: ConversationalModel,
        tools: ModelTools,
        fallback: AgentOrchestrator,
        sessions: AgentSessionRepository,
        ids: IdGenerator,
        max_tool_rounds: int = 4,
    ):
        self._model, self._tools, self._fallback, self._sessions, self._ids = model, tools, fallback, sessions, ids
        if not 1 <= max_tool_rounds <= 4:
            raise ValueError("Tool rounds must be1..4")
        self._rounds = max_tool_rounds
        self._reads = ReadDialogue(tools, ids)

    def handle_turn(
        self, *, patient_id: UUID, session_id: UUID, turn: AgentTurn, on_model_request: Callable[[], None] | None = None
    ) -> AgentReply:
        session = self._fallback.get_session(patient_id=patient_id, session_id=session_id)
        if session is None or session.state == "expired":
            raise ValidationError("Reopen your assistant session")
        if needs_urgent_help_notice(turn.text):
            return self._fallback.handle_turn(patient_id=patient_id, session_id=session_id, turn=turn)
        selected_name = self.name_selection_turn(patient_id=patient_id, session_id=session_id, turn=turn)
        if selected_name is not None:
            return selected_name
        # Date safety precedes model tool selection. The same deterministic
        # policy must reject historical self-reporting even if a model would
        # otherwise ask an unrelated care clarification first.
        if re.search(r"\bi (?:already )?(?:took|did not take)|我.*(?:吃了|吃过|服了|服用过)", turn.text, re.I):
            metadata = self._tools.context_metadata(patient_id)
            calendar = calendar_selection(
                turn.text, datetime.fromisoformat(str(metadata["current_time"])), str(metadata["timezone"])
            )
            if calendar.explicit and (not calendar.supported or calendar.day.isoformat() != metadata["local_date"]):
                return self._fallback.handle_turn(patient_id=patient_id, session_id=session_id, turn=turn)
        interval_reply = self._fallback.interval_enrollment_turn(
            patient_id=patient_id, session_id=session_id, turn=turn
        )
        if interval_reply is not None:
            return interval_reply
        explicit_question = medication_question(turn.text)
        if (
            explicit_question
            and explicit_question.get("medication_name")
            and not turn.photo_context
            and not turn.medication_selection
        ):
            return self.medication_fallback(patient_id=patient_id, session_id=session_id, turn=turn)
        read = self._reads.run(patient_id, session, turn)
        if read is not None:
            return self._read_reply(session, turn, read)
        if session.context.medication_dialogue:
            dialogue = session.context.medication_dialogue.model_copy(
                update={"topic": "other", "choice": None, "name_choice": None}
            )
            session = session.model_copy(
                update={"context": session.context.model_copy(update={"medication_dialogue": dialogue})}
            )
            if turn.persistence.save_context:
                turn.persistence.persist_session(self._sessions, session)
        plural = current_medication_question(turn.text)
        education_context = session.context.active_task in {"medication_education_choice", "medication_education"}
        choice = turn.text if plural is None and education_context else None
        if (plural is not None or choice is not None) and turn.photo_context is None:
            answer = read_current_medication_uses(
                tools=self._tools,
                patient_id=patient_id,
                session_id=session_id,
                correlation_id=self._ids.new_id(),
                turn=turn,
                reference=turn.navigation_context.medication_id
                if turn.navigation_context
                else session.context.referenced_medication_id,
                plural=plural is True,
                choice=choice,
            )
            if answer is not None:
                context = record_context(
                    session.context,
                    text=turn.patient_text,
                    message=answer.message,
                    intent=AgentIntent.CLARIFICATION.value,
                    language=turn.language,
                    results=answer.results,
                ).model_copy(
                    update={
                        "active_task": "medication_education_choice"
                        if answer.awaiting_choice
                        else "medication_education",
                    }
                )
                if answer.selected_reference:
                    chosen = answer.selected_reference
                    context = context.model_copy(
                        update={
                            "referenced_medication_id": chosen.medication_id,
                            "referenced_regimen_id": chosen.regimen_id,
                            "referenced_occurrence_id": (
                                context.referenced_occurrence_id
                                if context.referenced_medication_id == chosen.medication_id
                                else None
                            ),
                        }
                    )
                if turn.persistence.save_context:
                    turn.persistence.persist_session(self._sessions, session.model_copy(update={"context": context}))
                return AgentReply(
                    message=answer.message,
                    intent=AgentIntent.CLARIFICATION,
                    session_id=session_id,
                    session_state=session.state,
                    tool_results=answer.results,
                    mode="records_only",
                )
        context = session.context.model_dump(mode="json")
        task_id = turn.slots.get("evidence_task_id") or session.context.enrollment_task_id
        if task_id:
            try:
                owned_task_id = UUID(str(task_id))
            except (ValueError, TypeError):
                raise ValidationError("Choose a valid owned evidence task") from None
            verified = self._tools.evidence_context(patient_id, owned_task_id)
            context["enrollment"] = verified
            # Store only the tool-validated reference; durable evidence is in
            # the owned task, independent of the two-hour conversation TTL.
            session = session.model_copy(
                update={
                    "context": session.context.model_copy(
                        update={"enrollment_task_id": UUID(str(task_id)), "active_task": "medication_enrollment"}
                    )
                }
            )
            if turn.persistence.save_context:
                turn.persistence.persist_session(self._sessions, session)
        context["preferred_language"] = turn.language
        # No patient UUID/token or medication database dump enters this envelope.
        history = [
            {
                "type": "user_input",
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "context": context,
                                **self._tools.context_metadata(patient_id),
                                "current_input": bounded_text(turn.text, 2000),
                                "navigation_context": turn.navigation_context.model_dump(mode="json")
                                if turn.navigation_context
                                else None,
                                **(
                                    {"untrusted_photo_evidence": turn.photo_context.model_context()}
                                    if turn.photo_context
                                    else {}
                                ),
                            }
                        ),
                    }
                ],
            }
        ]
        results = []
        intent = AgentIntent.CLARIFICATION
        tools_used = 0
        evidence_summary = None
        full_review_summary = None
        knowledge_reads: dict[str, dict] = {}
        knowledge_is_current_summary = False
        text = turn.text.lower()
        review_requested = (
            any(word in text for word in ("prepare", "preparing"))
            and any(word in text for word in ("pharmacist", "doctor", "visit", "medication review"))
        ) or any(word in text for word in ("就诊准备", "复查准备", "准备复诊"))
        requested_review_repair = False
        try:
            for _round in range(self._rounds):
                with execution_step("model"):
                    if on_model_request:
                        on_model_request()
                    schemas = model_tool_schemas(photo_only=turn.photo_context is not None)
                    if control := current_execution.get():
                        control.model_started(getattr(self._model, "model", None), INSTRUCTION, schemas)
                    reply = self._model.create(history=history, tools=schemas, instruction=INSTRUCTION)
                history.extend(reply.replay)
                if not reply.calls:
                    if not results and medication_question(turn.text):
                        grounded = self.medication_fallback(patient_id=patient_id, session_id=session_id, turn=turn)
                        if grounded:
                            return grounded
                    if (
                        review_requested
                        and results
                        and any(row.tool_name == ToolName.GET_LONG_TERM_CARE for row in results)
                        and full_review_summary is None
                        and not any(row.payload.get("care_clarification") for row in results)
                    ):
                        if requested_review_repair:
                            raise ValidationError("Requested medication review evidence is incomplete")
                        # Bounded coverage repair: a narrow task read cannot
                        # satisfy a requested medication/health visit review.
                        requested_review_repair = True
                        history.append(
                            {
                                "type": "user_input",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "Application coverage check: only a partial read is available. "
                                        "Call prepare_medication_review to complete the requested visit review; "
                                        "do not infer missing health or medication information.",
                                    }
                                ],
                            }
                        )
                        continue
                    # Multiple medicines must clarify even if the model stops
                    # after listing. The existing deterministic policy owns it.
                    if any(
                        row.tool_name.value == "list_active_medications" and row.payload.get("item_count", 0) > 1
                        for row in results
                    ) and (turn.text.lower().startswith("i took") or turn.text.startswith("我吃了")):
                        clarification = self._fallback.handle_turn(
                            patient_id=patient_id, session_id=session_id, turn=turn
                        )
                        return replace(clarification, mode="gemini")
                    if evidence_summary is not None:
                        # Source tasks may still be unreviewed: do not decorate
                        # them with the model's generic "reviewed record" prefix.
                        message = evidence_summary
                        if knowledge_is_current_summary and full_review_summary is None:
                            plural_uses = bool(
                                re.search(
                                    r"\bevery\b|\beach\b|\ball\b|\bmedicines\b|\bmedications\b|这些|各个|分别|各自",
                                    turn.text,
                                    re.I,
                                )
                            )
                            listed = (
                                [
                                    item
                                    for result in results
                                    if result.tool_name == ToolName.LIST_ACTIVE_MEDICATIONS
                                    for item in result.payload.get("medications", [])
                                ]
                                if plural_uses
                                else []
                            )
                            message = medication_knowledge_batch_reply(
                                list(knowledge_reads.values()), listed, turn.language
                            )
                    elif results:
                        # Medication facts use the deterministic grounded renderer.
                        message = grounded_message(
                            reply.text, self._fallback.render_results(intent, results, turn.language)
                        )
                    elif turn.photo_context:
                        message = turn.photo_context.patient_summary(turn.language)
                    else:
                        message = (
                            "Please choose a medication task or clarify what you need. "
                            "I cannot infer your medication instructions."
                        )
                    saved = self._fallback.get_session(patient_id=patient_id, session_id=session_id)
                    if any(word in turn.text.lower() for word in ["not sure", "unsure", "whether", "不确定", "不记得"]):
                        message = (
                            "不会因不确定而记录已服用。"
                            if turn.language == "zh"
                            else "No dose will be marked as taken from uncertainty. "
                        ) + message
                    context = record_context(
                        saved.context,
                        text=turn.patient_text,
                        message=message,
                        intent=intent.value,
                        language=turn.language,
                        results=results,
                    )
                    if knowledge_is_current_summary:
                        catalogue = [
                            item
                            for result in results
                            if result.tool_name == ToolName.LIST_ACTIVE_MEDICATIONS
                            for item in result.payload.get("medications", [])
                        ]
                        ids = [
                            UUID(str(data["medication_id"]))
                            for data in knowledge_reads.values()
                            if data.get("medication_id")
                        ]
                        context = bounded_context(
                            context.model_copy(
                                update={
                                    "medication_dialogue": MedicationDialogue(
                                        conversation_id=session.conversation_id,
                                        candidate_version=medication_candidate_version(catalogue),
                                        answered_medication_ids=ids[:3],
                                        subject_name=next(iter(knowledge_reads.values())).get("medication_name")
                                        if len(knowledge_reads) == 1 and not ids
                                        else None,
                                    ),
                                    # A plural answer does not establish one unique pronoun referent.
                                    **(
                                        {
                                            "referenced_medication_id": None,
                                            "referenced_regimen_id": None,
                                            "referenced_occurrence_id": None,
                                        }
                                        if len(knowledge_reads) > 1
                                        else {}
                                    ),
                                }
                            )
                        )
                    if turn.persistence.save_context:
                        turn.persistence.persist_session(self._sessions, saved.model_copy(update={"context": context}))
                    return AgentReply(
                        message=message,
                        intent=intent,
                        session_id=session_id,
                        session_state=saved.state,
                        tool_results=results,
                        mode="gemini",
                    )
                if tools_used + len(reply.calls) > 4:
                    raise ValidationError("Tool budget exceeded")
                for call in reply.calls:
                    tools_used += 1
                    executed = self._tools.execute(
                        name=call.name,
                        arguments=call.arguments,
                        patient_id=patient_id,
                        session_id=session_id,
                        correlation_id=self._ids.new_id(),
                        client_turn_id=str(turn.slots.get("client_turn_id", "turn-1")),
                        turn=turn,
                    )
                    if len(json.dumps(executed.data)) > 16000:
                        raise ValidationError("Tool result exceeds bounded model context")
                    results.extend(executed.results)
                    if "patient_safe_summary" in executed.data:
                        current_summary = str(executed.data["patient_safe_summary"])
                        knowledge_is_current_summary = (
                            call.name == "get_medication_understanding"
                            and executed.data.get("question") == "general_use"
                        )
                        if knowledge_is_current_summary:
                            key = str(executed.data.get("medication_id") or executed.data.get("medication_name"))
                            knowledge_reads[key] = executed.data
                        if call.name in ("prepare_medication_review", "get_longitudinal_summary"):
                            full_review_summary = current_summary
                        # A subsequent narrow read must not erase verified
                        # symptoms/supply from a completed medication review.
                        evidence_summary = (
                            current_summary
                            if executed.care_review or "care_clarification" in executed.data
                            else full_review_summary or current_summary
                        )
                    intent = executed.intent
                    history.append(
                        {
                            "type": "function_result",
                            "name": call.name,
                            "call_id": call.id,
                            "result": [
                                {
                                    "type": "text",
                                    "text": json.dumps(
                                        {
                                            **executed.data,
                                            "patient_safe_summary": evidence_summary
                                            or self._fallback.render_results(
                                                executed.intent, executed.results, turn.language
                                            ),
                                        }
                                    ),
                                }
                            ],
                        }
                    )
                    if executed.care_review:
                        saved = self._fallback.get_session(patient_id=patient_id, session_id=session_id)
                        new_context = record_context(
                            saved.context,
                            text=turn.patient_text,
                            message=evidence_summary,
                            intent=intent.value,
                            language=turn.language,
                            results=results,
                        )
                        if turn.persistence.save_context:
                            turn.persistence.persist_session(
                                self._sessions, saved.model_copy(update={"context": new_context})
                            )
                        return AgentReply(
                            message=evidence_summary,
                            intent=intent,
                            session_id=session_id,
                            session_state=saved.state,
                            tool_results=results,
                            mode="gemini",
                            care_request=executed.care_review,
                        )
                    if executed.visual_request:
                        return AgentReply(
                            message=(
                                "Choose a synthetic pill photo to check. "
                                "A photo cannot confirm medication safety or ingestion."
                            ),
                            intent=AgentIntent.CLARIFICATION,
                            session_id=session_id,
                            session_state=session.state,
                            mode="gemini",
                            visual_check_request=executed.visual_request,
                        )
                    if executed.health_review:
                        message = (
                            "请核对您的感受描述，再明确选择保存。不会据此诊断病因或修改用药记录。"
                            if turn.language == "zh"
                            else "Review your own description before saving a health note. "
                            "This does not diagnose a cause or change dose records."
                        )
                        if executed.health_review.urgent_help_advised:
                            message = (
                                "若您现在有严重症状，请及时寻求专业帮助。危及生命的紧急情况请联系当地急救服务"
                                "（新加坡为995），不要等待本演示处理。您可稍后核对并保存感受记录。"
                                if turn.language == "zh"
                                else "For a life-threatening emergency, call your local emergency service "
                                "(995 in Singapore). If severe symptoms are happening now, "
                                "seek prompt professional help; "
                                "do not wait for this demo. "
                                "You can review your health note later."
                            )
                        context = record_context(
                            session.context,
                            text=turn.patient_text,
                            message=message,
                            intent="health_review",
                            language=turn.language,
                            results=[],
                        )
                        if turn.persistence.save_context:
                            turn.persistence.persist_session(
                                self._sessions, session.model_copy(update={"context": context})
                            )
                        return AgentReply(
                            message=message,
                            intent=AgentIntent.CLARIFICATION,
                            session_id=session_id,
                            session_state=session.state,
                            mode="gemini",
                            health_note_request=executed.health_review,
                        )
                    if executed.prepared_reply:
                        return replace(executed.prepared_reply, mode="gemini")
            raise ValidationError("Model tool-round budget exceeded")
        except (ModelProviderError, ExecutionStopped):
            raise
        except (DomainError, SchemaError) as exc:
            LOGGER.warning("Model tool fallback error_type=%s", type(exc).__name__)
            if medication_question(turn.text):
                knowledge = self.medication_fallback(patient_id=patient_id, session_id=session_id, turn=turn)
                if knowledge:
                    return knowledge
            # Genuine deterministic fallback; never present it as a model answer.
            return self._fallback.handle_turn(patient_id=patient_id, session_id=session_id, turn=turn)
