"""Replay the actual final-provider failure through public Agent HTTP/services."""

from uuid import uuid4

import pytest
from app.agent.conversation import ConversationService
from app.agent.patient_read_reply import medication_knowledge_batch_reply
from app.application.ai_quota import QuotaAgent
from app.contracts.model import FunctionCall, ModelReply
from app.infrastructure.memory_quota import MemoryQuota
from app.infrastructure.memory_repos import InMemoryAgentSessionRepository

from .correctness02_support import build_harness


@pytest.mark.parametrize("language", ["en", "zh"])
@pytest.mark.parametrize("separate_rounds", [False, True])
def test_real_provider_call_shape_keeps_all_sourced_general_uses(language, separate_rounds):
    h = build_harness()
    try:

        def call(index, question="general_use"):
            return FunctionCall(
                id=f"DEMO-knowledge-{index}",
                name="get_medication_understanding",
                arguments={"medication_id": str(h.plans[index].medication.id), "question": question},
            )

        rounds = [ModelReply(calls=[FunctionCall(id="DEMO-list", name="list_active_medications", arguments={})])]
        rounds += (
            [ModelReply(calls=[call(1)]), ModelReply(calls=[call(3)])]
            if separate_rounds
            else [ModelReply(calls=[call(1), call(3)])]
        )
        rounds.append(ModelReply(text="Invented or incomplete model wording must not replace tool facts."))
        iterator = iter(rounds)

        class Model:
            def create(self, **kwargs):
                return next(iterator)

        conversation = ConversationService(
            model=Model(),
            tools=h.tools,
            fallback=h.root.orchestrator,
            sessions=InMemoryAgentSessionRepository(h.root.store),
            ids=h.root.ids,
        )
        h.root.ai_agent = QuotaAgent(
            repository=MemoryQuota(clock=h.root.clock, nonce_factory=lambda: str(uuid4()), limit=30),
            conversation=conversation,
            fallback=h.root.orchestrator,
            daily_limit=30,
        )
        reply = h.ask(
            "Please explain the usual purpose of every entry we just found, using drug-label evidence.",
            language=language,
        )
        message = reply["message"]
        assert reply["mode"] == "gemini"
        assert all(message.count(name) == 1 for name in ("Amlodipine 5 mg", "Amlodipine 10 mg", "Metformin 500 mg"))
        assert message.count("高血压" if language == "zh" else "hypertension") == 1
        assert "血糖" in message if language == "zh" else "blood sugar" in message
        assert "Invented" not in message and "https://" not in message
        assert message.count("以上为美国标签" if language == "zh" else "General uses from US labels") == 1
        assert len(h.rows[-1]["tools"]) == 3 and len(h.root.store.events) == 3
        assert all(call["data"]["general_knowledge"]["sources"] for call in h.rows[-1]["tools"][1:])
        sources = h.ask("这些用途的来源是什么？", language="zh")
        assert "openFDA / SPL" in sources["message"] and "高血压" not in sources["message"]
        assert sources["mode"] == "records_only"  # Exhausted fake cannot answer another model request.
        assert not sources["medication_choice"]
    finally:
        h.close()


@pytest.mark.parametrize("difference", ["missing", "release", "form", "route", "brand", "ingredient"])
def test_shared_general_uses_require_trusted_compatible_scope_and_disclose_missing_entries(difference):
    h = build_harness()
    try:
        h.ask("What are those medicines generally used for?")
        calls = h.rows[-1]["tools"]
        listed = calls[0]["data"]["payload"]["medications"]
        reads = [call["data"] for call in calls[1:] if call["data"]["medication_id"] != str(h.plans[2].medication.id)]
        affected = next(row for row in listed if row["medication_id"] == str(h.plans[2].medication.id))
        if difference == "missing":
            affected["comparison_basis"] = None
        elif difference == "ingredient":
            affected["ingredients"] = ["DEMO_OTHER"]
        else:
            affected["comparison_basis"][difference] = "DEMO_OTHER"
        actual = medication_knowledge_batch_reply(reads, listed, "en")
        assert "Applicable use evidence was not obtained for these entries: Amlodipine 10 mg" in actual
        assert "Amlodipine 5 mg: Used" in actual and "Metformin 500 mg: Used" in actual
    finally:
        h.close()
