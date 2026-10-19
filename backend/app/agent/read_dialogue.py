"""Bounded read planning over existing tools and the existing session context.

No writes, private repositories, inferred patient IDs or model-generated facts.
"""

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from ..application.medication_presentation import knowledge_scope
from ..contracts.dto import AgentSessionDTO
from ..contracts.enums import AgentIntent, ToolStatus
from ..contracts.medication_dialogue import MedicationChoice, MedicationDialogue, MedicationOption
from ..contracts.ports import IdGenerator
from ..contracts.temporal import without_calendar_words
from ..domain.errors import AuthenticationRequiredError, DomainError, ValidationError
from .knowledge_intent import medication_question
from .medication_resolution import comparative_option
from .model_tools import ModelTools
from .orchestrator import AgentTurn
from .patient_read_reply import history_reply, knowledge_sources_reply, localized_form, medication_list_reply
from .status_reply import status_reply
from .tools import ToolResult


def normalized(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).casefold()).strip(" ?？。.")


def named_options(text: str, options: list[MedicationOption]) -> list[MedicationOption]:
    value = normalized(text)
    if re.fullmatch(r"[\w .+()/%-]{1,160}", value):
        prefix = [row for row in options if normalized(row.display_name).startswith(value + " ")]
        if prefix:
            return prefix
    exact = [
        row
        for row in options
        if re.search(r"(?<![a-z0-9])" + re.escape(normalized(row.display_name)) + r"(?![a-z0-9])", value)
    ]
    # Only trusted ingredient identities from the current patient's tool result.
    return [
        row
        for row in options
        if row in exact
        or any(
            re.search(r"(?<![a-z0-9])" + re.escape(normalized(ingredient)) + r"(?![a-z0-9])", value)
            for ingredient in row.ingredient_names
        )
    ]


def resolve_options(text: str, options: list[MedicationOption], *, allow_order: bool) -> list[MedicationOption]:
    value = normalized(text)
    found = named_options(text, options)
    strength = re.search(r"(?<![\d.])\d+(?:\.\d+)?\s*(?:mg|mcg|毫克|微克)(?![a-z])", value)
    if strength:
        compact = re.sub(r"\s+", "", strength[0]).replace("毫克", "mg").replace("微克", "mcg")
        found = [
            row
            for row in found or options
            if re.search(
                r"(?<![\d.])" + re.escape(compact) + r"(?![a-z\d.])",
                re.sub(r"\s+", "", normalized(row.label)),
            )
        ]
    if found:
        return found
    if allow_order:
        order = re.search(
            r"第\s*([一二三四五六七八九十]|\d+)\s*(?:个|种)?|\b(first|second|third|fourth|fifth|\d+(?:st|nd|rd|th))\b",
            value,
        )
        if order:
            key = order[1] or order[2]
            ordinal = {
                "一": 1,
                "二": 2,
                "三": 3,
                "四": 4,
                "五": 5,
                "六": 6,
                "七": 7,
                "八": 8,
                "九": 9,
                "十": 10,
                "first": 1,
                "second": 2,
                "third": 3,
                "fourth": 4,
                "fifth": 5,
            }.get(key)
            ordinal = ordinal or int(re.sub(r"\D", "", key) or "0")
            return options[ordinal - 1 : ordinal] if ordinal else []
    return []


def medication_candidate_version(rows: list[dict]) -> str:
    """Shared current-catalogue fingerprint; labels and UI language are excluded."""
    return hashlib.sha256(
        json.dumps(
            sorted(
                (
                    str(row["medication_id"]),
                    str(row["regimen_id"]),
                    row["display_name"],
                    row.get("strength_text"),
                    row.get("dosage_form"),
                    tuple(row.get("ingredients", [])),
                    json.dumps(row.get("comparison_basis"), sort_keys=True),
                )
                for row in rows
            )
        ).encode()
    ).hexdigest()


@dataclass(frozen=True)
class ReadAnswer:
    message: str
    results: list[ToolResult]
    dialogue: MedicationDialogue
    selected: MedicationOption | None = None
    intent: AgentIntent = AgentIntent.CLARIFICATION


class ReadDialogue:
    def __init__(self, tools: ModelTools, ids: IdGenerator):
        self._tools, self._ids = tools, ids

    def run(self, patient_id: UUID, session: AgentSessionDTO, turn: AgentTurn) -> ReadAnswer | None:
        if turn.photo_context:
            return None
        text = normalized(turn.text)
        previous = session.context.medication_dialogue or MedicationDialogue()
        question = medication_question(turn.text)
        original = bool(
            re.search(
                r"(?:show|view|read).*original.*(?:instruction|label)|(?:查看|显示|看看).*(?:原文|原始.*(?:指示|标签))",
                text,
            )
        )
        if original:
            question = {"question": "personal_instructions"}
        history = bool(
            re.search(
                (
                    "\\bhistory\\b|\\brecords?\\b.*\\b(?:dose|medicine|medication)\\b|\\b(?:d"
                    "ose|medication) (?:records?|reports?)\\b|report(?:ed)? taking|服药记录|服药自述|用药记录|吃过"
                    "哪些药|\\bdid i (?:take|report taking)\\b|\\bhave i (?:taken|reported taking)\\b"
                ),
                text,
            )
        )
        if session.context.last_intent == AgentIntent.MEDICATION_HISTORY.value and re.fullmatch(
            r"(?:what about |how about |那|查看)?"
            r"(?:yesterday|today|昨天|今天|\d{4}-\d{2}-\d{2})(?:呢|的记录)?[?？。.]?",
            text,
        ):
            history = True
        health = bool(re.search(r"health (?:notes|observations|records|data)|健康(?:记录|观察|感受|数据)", text))
        listing = (
            bool(
                re.search(
                    r"(?:what|which|list|show).*(?:medicines?|medications?)|(?:哪些药|什么药|用药清单|登记的药物|正在吃的药)",
                    text,
                )
            )
            and not question
            and not history
            and not re.search(r"should|due|计划|需要|要吃|今天吃什么药", text)
        )
        source = bool(re.search(r"\bsource|\bcitation|(?:information|answer|that|this).*come from|来源|依据", text))
        identify = (
            bool(re.search(r"第.+是什么|what is the (?:first|second|third) one", text)) and not question and not source
        )
        strengths = bool(re.search(r"other strengths?|其他规格", text))
        compare = bool(re.search(r"\bdiffer|区别|不同", text)) and not health
        pending = previous.choice
        # A name-only reply may resume a read intent from the latest saved user
        # question after restore. Old ordinal positions are never reconstructed.
        short_reply = len(text) <= 160 and not re.search(
            r"吃了|服了|took|taken|save|记录|提醒|double|increase|加量", text
        )
        displayed = previous.choice.options if previous.choice else previous.listed
        continuation = short_reply and bool(resolve_options(turn.text, displayed, allow_order=True))
        if not any(
            (
                question,
                history,
                health,
                listing,
                source
                and previous.topic == "medication"
                and (previous.listed or previous.subject_name or previous.answered_medication_ids),
                identify,
                strengths,
                compare and previous.listed,
                turn.medication_selection,
                continuation and displayed,
            )
        ):
            return None
        results: list[ToolResult] = []
        zh = turn.language == "zh"
        metadata = self._tools.context_metadata(patient_id)
        now = datetime.fromisoformat(str(metadata["current_time"]))

        def execute(name: str, arguments: dict[str, object]):
            output = self._tools.execute(
                name=name,
                arguments=arguments,
                patient_id=patient_id,
                session_id=session.id,
                correlation_id=self._ids.new_id(),
                client_turn_id=str(turn.slots.get("client_turn_id", "turn-1")),
                turn=turn,
            )
            results.extend(output.results)
            if (
                any(row.status != ToolStatus.SUCCESS for row in output.results)
                and "patient_safe_summary" not in output.data
            ):
                raise DomainError("Read unavailable")
            return output

        def answer(
            message: str,
            dialogue: MedicationDialogue,
            selected: MedicationOption | None = None,
            intent=AgentIntent.CLARIFICATION,
        ):
            return ReadAnswer(message, results, dialogue, selected, intent)

        try:
            if health:
                days = self._days(text, str(metadata["local_date"]))
                if days not in (7, 30):
                    return answer(
                        "健康观察查询目前支持最近7天或30天，请选择范围。"
                        if zh
                        else "Health observations currently support the past 7 or 30 days. Please choose one.",
                        previous.model_copy(update={"topic": "other", "choice": None}),
                    )
                data = execute("get_health_observations", {"days": days}).data
                return answer(
                    str(data["patient_safe_summary"]), previous.model_copy(update={"topic": "other", "choice": None})
                )
            if history:
                status_question = re.search(
                    r"^(?:did i (?:take|report taking)|have i (?:taken|reported taking))\s+(.+?)[?？.]*$",
                    turn.text,
                    re.I,
                )
                if status_question:
                    target = without_calendar_words(status_question[1]).strip(" ?？.,")
                    if target and target.casefold() not in {"it", "this", "that"}:
                        execute("get_dose_status", {"medication_name": target})
                        return answer(
                            status_reply(results[-1], turn.language),
                            previous.model_copy(update={"topic": "other", "choice": None}),
                            intent=AgentIntent.DOSE_STATUS_QUERY,
                        )
                days = self._days(text, str(metadata["local_date"]))
                params = {"days": days}
                match = re.search(r"(?:history|records) (?:for|of) (.+?)[?？.]*$", turn.text, re.I)
                if match:
                    target = without_calendar_words(match[1])
                    target = re.sub(
                        r"\b(?:this|last) (?:week|month)\b|\b(?:past|last) \d+ days?\b", " ", target, flags=re.I
                    )
                    target = re.sub(r"\b(?:for|during|from|in)\b", " ", target, flags=re.I).strip(" ?？.,")
                    if target:
                        params["medication_name"] = target
                elif (
                    session.context.last_intent == AgentIntent.MEDICATION_HISTORY.value
                    and previous.history_medication_id
                    and not re.search(r"\ball\b|全部|所有", text)
                ):
                    params["medication_id"] = str(previous.history_medication_id)
                execute("get_medication_history", params)
                return answer(
                    history_reply(results, turn.language),
                    previous.model_copy(
                        update={
                            "topic": "other",
                            "choice": None,
                            "history_medication_id": UUID(results[-1].payload["medication_id"])
                            if results[-1].payload.get("medication_id")
                            else None,
                        }
                    ),
                    intent=AgentIntent.MEDICATION_HISTORY,
                )
            listed = execute("list_active_medications", {})
            rows = listed.data["payload"]["medications"]
            options = [
                MedicationOption(
                    medication_id=row["medication_id"],
                    regimen_id=row["regimen_id"],
                    display_name=row["display_name"],
                    ingredient_names=row.get("ingredients", []),
                    label=(
                        row["display_name"]
                        + (
                            f" — {row['strength_text']}"
                            if row.get("strength_text")
                            and normalized(row["strength_text"]) not in normalized(row["display_name"])
                            else ""
                        )
                        + (
                            f" ({localized_form(str(row['dosage_form']), turn.language)})"
                            if row.get("dosage_form")
                            else ""
                        )
                    )[:300],
                )
                for row in rows
            ]
            version = medication_candidate_version(rows)
            state = MedicationDialogue(
                listed=options[:10], conversation_id=session.conversation_id, candidate_version=version
            )

            def clarify(q: str, prefix: str = "", candidates: list[MedicationOption] | None = None):
                target_name = question.get("medication_name") if question else pending.target_name if pending else None
                candidates = (
                    candidates
                    if candidates is not None
                    else (resolve_options(target_name, options, allow_order=False) if target_name else options)
                )
                if not target_name and candidates and len(candidates) < len(options):
                    mentioned = {
                        ingredient
                        for row in candidates
                        for ingredient in row.ingredient_names
                        if normalized(ingredient) in text
                    }
                    if len(mentioned) == 1:
                        target_name = mentioned.pop()
                if not candidates:
                    return answer(prefix + medication_list_reply(listed.results[0], turn.language), state)
                choice = MedicationChoice(
                    id=self._ids.new_id(),
                    question=q,
                    prompt=prefix + ("您想了解哪一种药物？" if zh else "Which medicine do you mean?"),
                    expires_at=now + timedelta(minutes=10),
                    options=candidates[:10],
                    target_name=target_name,
                    include_original=original if question else bool(pending and pending.include_original),
                )
                message = prefix + ("您想了解哪一种药物？" if zh else "Which medicine do you mean?")
                message += "\n" + "\n".join(f"{i}. {row.label}" for i, row in enumerate(choice.options, 1))
                if len(candidates) > 10:
                    message += (
                        "\n目前展示前10项，请输入药名缩小范围。"
                        if zh
                        else "\nShowing the first 10; enter a medicine name to narrow the list."
                    )
                return answer(message, state.model_copy(update={"choice": choice, "listed": []}))

            if listing:
                return answer(medication_list_reply(listed.results[0], turn.language), state)
            q = (
                question["question"]
                if question
                else pending.question
                if pending
                else "personal_instructions"
                if strengths
                else "general_use"
            )
            if turn.medication_selection:
                selection = turn.medication_selection
                if (
                    not pending
                    or selection.choice_id != pending.id
                    or pending.expires_at <= now
                    or previous.conversation_id != session.conversation_id
                    or previous.candidate_version != version
                ):
                    return clarify(
                        q,
                        "这个选择已失效，请重新选择。\n"
                        if zh
                        else "That choice has expired or changed. Please choose again.\n",
                    )
                selected = [row for row in pending.options if row.medication_id == selection.medication_id]
                if not selected:
                    return clarify(q, "无法使用这个选择。\n" if zh else "That selection is unavailable.\n")
            else:
                if pending and pending.expires_at <= now and not question:
                    return clarify(
                        q,
                        "之前的选项已过期，请重新选择。\n"
                        if zh
                        else "The earlier choices expired. Please choose again.\n",
                    )
                if pending and previous.candidate_version != version and not question:
                    return clarify(
                        q,
                        "药物资料已变化，请重新选择。\n"
                        if zh
                        else "Your medication data changed. Please choose again.\n",
                    )
                reliable_order = displayed if previous.candidate_version == version else []
                selected = resolve_options(turn.text, reliable_order or options, allow_order=bool(reliable_order))
                # A new question uses the full current catalogue, not stale pending choices.
                if question:
                    selected = resolve_options(turn.text, options, allow_order=False) or resolve_options(
                        turn.text, reliable_order, allow_order=bool(reliable_order)
                    )
                if selected:
                    selected = comparative_option(turn.text, selected, rows)
                if source and not selected and previous.topic == "medication" and previous.candidate_version == version:
                    selected = [row for row in options if row.medication_id in previous.answered_medication_ids]
                if not selected and question and question.get("medication_name"):
                    target = question["medication_name"]
                    if not re.search(
                        r"第|first|second|third|other|它|这个|我|这些|那|\bit\b|\bmy\b|\bthis\b|\bthese\b", target, re.I
                    ):
                        selected = resolve_options(target, options, allow_order=False)
                        if not selected:
                            output = execute("get_medication_understanding", {"medication_name": target, "question": q})
                            return answer(
                                str(output.data["patient_safe_summary"]),
                                state.model_copy(update={"subject_name": target}),
                            )
                plural = bool(
                    re.search(r"medicines|medications|这些|分别|各自|我(?:现在|目前|正在)?(?:吃|服用|用)的药", text)
                ) and not re.search(r"这个|this medicine|this medication", text)
                if plural or compare:
                    selected = options if not selected or compare else selected
                if not selected and (source or strengths or (question and previous.topic == "medication")):
                    reference = (
                        turn.navigation_context.medication_id
                        if turn.navigation_context
                        else session.context.referenced_medication_id
                    )
                    selected = [row for row in options if row.medication_id == reference]
                    if not selected and session.context.recent_turns and not previous.listed:
                        for recent in reversed(session.context.recent_turns):
                            if re.search(r"健康|health|history|记录", recent.user, re.I):
                                break
                            found = named_options(recent.user, options)
                            if len(found) == 1:
                                selected = found
                                break
                    if not selected and previous.subject_name and q == "general_use":
                        output = execute(
                            "get_medication_understanding", {"medication_name": previous.subject_name, "question": q}
                        )
                        return answer(
                            knowledge_sources_reply(output.data, turn.language)
                            if source
                            else str(output.data["patient_safe_summary"]),
                            state.model_copy(update={"subject_name": previous.subject_name}),
                        )
                if not selected and len(options) == 1 and not session.context.referenced_medication_id:
                    selected = options
            if not selected or len(selected) > 3 or (q != "general_use" and len(selected) > 1):
                return clarify(
                    q,
                    (
                        "每次可查询最多三种，请选择。\n"
                        if zh
                        else "Please choose up to three medicines for this request.\n"
                    )
                    if len(selected) > 3
                    else "",
                    candidates=selected or None,
                )
            if identify:
                return answer(
                    "\n".join(row.label for row in selected), state, selected[0] if len(selected) == 1 else None
                )
            if strengths:
                selected_names = {row.display_name for row in selected}
                ingredients = {
                    tuple(sorted(normalized(item) for item in row.ingredient_names))
                    for row in selected
                    if row.ingredient_names
                }
                related = [
                    row.label
                    for row in options
                    if row.display_name in selected_names
                    or (
                        row.ingredient_names
                        and tuple(sorted(normalized(item) for item in row.ingredient_names)) in ingredients
                    )
                ]
                return answer(
                    ("相同登记名称下目前的规格：\n" if zh else "Current entries with the same registered name:\n")
                    + "\n".join(related),
                    state,
                    selected[0] if len(selected) == 1 else None,
                )
            summaries = []
            matched_knowledge = False
            evidence_groups: dict[tuple[str, str], tuple[list[str], str, int]] = {}
            for row in selected:
                output = execute(
                    "get_medication_understanding", {"medication_id": str(row.medication_id), "question": q}
                )
                summary = (
                    knowledge_sources_reply(output.data, turn.language)
                    if source
                    else str(output.data["patient_safe_summary"])
                )
                if q == "personal_instructions" and (
                    original or (not question and pending and pending.include_original)
                ):
                    instructions = output.data.get("personal_instructions") or {}
                    raw = instructions.get("original_instructions")
                    summary = (
                        ("已核对的原始指示：\n" if zh else "Reviewed original instructions:\n") + raw
                        if raw
                        else (
                            "没有可读取的已核对原始指示。" if zh else "No reviewed original instructions are available."
                        )
                    )
                knowledge = output.data.get("general_knowledge")
                matched_knowledge = matched_knowledge or bool(knowledge and knowledge.get("status") == "matched")
                name = str(output.data.get("medication_name", ""))
                prefix = name + ("：" if zh else ": ")
                if q == "general_use" and not source:
                    summary = summary.removesuffix("\n\n" + knowledge_scope(turn.language))
                if (
                    q == "general_use"
                    and not compare
                    and knowledge
                    and knowledge.get("status") == "matched"
                    and summary.startswith(prefix)
                ):
                    body = summary[len(prefix) :]
                    # Share an identical sourced explanation, not a medication identity.
                    # All original names/strengths/IDs and tool reads remain distinct.
                    key = (
                        body,
                        json.dumps(
                            {
                                "sources": knowledge.get("sources", []),
                                "ingredients": sorted(normalized(item) for item in row.ingredient_names)
                                or [str(row.medication_id)],
                            },
                            sort_keys=True,
                        ),
                    )
                    if key in evidence_groups:
                        evidence_groups[key][0].append(name)
                    else:
                        evidence_groups[key] = ([name], prefix[len(name) :], len(summaries))
                        summaries.append("")
                else:
                    summaries.append(summary)
            for key, (names, separator, position) in evidence_groups.items():
                summaries[position] = " / ".join(names) + separator + key[0]
            prefix = (
                (
                    "以下分别来自标签的一般用途，不能据此判断药物可互换。\n"
                    if zh
                    else (
                        "These are separately sourced general uses, not evidence that the "
                        "medicines are interchangeable.\n"
                    )
                )
                if compare
                else ""
            )
            state = state.model_copy(update={"answered_medication_ids": [row.medication_id for row in selected]})
            message = prefix + "\n\n".join(summaries)
            if q == "general_use" and not source and matched_knowledge:
                message += "\n\n" + knowledge_scope(turn.language)
            return answer(message, state, selected[0] if len(selected) == 1 else None)
        except AuthenticationRequiredError:
            raise
        except ValidationError:
            return answer(
                "无法可靠解析这个查询；请注明药物及日期。历史范围支持最近1–30天或明确的单个日期。"
                if zh
                else (
                    "I could not safely resolve that query. Specify the medicine and d"
                    "ate; history supports the past 1–30 days or one explicit date."
                ),
                previous.model_copy(update={"choice": None}),
            )
        except DomainError:
            return answer(
                "暂时无法完成这项资料查询，请稍后重试；这不表示没有记录。"
                if zh
                else (
                    "This record lookup is temporarily unavailable. Please retry; this does not mean no records exist."
                ),
                previous.model_copy(update={"choice": None}),
            )

    @staticmethod
    def _days(text: str, local_date: str) -> int:
        match = re.search(r"(?:past|last|过去|最近)\s*(\d+)\s*(?:days?|天)", text)
        if match:
            days = int(match[1])
            if not 1 <= days <= 30:
                raise ValidationError("History supports 1–30 days; narrow the requested range")
            return days
        if re.search(r"this week|本周|这周", text):
            return datetime.fromisoformat(local_date).weekday() + 1
        return 30 if re.search(r"month|月", text) else 7
