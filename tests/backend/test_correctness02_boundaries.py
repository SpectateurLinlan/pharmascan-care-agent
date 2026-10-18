"""Fact/coverage/entity assertions, not reply-count or mocked happy-path acceptance."""

import json
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from app.contracts.agent_context import AgentContext, RecentTurn
from app.contracts.context_bounds import bounded_context
from app.contracts.medication_dialogue import MedicationChoice, MedicationDialogue, MedicationOption
from app.contracts.medication_knowledge import KnowledgeProduct
from app.contracts.observations import ObservationInput
from app.infrastructure.openfda_knowledge import OpenFDAKnowledge

from .correctness02_support import OWNER, build_harness


def test_large_non_ascii_choice_metadata_expires_without_dropping_current_question():
    h = build_harness()
    try:
        options = [
            MedicationOption(
                medication_id=uuid4(),
                regimen_id=uuid4(),
                display_name="合成药" * 60,
                label="合成药" * 100,
                ingredient_names=["成分" * 100] * 8,
            )
            for _ in range(10)
        ]
        context = AgentContext(
            medication_dialogue=MedicationDialogue(
                choice=MedicationChoice(
                    id=uuid4(),
                    question="general_use",
                    expires_at=h.root.clock.now() + timedelta(minutes=10),
                    options=options,
                )
            ),
            recent_turns=[RecentTurn(user="当前问题😀", assistant="请重新选择")],
        )
        bounded = bounded_context(context)
        assert len(json.dumps(bounded.model_dump(mode="json"), ensure_ascii=False).encode()) <= 16000
        assert bounded.recent_turns[-1].user == "当前问题😀"
        assert bounded.medication_dialogue is None
    finally:
        h.close()


def test_education_read_does_not_swallow_subsequent_historical_write_or_named_status():
    h = build_harness()
    try:
        h.ask("Show my medication history")
        reply = h.ask("I took Amlodipine 5 mg yesterday.")
        assert "Historical dose backfill is not supported" in reply["message"]
        assert not reply.get("pending_report")
        assert len(h.root.store.events) == 3
        h.ask("Show my medication history")
        reply = h.ask("Did I take Amlodipine 5 mg yesterday?")
        assert "reported not taking Amlodipine 5 mg" in reply["message"]
        assert "Metformin" not in reply["message"]
        assert h.rows[-1]["tools"][-1]["tool"] == "get_dose_status"
    finally:
        h.close()


@pytest.mark.parametrize(
    "question",
    [
        "我现在有哪些药？",
        "把我正在吃的药列出来。",
        "我正在吃什么药？",
        "What medicines am I taking?",
        "Can you list my current medication?",
        "Which medicines do I have?",
    ],
)
def test_current_medication_paraphrases_name_all_owned_current_products(question):
    h = build_harness()
    try:
        data = h.ask(question)
        assert all(name in data["message"] for name in ["Amlodipine 5 mg", "Amlodipine 10 mg", "Metformin 500 mg"])
        assert h.rows[-1]["tools"][0]["tool"] == "list_active_medications"
    finally:
        h.close()


def test_actual_public_label_usp_and_brand_generic_variants_do_not_lose_ingredient_use(clock):
    raw = json.loads(Path("tests/backend/fixtures/correctness02_metformin_variants.json").read_text(encoding="utf8"))
    provider = OpenFDAKnowledge(
        httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=raw))),
        clock,
        monotonic=lambda: 0,
    )
    result = provider.lookup(
        KnowledgeProduct(scope="ingredient", name="METFORMIN HYDROCHLORIDE", ingredients=["METFORMIN HYDROCHLORIDE"])
    )
    assert result.status == "matched" and result.match_scope == "US_label_ingredient"
    assert "glycemic control" in result.use_statement and "血糖" in result.use_statement_zh
    assert all(
        "sitagliptin" not in section.text.lower() and "glipizide" not in section.text.lower()
        for source in result.sources
        for section in source.sections
    )


@pytest.mark.parametrize("count", [0, 1, 5, 20])
def test_health_record_coverage_counts_values_and_explicit_summary_bounds(count):
    h = build_harness()
    try:
        for note in h.root.observations.list(
            OWNER, h.root.clock.now() - timedelta(days=30), h.root.clock.now() + timedelta(seconds=1)
        ):
            h.root.observations.delete(OWNER, note.id)
        for index in range(count):
            h.root.observations.save(
                OWNER,
                ObservationInput(
                    id=uuid4(),
                    description=f"DEMO observation {index:02}",
                    occurred_at=h.root.clock.now() - timedelta(minutes=index + 1),
                    confirmed=True,
                ),
            )
        response = h.ask("Show my health observations")
        tool = h.rows[-1]["tools"][-1]
        assert tool["tool"] == "get_health_observations" and tool["data"]["observation_count"] == count
        for index in range(min(count, 10)):
            assert f"DEMO observation {index:02}" in response["message"]
        if count > 10:
            assert "latest 10" in response["message"] and str(count) in response["message"]
        assert all("patient_id" not in row for row in tool["data"]["observations"])
    finally:
        h.close()


def test_rolling_observation_window_includes_previous_calendar_week():
    h = build_harness()
    try:
        h.root.clock.advance(days=1)  # Monday; all three notes are from Sunday.
        data = h.ask("Show my health observations")
        assert all(note in data["message"] for note in ["DEMO felt tired", "DEMO headache resolved", "DEMO felt well"])
        assert h.rows[-1]["tools"][-1]["data"]["observation_count"] == 3
    finally:
        h.close()


@pytest.mark.parametrize("count", [0, 1, 5, 6, 20, 25])
def test_history_counts_and_real_read_bounds_are_transparent(count):
    h = build_harness()
    try:
        base = next(iter(h.root.store.occurrences.values()))
        h.root.store.occurrences.clear()
        h.root.store.events.clear()
        for index in range(count):
            occurrence = base.model_copy(
                update={
                    "id": uuid4(),
                    "regimen_id": h.plans[1].regimen.id,
                    "due_at": h.root.clock.now() - timedelta(minutes=index + 1),
                    "generation_key": f"DEMO-bounded-{index}",
                }
            )
            h.root.store.occurrences[(OWNER, occurrence.id)] = occurrence
        future = base.model_copy(
            update={
                "id": uuid4(),
                "regimen_id": h.plans[1].regimen.id,
                "due_at": h.root.clock.now() + timedelta(days=1),
                "generation_key": "DEMO-future",
            }
        )
        h.root.store.occurrences[(OWNER, future.id)] = future
        data = h.ask("Show my medication history")
        payload = h.rows[-1]["tools"][-1]["data"]["payload"]
        assert payload["item_count"] == count and len(payload["entries"]) == min(count, 20)
        assert all(not row["reported"] for row in payload["entries"])
        assert "Unrecorded does not mean missed" in data["message"]
        if count > 20:
            assert f"latest 20 of {count}" in data["message"]
    finally:
        h.close()


def test_pending_choice_order_is_the_displayed_order_not_later_repository_order():
    h = build_harness()
    try:
        first = h.ask("What is this medicine for?")
        options = first["medication_choice"]["options"]
        h.root.store.medications = dict(reversed(list(h.root.store.medications.items())))
        result = h.ask("second")
        assert h.rows[-1]["tools"][-1]["parameters"]["medication_id"] == options[1]["medication_id"]
        assert "Amlodipine 10 mg" in result["message"]
    finally:
        h.close()


def test_restore_after_topic_change_never_resurrects_an_older_medication_reference():
    h = build_harness()
    try:
        h.ask("What is Metformin 500 mg used for?")
        h.ask("Show my health observations")
        first = h.ask("What is this medicine for?")
        assert first["medication_choice"]
        h.restore()
        after = h.ask("What is this medicine for?")
        assert after["medication_choice"]
        assert not any(call["tool"] == "get_medication_understanding" for call in h.rows[-1]["tools"])
    finally:
        h.close()


def test_personal_instructions_require_exact_product_choice_then_resume_without_general_knowledge():
    h = build_harness()
    try:
        response = h.ask("How should I take Amlodipine?")
        choice = response["medication_choice"]
        assert choice and choice["question"] == "personal_instructions"
        assert len(choice["options"]) == 2 and all("Amlodipine" in row["label"] for row in choice["options"])
        option = next(row for row in choice["options"] if "10 mg" in row["label"])
        answer = h.ask(option["label"], selection={"choice_id": choice["id"], "medication_id": option["medication_id"]})
        read = h.rows[-1]["tools"][-1]
        assert read["parameters"]["medication_id"] == option["medication_id"]
        assert read["data"]["personal_instructions"]["dose_amount"] == 1
        assert read["data"]["general_knowledge"] is None
        assert "1 tablet" in answer["message"]
        assert not answer["requires_confirmation"] and len(h.root.store.events) == 3
    finally:
        h.close()


def test_identical_display_names_keep_reviewed_strength_and_plan_source_in_history():
    h = build_harness()
    try:
        for plan in h.plans[:3]:
            medication = h.root.enrollment.get_medication(OWNER, plan.medication.id)
            h.root.store.medications[(OWNER, medication.id)] = medication.model_copy(
                update={"display_name": "Amlodipine"}
            )
        reply = h.ask("Show my medication history")
        assert "Amlodipine — 5 mg" in reply["message"] and "Amlodipine — 10 mg" in reply["message"]
        entries = h.rows[-1]["tools"][-1]["data"]["payload"]["entries"]
        assert {entry["strength_text"] for entry in entries if entry["display_name"] == "Amlodipine"} == {
            "5 mg",
            "10 mg",
        }
        assert all(entry["regimen_version"] and entry["regimen_effective_from"] for entry in entries)
    finally:
        h.close()


def test_a_b_conversations_reject_each_others_choice_and_foreign_owner_cannot_resume():
    h = build_harness()
    try:
        first = h.ask("What is this medicine for?")
        a = (h.session, h.conversation)
        choice = first["medication_choice"]
        option = choice["options"][0]
        selection = {"choice_id": choice["id"], "medication_id": option["medication_id"]}
        h.session = None
        h.conversation = None
        h.ask("What is this medicine for?")
        b = h.conversation
        rejected = h.ask(option["label"], selection=selection)
        assert rejected["medication_choice"] and not any(
            call["tool"] == "get_medication_understanding" for call in h.rows[-1]["tools"]
        )
        assert b != a[1]
        h.session, h.conversation = a
        accepted = h.ask(option["label"], selection=selection)
        assert accepted["conversation_id"] == a[1] and "hypertension" in accepted["message"]
        denied = h.client.post(
            f"/api/agent/conversations/{a[1]}/resume", headers={"Authorization": "Bearer DEMO.foreign"}
        )
        assert denied.status_code == 404 and "Amlodipine" not in denied.text
        assert len(h.root.store.events) == 3
    finally:
        h.close()
