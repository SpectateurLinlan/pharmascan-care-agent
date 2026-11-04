"""Truthful evidence derived from actual results, without raw tool vocabulary."""

from ..contracts.assistant_explanations import ExplanationStep
from ..contracts.medication_knowledge import KnowledgeResult

NOT_ATTEMPTED = {"unsupported_search_name", "missing_form_route_or_release", "name_not_resolved"}


def explain_knowledge(result: KnowledgeResult, *, attempted: bool) -> tuple[ExplanationStep, ...]:
    attempted = attempted and result.reason not in NOT_ATTEMPTED
    outcome = (
        "not_attempted" if not attempted else "unavailable" if result.status == "unavailable"
        else "partial" if result.status == "matched" and result.coverage == "partial"
        else "success" if result.status == "matched" else "not_found" if result.reason == "not_found" else "failed"
    )
    return (ExplanationStep(
        operation_key="knowledge.lookup", outcome=outcome,
        source_name="openFDA Drug Label / SPL" if attempted else None,
        source_refs=tuple(source.url for source in result.sources[:10]), reason_key=result.reason[:100],
        count=len(result.sources) if result.status == "matched" else None,
    ),)


def knowledge_failure_text(result: KnowledgeResult, language: str) -> str:
    reason = result.reason
    if reason in NOT_ATTEMPTED:
        return ("尚未查询公共药品资料库：药名或产品信息暂不支持查询，请核对药名或补充原标签。" if language == "zh"
                else "The public label search has not run: this name or product information is not supported. "
                "Check the name or provide the original label.")
    if reason == "not_found":
        return ("已查询 openFDA / SPL，本次查询未找到匹配标签。这不代表该药不存在；请核对成分名或原标签。"
                if language == "zh" else "The openFDA / SPL search found no matching label. "
                "This does not establish that the medicine does not exist; check its ingredient name or label.")
    if reason in {"timeout", "request_budget_exceeded"}:
        return ("查询 openFDA / SPL 超时，请稍后重试；暂时无法确认一般用途。" if language == "zh"
                else "The openFDA / SPL lookup timed out. Please retry; its general use is not yet confirmed.")
    if result.status == "unavailable":
        return ("openFDA / SPL 资料服务暂时不可用，请稍后重试；这不代表资料库没有该药。" if language == "zh"
                else "The openFDA / SPL information service is temporarily unavailable. "
                "Please retry; this does not mean the medicine is absent from the database.")
    if reason in {"true_scope_conflict", "conflicting_label_uses", "duplicate_version_conflict"}:
        return ("查询到的标签内容存在冲突，当前无法可靠整理一般用途；请核对所持产品原标签或咨询药剂师。"
                if language == "zh" else "The retrieved label evidence conflicts, so a reliable use summary "
                "is not available. Check your product's original label with a pharmacist.")
    return ("已查询 openFDA / SPL，但本次成分及适用范围证据不足，无法从来源可靠确认一般用途；请核对药名和原标签。"
            if language == "zh"
            else "The openFDA / SPL lookup did not establish the ingredient and use scope. "
            "Check the name and original label.")
