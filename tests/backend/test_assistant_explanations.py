"""Patient evidence describes the lookup outcome, not the transport success."""

import pytest
from app.contracts.medication_knowledge import KnowledgeResult


@pytest.mark.parametrize("reason,status,attempted,outcome", [
    ("unsupported_search_name", "no_reliable_match", False, "not_attempted"),
    ("not_found", "no_reliable_match", True, "not_found"),
    ("timeout", "unavailable", True, "unavailable"),
    ("conflicting_label_uses", "no_reliable_match", True, "failed"),
    ("true_scope_conflict", "no_reliable_match", True, "failed"),
    ("scoped_partial_evidence", "matched", True, "partial"),
])
def test_knowledge_explanations_distinguish_actual_outcomes(reason, status, attempted, outcome):
    from app.application.assistant_explanations import explain_knowledge

    result = KnowledgeResult(status=status, reason=reason, coverage="partial" if status == "matched" else None)
    steps = explain_knowledge(result, attempted=attempted)
    assert len(steps) == 1 and steps[0].operation_key == "knowledge.lookup"
    assert steps[0].outcome == outcome and steps[0].reason_key == reason
    assert bool(steps[0].source_name) == attempted


@pytest.mark.parametrize("reason", ["unsupported_search_name", "timeout", "conflicting_label_uses", "not_found"])
def test_service_summary_names_the_specific_failure(wired, reason):
    from app.application.medication_understanding import MedicationUnderstandingService

    class Provider:
        def lookup(self, product):
            return KnowledgeResult(status="unavailable" if reason == "timeout" else "no_reliable_match", reason=reason)

    service = MedicationUnderstandingService(wired.enrollment, Provider(), wired.clock)
    result = service.explain(patient_id=wired.ids.new_id(), medication_name="ibuprofen", language="zh")
    expected = {"unsupported_search_name": "尚未查询", "timeout": "超时",
                "conflicting_label_uses": "冲突", "not_found": "未找到"}[reason]
    assert expected in result.patient_safe_summary
    assert "可能存在成分不匹配、来源冲突或服务不可用" not in result.patient_safe_summary
    assert result.explanations
