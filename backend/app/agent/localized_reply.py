"""Chinese rendering of supported typed tool outcomes; never dosing inference."""

from ..contracts.enums import AgentIntent, ToolName
from .tools import ToolResult


def chinese_reply(intent: AgentIntent, results: list[ToolResult]) -> str:
    if not results:
        if intent == AgentIntent.REMINDER:
            return "您希望多久后提醒？可以选择 15 或 30 分钟。提醒不会改变用药计划。"
        return "请说明要查看的药物、用药记录或提醒。此演示助手不能提供新的用药建议。"
    last = results[-1]
    if last.requires_confirmation:
        return "请核对下方药物和自述内容，然后明确确认。确认前不会保存用药自述。患者自述不能证明实际吞服。"
    if last.blocked:
        return "无法完成此操作。请查看今日药物和记录，或先完成药物核对与激活。没有保存新的用药自述。"
    if last.tool_name == ToolName.CHECK_DUE_DOSE and last.payload.get("window") == "tonight":
        rows = last.payload.get("schedule", [])
        if not rows:
            return "已核对并激活的计划中，今晚没有安排用药（新加坡时间 18:00–24:00）。"
        descriptions = [
            f"{row['medication_name']}：{row['dose_amount']} {row['dose_unit']}，{row['local_time']}" for row in rows
        ]
        return "您已核对的今晚用药计划：" + "；".join(descriptions) + "。这仅显示已有计划，并非新的用药建议。"
    if intent == AgentIntent.DOSE_SELF_REPORT and last.tool_name != ToolName.RECORD_SELF_REPORT:
        state = ""
        if last.tool_name == ToolName.GET_DOSE_STATUS:
            status = last.payload.get("intake_status")
            state = {
                "reported_taken": "已有记录：您自述已服用。该记录不能证明实际吞服。",
                "reported_not_taken": "已有记录：您自述未服用。",
                "unsure": "已有记录：您自述不确定是否服用。",
            }.get(status, "今天没有已确认的自述记录；这不代表漏服。")
        return "不会因您的不确定而记录已服用。请查看记录或核对当前药物。" + state
    if last.tool_name == ToolName.RECORD_SELF_REPORT:
        return "已保存您的自述。此记录不能证明实际吞服。"
    if last.tool_name == ToolName.CREATE_REMINDER:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        time = (
            datetime.fromisoformat(last.payload["remind_at"]).astimezone(ZoneInfo("Asia/Singapore")).strftime("%H:%M")
        )
        return f"已保存提醒，时间为 {time}。应用打开或重新打开时可查看。用药计划没有改变。"
    if last.tool_name == ToolName.CHECK_DUE_DOSE:
        return f"当前有 {last.payload.get('item_count', 0)} 次已安排的用药到期，请在今日页面核对。"
    if last.tool_name == ToolName.GET_MEDICATION_HISTORY:
        return "请查看您的用药记录。没有自述记录不代表漏服。"
    return "请在今日页面查看药物，或在我的药物中完成核对与激活。"
