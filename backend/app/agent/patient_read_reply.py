"""Data-driven patient renderers. Stored times and reports never prove ingestion."""

from datetime import datetime
from zoneinfo import ZoneInfo

from .tools import ToolResult


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
    for index, row in enumerate(rows, 1):
        details = [str(row[key]) for key in ("strength_text", "dosage_form") if row.get(key)]
        label = str(row["display_name"]) + (" — " + ", ".join(details) if details else "")
        if row.get("is_prn"):
            label += "（按需使用）" if zh else " (as needed)"
        if row.get("identity_status") == "unverified":
            label += "（产品身份尚未核实）" if zh else " (product identity not yet verified)"
        lines.append(f"{index}. {label}")
    lines.append(
        "这是登记的用药清单，不能证明实际服用。" if zh else "This is your registered list, not proof of taking a dose."
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
