"""Bounded, read-only discovery before clarifying a contextual medicine-use question."""

import re
from dataclasses import dataclass
from uuid import UUID

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


def read_current_medication_uses(
    *,
    tools: ModelTools,
    patient_id: UUID,
    session_id: UUID,
    correlation_id: UUID,
    turn: AgentTurn,
    reference: UUID | None,
    plural: bool,
) -> CurrentMedicationAnswer:
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
    selected = rows if plural else [row for row in rows if str(row["medication_id"]) == str(reference)]
    if not selected and reference is None and len(rows) == 1:
        selected = rows
    if not selected or len(selected) > 3:
        names = "、".join(str(row["display_name"]) for row in rows)
        message = (
            f"您目前登记的用药有：{names}。请问您想了解哪一种？"
            if zh
            else f"Your active medicines are: {names}. Which would you like to learn about?"
        )
        if plural:
            message += " 每次可查询最多三种，请先选择。" if zh else " Please choose up to three for this request."
        return CurrentMedicationAnswer(message, results)
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
            summaries.append(str(explained.data["patient_safe_summary"]))
        except ProviderUnavailableError:
            summaries.append(f"{row['display_name']}: {unavailable}")
    return CurrentMedicationAnswer("\n\n".join(summaries), results)
