"""Render dates and individual dose states without inferring ingestion."""

from datetime import datetime
from zoneinfo import ZoneInfo

from .tools import ToolResult


def status_reply(result: ToolResult, language: str) -> str:
    payload = result.payload
    chinese = language == "zh"
    name = payload.get("medication_name") or ("该药物" if chinese else "that medicine")
    day = payload.get("local_date", "")
    relative = payload.get("relative_day")
    label = (
        ("今天" if chinese else "today")
        if relative in {None, 0}
        else (("昨天" if chinese else "yesterday") if relative == -1 else day)
    )
    label = f"{label} ({day})" if day else label
    zone = ZoneInfo(payload.get("local_timezone", "Asia/Singapore"))
    records = [row for row in payload.get("records", []) if not row.get("future")]
    if not records:
        records = [{"intake_status": payload.get("intake_status", "no_report"), "event_time": None}]
    descriptions = []
    for row in records:
        instant = row.get("due_at") or row.get("event_time")
        time = datetime.fromisoformat(instant).astimezone(zone).strftime("%H:%M") if instant else ""
        reported = row.get("reported_at")
        if reported:
            report_time = datetime.fromisoformat(reported).astimezone(zone).strftime("%Y-%m-%d %H:%M")
            time += f" ({'提交于' if chinese else 'reported at'} {report_time})"
        state = row["intake_status"]
        if chinese:
            text = {
                "reported_taken": "您自述已服用",
                "reported_not_taken": "您自述未服用",
                "unsure": "您自述不确定是否服用",
            }.get(state, "没有记录服用情况，无法判断是否服用")
        else:
            text = {
                "reported_taken": "You reported taking",
                "reported_not_taken": "You reported not taking",
                "unsure": "You reported being unsure whether you took",
            }.get(state, "No confirmed dose record; I cannot tell whether you took")
        descriptions.append(f"{time} {text} {name}".strip())
    boundary = "不会推断实际服药情况。" if chinese else "I will not guess whether you took it."
    if any(row["intake_status"] == "reported_taken" for row in records):
        boundary = "患者自述不能证明实际吞服。" if chinese else "A self-report does not prove ingestion."
    if any(row["intake_status"] == "no_report" for row in records):
        boundary += " 没有记录不等于漏服。" if chinese else " No report is not the same as a missed dose."
    return f"{label}: " + "; ".join(descriptions) + ". " + boundary
