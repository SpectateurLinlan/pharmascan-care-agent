"""Bounded long-term read tools and proposals; this adapter cannot confirm writes."""

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Literal
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from ..application.long_term import LongTermCareService
from ..contracts.long_term import (
    BarrierInput,
    BarrierKind,
    CareReview,
    CareTaskInput,
    CountUnit,
    StockInput,
    StockKind,
    TaskCategory,
    TaskStatus,
    TaskUpdate,
)
from ..domain.errors import NotFoundError


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ReadCare(Arguments):
    days: Literal[7, 30] = 30


class Inventory(Arguments):
    medication_id: UUID


class ProposeStock(Inventory):
    kind: StockKind
    quantity: float = Field(ge=-100000, le=100000)
    unit: CountUnit
    low_threshold: float = Field(default=7, ge=0, le=10000)


class ProposeBarrier(Arguments):
    category: BarrierKind
    occurred_at: AwareDatetime
    regimen_id: UUID | None = None
    chosen_action: str = Field(default="", max_length=500)


class ProposeTask(Arguments):
    category: TaskCategory
    title: str = Field(min_length=1, max_length=160)
    due_at: AwareDatetime
    medication_id: UUID | None = None
    regimen_id: UUID | None = None


class ProposeUpdate(Arguments):
    task_id: UUID
    status: TaskStatus
    due_at: AwareDatetime | None = None


class ClarifyCare(Arguments):
    missing_field: Literal[
        "medication",
        "stock_quantity",
        "stock_unit",
        "follow_up_date",
        "follow_up_type",
        "barrier_time",
        "support_action",
    ]


CARE_SPECS = MappingProxyType(
    {
        "clarify_medication_care": (
            ClarifyCare,
            "Ask one controlled question for missing medicine/count/unit/date/action. "
            "Use before proposing a care change when necessary details are unknown. Never guess.",
        ),
        "get_medication_inventory": (
            Inventory,
            "Read confirmed count, estimated stock, units and supply concerns for an owned medication.",
        ),
        "get_adherence_history": (
            ReadCare,
            "Read reported dose statuses and patient-reported barriers. Unrecorded is not missed.",
        ),
        "get_health_observations": (
            ReadCare,
            "Read patient-reported observations and compatible-unit trends; never infer causality.",
        ),
        "get_longitudinal_summary": (
            ReadCare,
            "Read current persisted medication care context for a week/month. Do not use old chat as truth.",
        ),
        "prepare_medication_review": (
            ReadCare,
            "Required for pharmacist/doctor visit preparation or combined symptoms and follow-ups. "
            "Read medication reports, health observations, supply, barriers and unresolved tasks together.",
        ),
        "get_unresolved_follow_ups": (
            ReadCare,
            "Read still-open medication-related care tasks from persistent patient records.",
        ),
        "prepare_stock_change": (
            ProposeStock,
            "Prepare a stock count/refill/adjustment for human confirmation. "
            "Never save; clarify units, medicine and quantity first.",
        ),
        "prepare_adherence_barrier": (
            ProposeBarrier,
            "Prepare review of the patient's stated medication difficulty and chosen action. "
            "Never infer missed doses or save.",
        ),
        "prepare_medication_care_task": (
            ProposeTask,
            "Prepare patient-reported medication follow-up for human review. Clarify date and medicine. "
            "No vaccines, general screening or clinical recommendations.",
        ),
        "prepare_care_task_update": (
            ProposeUpdate,
            "Prepare completion, pharmacy-contacted, defer or cancel of an owned task; human confirmation is required.",
        ),
    }
)


@dataclass(frozen=True)
class CareToolOutput:
    data: dict[str, object]
    review: CareReview | None = None


def _describe_trends(trends: list[dict[str, object]], language: str, timezone: str) -> str:
    """Describe actual endpoints/counts, not targets, diagnoses or medication effects."""
    text = ""
    for row in trends[:3]:
        points = row["points"]
        first, last = points[0], points[-1]
        start = datetime.fromisoformat(row["start"]).astimezone(ZoneInfo(timezone)).isoformat()
        end = datetime.fromisoformat(row["end"]).astimezone(ZoneInfo(timezone)).isoformat()
        kind, unit, count = row["kind"], row["unit"], row["count"]
        label = {
            "blood_pressure": ("blood pressure", "血压"),
            "blood_glucose": ("blood glucose", "血糖"),
            "weight": ("weight", "体重"),
            "sleep": ("sleep", "睡眠"),
            "mood": ("mood", "心情"),
        }.get(kind, ("measurement", "测量"))[language == "zh"]
        if count < 2:
            text += (
                f" {label}：仅 {count} 条 {unit} 记录，不足以描述变化。"
                if language == "zh"
                else f" {label}: only {count} {unit} record; insufficient to describe change."
            )
            continue
        a, b = str(first["value"]), str(last["value"])
        delta = f"{row['change']:+g}"
        if kind == "blood_pressure":
            a += f"/{first['secondary_value']}"
            b += f"/{last['secondary_value']}"
            delta += f"/{last['secondary_value'] - first['secondary_value']:+g}"
        text += (
            f" {label}：{count} 条记录，{start} 至 {end}，从 {a} 到 {b} {unit}，首末差值 {delta} {unit}。"
            if language == "zh"
            else f" {label}: {count} records, {start} to {end}; "
            f"first {a}, last {b} {unit}, endpoint change {delta} {unit}."
        )
    if text:
        text += (
            " 测量时间不规则；缺失测量未知，不能据此判断药物因果或临床改善。"
            if language == "zh"
            else " Sampling is irregular; missing measurements are unknown. "
            "These differences do not establish medication effects or clinical improvement."
        )
    return text


def execute_care_tool(
    service: LongTermCareService,
    *,
    name: str,
    arguments: dict[str, object],
    patient_id: UUID,
    session_id: UUID,
    turn_id: str,
    text: str,
    language: str,
    timezone: str,
) -> CareToolOutput:
    params = CARE_SPECS[name][0].model_validate(arguments).model_dump()
    key = uuid5(session_id, turn_id + ":" + name)
    review = None
    if name == "clarify_medication_care":
        questions = {
            "medication": (
                "Which registered medicine do you mean? Please include its strength or choose it in Medicines.",
                "您指的是哪一种已登记药物？请注明规格，或到药物页面选择。",
            ),
            "stock_quantity": (
                "How many units have you physically counted? If you are unsure, we can leave stock unknown.",
                "您实际清点了多少片或粒？不确定时可以保留库存未知。",
            ),
            "stock_unit": (
                "Are you counting tablets or capsules? I cannot convert medicine strength into a unit count.",
                "您清点的是药片还是胶囊？我不能把药品规格换算成片数或粒数。",
            ),
            "follow_up_date": (
                "What date and time would you like for this medication follow-up? Please confirm your time zone.",
                "您希望哪一天、什么时间进行这项用药跟进？请同时确认时区。",
            ),
            "follow_up_type": (
                "Is this a medication review, supply check or another medication-related follow-up?",
                "这是用药复查、余量核对，还是其他与用药有关的跟进？",
            ),
            "barrier_time": (
                "When did this medication difficulty occur? You can choose to record how you feel now.",
                "这次用药困难发生在什么时候？也可以选择记录您现在的情况。",
            ),
            "support_action": (
                "What support would you like to record, such as reviewing reminders "
                "or preparing a pharmacist question?",
                "您希望记录什么支持措施，例如查看提醒设置，或整理向药剂师咨询的问题？",
            ),
        }
        question = questions[params["missing_field"]][1 if language == "zh" else 0]
        return CareToolOutput(
            {"patient_safe_summary": question, "care_clarification": {"missing_field": params["missing_field"]}}
        )
    if name == "get_medication_inventory":
        stock = service.inventory(patient_id, params["medication_id"], timezone)
        amount = stock.estimated_remaining
        summary = (
            f"估算余量：{amount if amount is not None else '未知'} {stock.unit or ''}。请盘点核对；未报告的消耗未知。"
            if language == "zh"
            else f"Estimated remaining: {amount if amount is not None else 'unknown'} {stock.unit or ''}. "
            "Please count to confirm; unreported consumption is unknown."
        )
        return CareToolOutput(
            {"inventory": stock.model_dump(mode="json", exclude={"transactions"}), "patient_safe_summary": summary}
        )
    if name == "prepare_stock_change":
        medication_id = params.pop("medication_id")
        service.inventory(patient_id, medication_id, timezone)
        review = CareReview(
            action="stock", medication_id=medication_id, stock=StockInput(id=key, **params, note=text[:500])
        )
    elif name == "prepare_adherence_barrier":
        # Persist the patient's words only after their review, never a generated diagnosis.
        review = CareReview(action="barrier", barrier=BarrierInput(id=key, **params, description=text[:1000]))
    elif name == "prepare_medication_care_task":
        review = CareReview(action="task", task=CareTaskInput(id=key, **params, notes=text[:1000]))
    elif name == "prepare_care_task_update":
        task_id = params.pop("task_id")
        task = next((row for row in service.tasks(patient_id) if row.id == task_id), None)
        if task is None:
            raise NotFoundError("Follow-up not found for this patient")
        review = CareReview(
            action="task_update",
            task_id=task_id,
            task_update=TaskUpdate(id=key, expected_version=task.version, **params, notes=text[:1000]),
        )
    if review:
        service.validate_proposal(patient_id, review)
        summary = (
            "请核对下面的用药管理记录，再点击确认保存。取消不会写入；这不会修改医嘱或服药记录。"
            if language == "zh"
            else "Review the proposed medication-care record, then confirm to save. "
            "Cancel saves nothing. This does not change instructions or dose reports."
        )
        return CareToolOutput({"requires_patient_review": True, "patient_safe_summary": summary}, review)
    data = service.review(patient_id, params["days"], timezone).model_dump(
        mode="json",
        exclude={
            "barriers": {"__all__": {"patient_id"}},
            "follow_ups": {"__all__": {"patient_id", "history"}},
            "summary": {"observations": {"__all__": {"patient_id"}}},
            "observations": {"__all__": {"patient_id"}},
        },
    )
    summary_data = data["summary"]
    names = ", ".join(dict.fromkeys(row["name"] for row in summary_data["medications"])) or (
        "无" if language == "zh" else "none"
    )
    if language == "zh":
        summary = (
            f"这段时间记录了 {names} 的用药情况：您自述已服 {summary_data['reported_taken']} 次、"
            f"未服 {summary_data['reported_not_taken']} 次、"
            f"不确定 {summary_data['unsure']} 次。尚未记录不等于未服。"
            f"另有 {len(data['barriers'])} 项已记录的用药困难、{len(data['follow_ups'])} 项待跟进事项。"
        )
    else:
        summary = (
            f"Medicines in this period: {names}. Patient-reported taken: {summary_data['reported_taken']}; "
            f"not taken: {summary_data['reported_not_taken']}; unsure: {summary_data['unsure']}. "
            f"Unrecorded does not mean missed. Reported difficulties: {len(data['barriers'])}; "
            f"open follow-ups: {len(data['follow_ups'])}."
        )
    if name == "get_health_observations":
        summary = ""  # Answer the health query directly; medication totals belong to a combined review.
    overview = summary
    for task in [] if name == "get_health_observations" else data["follow_ups"][:4]:
        medication = next(
            (row["name"] for row in summary_data["medications"] if row["medication_id"] == task["medication_id"]), None
        )
        title = task["title"]
        if language == "zh" and task["source"] == "stock_estimate" and title == "Review medication supply":
            title = "核对药物余量与补药"
        label = f"{medication}: {title}" if medication else title
        due = task["due_at"]
        # Date-only values remain dates; aware instants display in the supplied patient zone.
        if "T" in due:
            moment = datetime.fromisoformat(due.replace("Z", "+00:00"))
            if moment.tzinfo is not None:
                due = moment.astimezone(ZoneInfo(timezone)).strftime("%Y-%m-%d %H:%M") + f" ({timezone})"
        summary += f" {'自述跟进' if language == 'zh' else 'Reported follow-up'}: “{label}” ({due})."
    for barrier in [] if name == "get_health_observations" else data["barriers"][-2:]:
        summary += f" {'自述困难' if language == 'zh' else 'Reported difficulty'}: “{barrier['description'][:160]}”."
    if name != "get_unresolved_follow_ups":
        notes = data["observations"]
        summary += (
            f"\n符合本次范围的健康观察共 {len(notes)} 条。"
            if language == "zh"
            else f"\nHealth observations in this query: {len(notes)}."
        )
        for note in notes[:10]:
            moment = datetime.fromisoformat(note["occurred_at"].replace("Z", "+00:00"))
            when = moment.astimezone(ZoneInfo(timezone)).strftime("%Y-%m-%d %H:%M")
            value = note.get("value")
            measurement = (
                ""
                if value is None
                else f" {value:g}"
                + (f"/{note['secondary_value']:g}" if note.get("secondary_value") is not None else "")
                + f" {note.get('unit') or ''}"
            )
            summary += f"\n- {when} ({timezone}){measurement}: “{note['description'][:200]}”"
            if len(note["description"]) > 200:
                summary += (
                    "（描述节选，完整内容见健康记录）" if language == "zh" else " (excerpt; full text in Health notes)"
                )
        if len(notes) > 10:
            summary += (
                "\n仅展开最近10条，其余请查看全部健康记录。"
                if language == "zh"
                else "\nShowing the latest 10; view all remaining entries in Health notes."
            )
    if name in ("get_health_observations", "get_longitudinal_summary", "prepare_medication_review"):
        trends_text = _describe_trends(data["trends"], language, timezone)
        if trends_text:
            summary += "\n" + trends_text.strip()
    if name == "prepare_medication_review":
        details = summary[len(overview) :]
        summary = overview
        questions = data.get("questions", [])
        if questions:
            translated = {
                "Which scheduled doses still need a patient report?": "哪些已有计划剂次还需要补充自述？",
                (
                    "Are there feelings or symptoms you would like to discuss with a healthcare professional?"
                ): "有哪些感受或症状希望与医护人员讨论？",
                "Is the intended course end date documented in your reviewed instructions?": (
                    "已核对的指示是否注明了疗程结束日期？"
                ),
                "Discuss your reported medication difficulties and chosen support actions.": (
                    "讨论已记录的用药困难和您选择的应对方式。"
                ),
                "Check medication supply and refill arrangements with your pharmacy.": "向药房核对药物余量和补药安排。",
            }
            summary += "\n复诊可讨论的问题：" if language == "zh" else "\nQuestions to discuss at your visit:"
            summary += "\n" + "\n".join("- " + (translated.get(q, q) if language == "zh" else q) for q in questions)
        summary += (
            "\n请带上用药清单，向医生或药剂师核对仍不确定的记录及后续安排。\n记录依据："
            if language == "zh"
            else "\nBring your medication list and ask your doctor or pharmacist to clarify uncertain records "
            "and next steps.\nSupporting records:"
        ) + details
    # Return only the requested minimum. UI has the full patient-review endpoint.
    sections = {
        "get_adherence_history": {"barriers"},
        "get_health_observations": {"trends"},
        "get_unresolved_follow_ups": {"follow_ups"},
    }.get(name, {"barriers", "inventory", "follow_ups", "questions", "trends"})
    bounded = {key: value[:5] if isinstance(value, list) else value for key, value in data.items() if key in sections}
    if name in ("get_health_observations", "get_longitudinal_summary", "prepare_medication_review"):
        bounded["observation_count"] = len(data["observations"])
        bounded["observations"] = [
            {
                **row,
                "description": row["description"][:200],
                "notes": None,
                "description_truncated": len(row["description"]) > 200,
            }
            for row in data["observations"][:10]
        ]
    # Trends are bounded to the latest six actual measurements in model context.
    if "trends" in bounded:
        bounded["trends"] = [{**row, "points": row["points"][-6:]} for row in bounded["trends"]]
    return CareToolOutput({**bounded, "patient_safe_summary": summary})
