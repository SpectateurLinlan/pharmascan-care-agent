"""Recognise explicit education questions; never infer an indication or dose."""

import re


def medication_question(text: str) -> dict[str, str] | None:
    if "@" in text or "://" in text or "\n" in text:
        return None  # Do not turn contact details or URLs into public label queries.
    value = text.strip().rstrip("?？。.")
    value = re.sub(r"^(?:please\s+|can you\s+|could you\s+|tell me\s+)+", "", value, flags=re.I)
    value = re.sub(r"\bgenerally\s+", "", value, flags=re.I)
    lower = value.lower()
    if re.search(r"\b(?:double|increase|reduce|change|stop)\b.*\bdose\b|加量|减量|停药|改剂量", value, re.I):
        return None
    question = None
    if re.search(r"\bwhat (?:is|are) .+ (?:used for|for)$|\bwhat does .+ do$", lower) or any(
        token in value
        for token in ("有什么用", "什么作用", "用来做什么", "用于什么", "治什么", "干什么", "一般用途", "general use")
    ):
        question = "general_use"
    elif "why" in lower and "prescrib" in lower or "为什么" in value and "开" in value:
        question = "personal_reason"
    elif (
        "how should i take" in lower
        or "怎么服用" in value
        or "怎么吃" in value
        or re.search(r"\b(?:dose|amount per dose)\b|每次.*(?:用量|服用量)|每次服.*多少", value, re.I)
    ):
        question = "personal_instructions"
    if question is None:
        return None
    result = {"question": question}
    match = re.fullmatch(r"what (?:is|are) (.+?) (?:used for|for)", value, flags=re.I)
    if match is None:
        match = re.fullmatch(r"what does (.+?) do", value, flags=re.I)
    if match:
        name = match.group(1).strip()
        if not re.search(r"\b(?:this|it|my|these|first|second|third|taking|medicine|medication)\b", name, re.I):
            result["medication_name"] = name[:160]
    if question == "personal_instructions":
        match = re.fullmatch(r"how should i take (?:my )?(.+)", value, flags=re.I)
        if match and match.group(1).lower() not in {"it", "this", "medication", "medicine"}:
            result["medication_name"] = match.group(1)[:160]
    if question == "general_use" and "medication_name" not in result:
        match = re.fullmatch(r"(.+?)(?:有什么用|有什么作用|用于什么|治什么).*", value)
        if match and not re.search(r"这个|这药|它|我|这些|第|那", match.group(1)):
            result["medication_name"] = match.group(1)[:160]
    return result
