"""Bounded explicit field capture. Captured text is unreviewed patient input."""

import re
import unicodedata
from copy import deepcopy

_UNITS = {
    "片": "tablet",
    "tablet": "tablet",
    "tablets": "tablet",
    "粒": "capsule",
    "capsule": "capsule",
    "capsules": "capsule",
    "mg": "mg",
    "毫克": "mg",
    "ml": "ml",
    "毫升": "ml",
}
_COUNT = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "once": 1,
    "twice": 2,
}
_DOSE = r"([0-9]+(?:\.[0-9]+)?)\s*(tablets?|capsules?|毫克|毫升|片|粒|mg|ml)"


def collection_control(text: str) -> str | None:
    value = unicodedata.normalize("NFKC", text).strip().casefold().rstrip("。.!！")
    if value in {"pause", "pause task", "暂停", "暂停办理"}:
        return "pause"
    if value in {"resume", "resume task", "继续办理", "恢复办理"}:
        return "resume"
    return None


def collection_prompt_request(text: str) -> bool:
    value = unicodedata.normalize("NFKC", text).strip().casefold().rstrip("。.!！?？")
    return value in {
        "continue",
        "please continue",
        "next",
        "what details do you need",
        "what else",
        "继续",
        "继续录入",
        "下一步",
        "还需要什么",
        "需要什么资料",
    }


def outside_collection(text: str) -> bool:
    if collection_prompt_request(text):
        return False
    value = unicodedata.normalize("NFKC", text).strip()
    return bool(
        re.match(
            r"^(?:check|show|list|view|what|how|why|should|can|could)\b|^(?:查询|查看|检查|请问|为什么|是否)",
            value,
            re.I,
        )
        or "?" in value
        or "？" in value
    )


def collect_enrollment_message(
    text: str,
    prior: dict,
    missing: tuple[str, ...] | list[str],
    *,
    replace_recorded_times: bool = False,
) -> dict:
    value = unicodedata.normalize("NFKC", text).strip()
    if (
        collection_control(value)
        or collection_prompt_request(value)
        or len(value) > 2000
        or any(token in value for token in ("?", "？", "://", "@", "是什么", "怎么"))
        or re.match(r"^(?:what|how|why|should|can|could)\b", value, re.I)
    ):
        return {}
    if re.search(r"\b(?:ignore|activate|confirm|system|delete|rules?)\b|忽略|激活|确认|删除|停药", value, re.I):
        return {}
    result = {}
    if re.fullmatch(r"(?:手动(?:录入|输入|添加)?|改为手动|manual|enter manually|use manual)[。.!]?", value, re.I):
        return {"method": "manual"}
    if re.fullmatch(r"(?:拍照(?:识别|添加)?|上传照片|photo|use a photo)[。.!]?", value, re.I):
        return {"method": "photo"}
    name = re.search(r"(?:药名|药物名称|name|medication name)\s*:\s*([^;,，\n]+)", value, re.I)
    if name:
        result["medication_name"] = name.group(1).strip()
    strength = re.search(
        r"(?:规格|strength)\s*:?\s*(\d+(?:\.\d+)?\s*(?:mg|mcg|g|毫克|克)(?:\s*/\s*\d*\s*ml)?)", value, re.I
    )
    if strength:
        result["dose_basis"] = {
            **deepcopy(prior.get("dose_basis") or {}),
            "strength_text": strength.group(1).strip(),
            "patient_checked": False,
        }
    dose = re.search(r"(?:每次|dose\s*:|take)\s*(?:改为\s*)?" + _DOSE, value, re.I)
    if dose is None and missing and missing[0] in {"dose_amount", "dose_unit"}:
        dose = re.fullmatch(_DOSE, value, re.I)
    if dose:
        result.update(dose_amount=float(dose.group(1)), dose_unit=_UNITS[dose.group(2).casefold()])
    elif missing and missing[0] == "dose_amount" and re.fullmatch(r"\d+(?:\.\d+)?", value):
        result["dose_amount"] = float(value)
    elif missing and missing[0] == "dose_unit" and value.casefold() in _UNITS:
        result["dose_unit"] = _UNITS[value.casefold()]
    for field, labels in (
        ("course_start_date", r"开始日期|首次日期|start date|first dose date"),
        ("course_end_date", r"结束日期|end date"),
    ):
        match = re.search(r"(?:" + labels + r")\s*:?\s*(\d{4}-\d{2}-\d{2})", value, re.I)
        if match:
            result[field] = match.group(1)
        elif missing and missing[0] == field and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            result[field] = value
    times = re.findall(r"(?<!\d)([0-2]?\d:[0-5]\d)(?!\d)", value)
    if re.search(r"(?:按需|需要时|\bprn\b|\bas needed\b)", value, re.I) and not re.search(
        r"不是按需|not (?:prn|as needed)", value, re.I
    ):
        result.update(is_prn=True, frequency_rule=None, times_per_day=None)
    else:
        interval = re.search(r"每\s*(\d+)\s*小时|every\s+(\d+)\s*hours?", value, re.I)
        daily = re.search(
            r"(?:每天|每日|一天)\s*([一二两三四五六七八九十]|\d+)\s*次|\b(once|twice|\d+)\s+(?:a day|per day|daily)\b",
            value,
            re.I,
        )
        prior_rule = deepcopy(prior.get("frequency_rule") or {})
        if interval:
            result.update(
                is_prn=False,
                times_per_day=None,
                frequency_rule={
                    "kind": "interval",
                    "every_hours": int(interval.group(1) or interval.group(2)),
                    "local_times": times,
                },
            )
        elif daily or re.search(r"\bdaily\b|每天|每日", value, re.I):
            rule = prior_rule if prior_rule.get("kind") == "daily" else {"kind": "daily", "local_times": []}
            if times:
                rule["local_times"] = times
            result.update(is_prn=False, frequency_rule=rule)
            if daily:
                count = next(group for group in daily.groups() if group)
                result["times_per_day"] = _COUNT.get(count.casefold(), int(count) if count.isdigit() else None)
        elif times and ("frequency_local_times" in missing or replace_recorded_times and prior_rule):
            rule = prior_rule or {"kind": "daily", "local_times": []}
            prior_times = rule.get("local_times") or []
            rule["local_times"] = times if replace_recorded_times else list(dict.fromkeys([*prior_times, *times]))
            if replace_recorded_times:
                rule.pop("interval_anchor", None)
            result["frequency_rule"] = rule
    guidance = re.search(r"(?:条件|按需指示|instructions|guidance)\s*:\s*([^;\n]+)", value, re.I)
    if guidance:
        result["food_instruction"] = guidance.group(1).strip()
    if (
        not result
        and missing
        and missing[0] == "medication_name"
        and len(value) <= 160
        and re.fullmatch(r"[\w ()/.-]+", value)
        and not re.search(r"每次|规格|dose|strength|daily", value, re.I)
    ):
        result["medication_name"] = value
    return result
