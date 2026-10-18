"""Bounded, read-only discovery before clarifying a contextual medicine-use question."""

import re
import unicodedata
from dataclasses import dataclass
from uuid import UUID

from ..contracts.agent_context import CandidateReference
from ..contracts.enums import ToolStatus
from ..domain.errors import ProviderUnavailableError
from .model_tools import ExecutedTool, ModelTools
from .orchestrator import AgentTurn
from .tools import ToolResult


def current_medication_question(text: str) -> bool | None:
    """Return plural intent, or None for questions outside this narrow read path."""
    value = text.strip().rstrip("?？。.").casefold()
    if any(token in value for token in ("@", "://", "\n")):
        return None
    chinese = re.fullmatch(
        r"(?:请问|请告诉我)?(?:我(?:现在|目前|正在)?(?:吃|服用|用)的(?:这个|这几种|这些)?|这个|这些)药(?:品|物)?"
        r"(?:分别|各自|都)?(?:有什么作用|有什么用|是做什么用的|有什么功效)",
        value,
    )
    english = re.fullmatch(
        r"what (?:is|are) (?:(?:my (?:current )?|this |these )(?:medicine|medication)s?|"
        r"(?:this|the) (?:medicine|medication) (?:i am|i'm) taking) (?:used for|for)",
        value,
    )
    if not chinese and not english:
        return None
    return any(token in value for token in ("这些", "这几种", "分别", "各自", "medicines", "medications"))


@dataclass(frozen=True)
class CurrentMedicationAnswer:
    message: str
    results: list[ToolResult]
    awaiting_choice: bool = False
    selected_reference: CandidateReference | None = None


def matching_medication_choices(text: str, rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Exact name/prefix only; strength/form suffixes may narrow but never break a tie."""

    def normalize(value: str) -> str:
        value = unicodedata.normalize("NFKC", value).casefold().strip()
        value = re.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", " ", value)
        return re.sub(r"\s+", " ", value)

    choice = normalize(text)
    if not choice or len(choice) > 160 or not re.fullmatch(r"[\w .+()/%-]+", choice):
        return []
    matches = []
    for row in rows:
        name = normalize(str(row["display_name"]))
        if name == choice or name.startswith(choice + " "):
            matches.append(row)
    return matches


def read_current_medication_uses(
    *,
    tools: ModelTools,
    patient_id: UUID,
    session_id: UUID,
    correlation_id: UUID,
    turn: AgentTurn,
    reference: UUID | None,
    plural: bool,
    choice: str | None = None,
) -> CurrentMedicationAnswer | None:
    """Use server-owned references only; list + at most three knowledge reads."""
    results: list[ToolResult] = []
    zh = turn.language == "zh"
    unavailable = (
        "暂时无法读取用药资料，请稍后重试。" if zh else "Medication information is unavailable. Please retry later."
    )

    def execute(name: str, arguments: dict[str, object]) -> ExecutedTool:
        executed = tools.execute(
            name=name,
            arguments=arguments,
            patient_id=patient_id,
            session_id=session_id,
            correlation_id=correlation_id,
            client_turn_id=str(turn.slots.get("client_turn_id", "turn-1")),
            turn=turn,
        )
        results.extend(executed.results)
        return executed

    try:
        listed = execute("list_active_medications", {})
    except ProviderUnavailableError:
        return CurrentMedicationAnswer(unavailable, results)
    if not listed.results or any(row.status != ToolStatus.SUCCESS for row in listed.results):
        return CurrentMedicationAnswer(unavailable, results)
    rows = listed.data.get("payload", {}).get("medications", [])
    if not rows:
        return CurrentMedicationAnswer(
            "您的账户目前没有已激活的用药计划。您可以到药物页面完成登记与核对。"
            if zh
            else "Your account has no active medication plans. You can finish setup and review in Medicines.",
            results,
        )
    selected = (
        matching_medication_choices(choice, rows)
        if choice is not None
        else rows
        if plural
        else [row for row in rows if str(row["medication_id"]) == str(reference)]
    )
    if choice is not None and not selected:
        return None  # A different topic/action must still go through its normal policy path.
    if choice is None and not selected and reference is None and len(rows) == 1:
        selected = rows
    if not selected or len(selected) > 3 or (choice is not None and len(selected) != 1):
        names = "、".join(str(row["display_name"]) for row in rows)
        message = (
            f"您目前登记的用药有：{names}。请问您想了解哪一种？"
            if zh
            else f"Your active medicines are: {names}. Which would you like to learn about?"
        )
        if plural:
            message += " 每次可查询最多三种，请先选择。" if zh else " Please choose up to three for this request."
        return CurrentMedicationAnswer(message, results, awaiting_choice=True)
    summaries = []
    for row in selected:
        try:
            explained = execute(
                "get_medication_understanding",
                {
                    "medication_id": str(row["medication_id"]),
                    "question": "general_use",
                },
            )
            summaries.append(f"{row['display_name']}\n{explained.data['patient_safe_summary']}")
        except ProviderUnavailableError:
            summaries.append(f"{row['display_name']}: {unavailable}")
    selected_reference = (
        CandidateReference.model_validate(
            {key: selected[0][key] for key in ("medication_id", "regimen_id", "display_name")}
        )
        if len(selected) == 1
        else None
    )
    return CurrentMedicationAnswer("\n\n".join(summaries), results, selected_reference=selected_reference)
