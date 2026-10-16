"""Recognise explicit education questions; never infer an indication or dose."""

import re


def medication_question(text: str) -> dict[str, str] | None:
    if "@" in text or "://" in text or "\n" in text:
        return None  # Do not turn contact details or URLs into public label queries.
    value = text.strip().rstrip("?？.")
    lower = value.lower()
    question = None
    if re.search(r"\bwhat (?:is|are) .+ (?:used for|for)$", lower) or any(
        token in value for token in ("有什么用", "什么作用", "用来做什么", "用于什么", "治什么", "干什么")
    ):
        question = "general_use"
    elif "why" in lower and "prescrib" in lower or "为什么" in value and "开" in value:
        question = "personal_reason"
    elif "how should i take" in lower or "怎么服用" in value or "怎么吃" in value:
        question = "personal_instructions"
    if question is None:
        return None
    result = {"question": question}
    match = re.fullmatch(r"what (?:is|are) (.+?) (?:used for|for)", value, flags=re.I)
    if match:
        name = match.group(1).strip()
        if name.lower() not in {"this", "it", "this medicine", "this medication", "my medicine", "my medication"}:
            result["medication_name"] = name[:160]
    if question == "personal_instructions":
        match = re.fullmatch(r"how should i take (?:my )?(.+)", value, flags=re.I)
        if match and match.group(1).lower() not in {"it", "this", "medication", "medicine"}:
            result["medication_name"] = match.group(1)[:160]
    if question == "general_use" and "medication_name" not in result:
        match = re.fullmatch(r"(.+?)(?:有什么用|有什么作用|用于什么|治什么).*", value)
        if match and match.group(1) not in {"这个药", "这药", "它", "这是什么药"}:
            result["medication_name"] = match.group(1)[:160]
    return result
