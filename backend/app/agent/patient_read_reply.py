"""Data-driven patient renderers. Stored times and reports never prove ingestion."""

from datetime import datetime
from zoneinfo import ZoneInfo

from .tools import ToolResult


def localized_form(value: str, language: str) -> str:
    if language != "zh":
        return value
    return {"tablet": "片剂", "tablets": "片剂", "capsule": "胶囊", "capsules": "胶囊", "oral": "口服"}.get(
        value.lower(), value
    )


def local_time(value: object, timezone: str) -> str:
    if not value:
        return ""
    moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return moment.astimezone(ZoneInfo(timezone)).strftime("%Y-%m-%d %H:%M")


def medication_list_reply(result: ToolResult, language: str) -> str:
    zh = language == "zh"
    rows = result.payload.get("medications", [])
    heading = "目前有效的已登记用药：" if zh else "Your currently active registered medicines:"
    if not rows:
        return (
            "您的账户目前没有已激活且有效的用药计划。"
            if zh
            else "You have no currently active registered medication plans."
        )
    lines = [heading]
    for index, row in enumerate(rows[:20], 1):
        name = str(row["display_name"])
        details = [
            (
                {"tablet": "片剂", "tablets": "片剂", "capsule": "胶囊", "capsules": "胶囊", "oral": "口服"}.get(
                    str(row[key]).lower(), str(row[key])
                )
                if zh
                else str(row[key])
            )
            for key in ("strength_text", "dosage_form")
            if row.get(key) and str(row[key]).replace(" ", "").casefold() not in name.replace(" ", "").casefold()
        ]
        label = str(row["display_name"]) + (" — " + ", ".join(details) if details else "")
        if row.get("is_prn"):
            label += "（按需使用）" if zh else " (as needed)"
        if row.get("identity_status") == "unverified":
            label += "（产品身份尚未核实）" if zh else " (product identity not yet verified)"
        lines.append(f"{index}. {label}")
    if len(rows) > 20:
        lines.append(
            f"本次显示前20项，共{len(rows)}项有效登记；这不是完整清单，其余请在药物页查看或指定药名查询。"
            if zh
            else f"Showing the first 20 of {len(rows)} active registrations, not the complete list. "
            "View remaining entries in Medicines or ask about a named medicine."
        )
    lines.append(
        "这是登记的用药清单，不能证明实际服用。" if zh else "This is your registered list, not proof of taking a dose."
    )
    return "\n".join(lines)


def knowledge_sources_reply(data: dict, language: str) -> str:
    """Source follow-ups answer provenance, without repeating the indications."""
    knowledge = data.get("general_knowledge") or {}
    sources = knowledge.get("sources") or []
    if not sources:
        return (
            "本次没有可核实的知识来源，请稍后重试；不会用无来源的医学知识补充。"
            if language == "zh"
            else "No reliable knowledge source was available for this lookup. Please retry later."
        )
    name = str(data.get("medication_name") or "")
    lines = [
        f"{name}：回答依据是以下美国药品标签。"
        if language == "zh"
        else f"{name}: this answer uses the following US drug labels."
    ]
    lines.extend(
        f"- openFDA / SPL{(' — ' + row['label_name']) if row.get('label_name') else ''} "
        f"· {row['effective_time']} · v{row['version']}: {row['url']}"
        for row in sources
    )
    lines.append(
        "这些标签支持一般成分用途，不代表已确认您持有的具体产品或个人处方。"
        if language == "zh"
        else (
            "These support general ingredient uses; they do not "
            "confirm your particular product or personal prescription."
        )
    )
    return "\n".join(lines)


def history_reply(results: list[ToolResult], language: str) -> str:
    zh = language == "zh"
    payload = results[0].payload
    timezone = str(payload.get("local_timezone", "Asia/Singapore"))
    start, end = local_time(payload.get("window_start"), timezone), local_time(payload.get("window_end"), timezone)
    lines = [(f"服药记录：{start} 至 {end}（{timezone}）" if zh else f"Dose records: {start} to {end} ({timezone})")]
    rows = [row for result in results for row in result.payload.get("entries", [])]
    rows.sort(key=lambda row: str(row.get("due_at") or row.get("event_time") or ""), reverse=True)
    labels = {
        "reported_taken": ("you reported taking this dose", "您自述已服用"),
        "reported_not_taken": ("you reported not taking this dose", "您自述未服用"),
        "unsure": ("you were unsure whether you took this dose", "您自述不确定是否服用"),
    }
    for row in rows[:30]:
        status = labels.get(
            row.get("intake_status") if row.get("reported") else None, ("not yet recorded", "尚未记录")
        )[zh]
        when = local_time(row.get("due_at") or row.get("event_time"), timezone)
        kind = (
            ("计划时点" if zh else "scheduled time")
            if row.get("due_at")
            else ("自述事件时点" if zh else "report event time")
        )
        name = str(row.get("display_name", ""))
        strength = row.get("strength_text")
        if strength and str(strength).casefold() not in name.casefold():
            name += f" — {strength}"
        reported = local_time(row.get("event_time"), timezone)
        report_note = (
            (f"；自述事件时点：{reported}" if zh else f"; self-report event time: {reported}")
            if reported and row.get("due_at")
            else ""
        )
        lines.append(f"- {name} — {when} ({kind}): {status}{report_note}.")
    if not rows:
        lines.append("此范围没有可读取的记录。" if zh else "No stored records were found in this period.")
    total = sum(int(result.payload.get("item_count", len(result.payload.get("entries", [])))) for result in results)
    if total > min(len(rows), 30):
        lines.append(
            f"显示最近{min(len(rows), 30)}条，共{total}条；其余明细请在记录页查看。"
            if zh
            else f"Showing the latest {min(len(rows), 30)} of {total} records; view remaining details in Records."
        )
    lines.append(
        "尚未记录不等于未服；计划时点不是实际吞服时间。本查询不补建历史剂次，未来计划不计入历史。"
        if zh
        else (
            "Unrecorded does not mean missed. Scheduled time is not ingestion "
            "time. This read does not reconstruct historical doses; future dos"
            "es are excluded."
        )
    )
    return "\n".join(lines)
