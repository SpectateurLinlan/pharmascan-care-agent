"""Patient-readable schedule facts grounded only in typed application results."""

from .tools import ToolResult


def schedule_reply(result: ToolResult, language: str) -> str:
    chinese = language == "zh"
    window = result.payload.get("window", "due")
    rows = result.payload.get("schedule" if window in {"tonight", "today"} else "due_doses", [])
    timezone = result.payload.get("local_timezone", "Asia/Singapore")
    if not rows:
        if window == "due":
            return (
                "当前没有已到期的固定用药安排。这不代表今天稍后没有安排，按需用药也不属于固定时间安排。"
                if chinese
                else "No scheduled dose is due right now. "
                "Later doses and as-needed medicines are separate from this result."
            )
        label = "今晚" if window == "tonight" else "今天"
        return (
            f"已核对的计划中，{label}没有固定时间的用药安排（{timezone}）。按需用药不列入固定安排。"
            if chinese
            else f"No fixed dose is scheduled in your reviewed active record {window} "
            f"({timezone}). As-needed medicines have no fixed schedule."
        )
    descriptions = []
    for row in rows:
        amount = row["dose_amount"]
        quantity = str(int(amount)) if isinstance(amount, (int, float)) and float(amount).is_integer() else str(amount)
        unit = row["dose_unit"]
        if chinese:
            unit = {"tablet": "片", "capsule": "粒", "mg": "毫克", "ml": "毫升", "mL": "毫升"}.get(unit, unit)
        report = row.get("intake_status", "not_reported")
        state = {
            "reported_taken": "自述已服用" if chinese else "patient reported taken",
            "reported_not_taken": "自述未服用" if chinese else "patient reported not taken",
            "unsure": "自述不确定" if chinese else "patient is unsure",
            "not_reported": "尚无自述记录" if chinese else "no patient report",
        }.get(report, "尚无自述记录" if chinese else "no patient report")
        descriptions.append(
            f"{row['medication_name']}：{quantity} {unit}，{row['local_time']}（{state}）"
            if chinese
            else f"{row['medication_name']}: {quantity} {unit} at {row['local_time']} ({state})"
        )
    if chinese:
        heading = (
            "当前已到期的安排"
            if window == "due"
            else "您已核对的" + ("今晚" if window == "tonight" else "今天") + "用药计划"
        )
        return (
            f"{heading}（{timezone}）："
            + "；".join(descriptions)
            + "。仅显示已有计划，不是新的用药建议；没有自述记录不等于漏服。"
        )
    heading = "Scheduled doses due now" if window == "due" else "Your reviewed schedule " + window
    return (
        f"{heading} ({timezone}): "
        + "; ".join(descriptions)
        + ". These are recorded instructions. No report does not mean a missed dose."
    )
