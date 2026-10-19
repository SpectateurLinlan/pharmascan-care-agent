"""Presentation of already validated knowledge; no new medical facts or retrieval."""

import re

from ..contracts.medication_knowledge import KnowledgeResult


def general_use_text(knowledge: KnowledgeResult, language: str) -> str:
    if language == "zh":
        if knowledge.use_statement_zh:
            # Only the controlled translation's introductory attribution changes.
            return re.sub(r"^(?:该|所引)美国标签列出的(?:一个)?用途是", "一般用途：", knowledge.use_statement_zh)
        return "暂无经核对的中文译文。美国标签原文摘录：" + (knowledge.use_statement or "")
    # Preserve every indication qualifier (population, adjuncts, release, etc.).
    # Strip only the source product's grammatical subject, not its clinical text.
    text = knowledge.use_statement or ""
    match = re.fullmatch(r".+? (?:is|are) indicated (for|as) (.+)", text, re.I | re.S)
    if not match:
        return text
    clause = match[2]
    if match[1].lower() == "for" and clause.startswith("the treatment of "):
        return "Used to treat " + clause.removeprefix("the treatment of ")
    adjunct = "an adjunct to diet and exercise to improve glycemic control "
    if match[1].lower() == "as" and clause.startswith(adjunct):
        return "Used alongside diet and exercise to help control blood sugar " + clause.removeprefix(adjunct)
    return f"Used {match[1]} {clause}"


def knowledge_scope(language: str) -> str:
    return (
        "以上为美国标签支持的一般用途摘录，不代表您的具体产品、个人开药原因或用量；适用范围及原文见回答依据。"
        if language == "zh"
        else "General uses from US labels, not your personal prescribing reason or dose. "
        "Source brands may differ from your product; see Sources."
    )
