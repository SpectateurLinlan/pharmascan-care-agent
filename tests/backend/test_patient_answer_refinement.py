"""Patient-visible outcome acceptance using real services and DEMO_ONLY cached labels."""

from uuid import uuid4

import pytest
from app.agent.long_term_tools import execute_care_tool
from app.agent.medication_resolution import comparative_option
from app.agent.read_dialogue import resolve_options
from app.application.medication_presentation import general_use_text
from app.contracts.medication_dialogue import MedicationOption
from app.contracts.medication_knowledge import KnowledgeResult

from .correctness02_support import OWNER, build_harness


@pytest.fixture
def patient():
    h = build_harness()
    yield h
    h.close()


@pytest.mark.parametrize(
    "language,question", [("zh", "我现在有哪些药？"), ("en", "What medications am I currently taking?")]
)
def test_list_is_complete_without_repeated_boilerplate(patient, language, question):
    reply = patient.ask(question, language=language)["message"]
    for name in ("Amlodipine 5 mg", "Amlodipine 10 mg", "Metformin 500 mg"):
        assert reply.count(name) == 1
    assert "not proof" not in reply and "不能证明" not in reply
    assert ("片剂" if language == "zh" else "tablet") in reply


@pytest.mark.parametrize(
    "language,question", [("zh", "这些药分别有什么作用？"), ("en", "What are those medicines generally used for?")]
)
def test_general_uses_share_explanation_but_keep_all_identities_and_sources(patient, language, question):
    reply = patient.ask(question, language=language)
    reads = [call for call in patient.rows[-1]["tools"] if call["tool"] == "get_medication_understanding"]
    assert len({call["parameters"]["medication_id"] for call in reads}) == 3
    message = reply["message"]
    assert all(name in message for name in ("5 mg", "10 mg", "Metformin 500 mg"))
    assert message.count("高血压" if language == "zh" else "hypertension") == 1
    assert "血糖" in message if language == "zh" else "blood sugar" in message
    assert "https://" not in message and "NORLIQVA is" not in message
    assert "美国" in message if language == "zh" else "US labels" in message
    assert reads[0]["data"]["general_knowledge"]["sources"][0]["label_name"].startswith("NORLIQVA")
    assert all(call["data"]["general_knowledge"]["sources"][0]["sections"] for call in reads)
    assert all("dailymed.nlm.nih.gov" in call["data"]["general_knowledge"]["sources"][0]["url"] for call in reads)


def test_chinese_plan_has_actual_dose_and_time_without_raw_or_empty_fields(patient):
    reply = patient.ask("Amlodipine 5 mg 每次服用多少？", language="zh")["message"]
    assert "每次服用 0.5 片" in reply and "20:00" in reply and "口服" in reply
    assert not any(value in reply for value in ("DEMO_ONLY", "原文", "tablet", "oral", "Food", "未记录", "UUID"))
    assert not patient.requests  # Personal dose never comes from general drug labels.


@pytest.mark.parametrize(
    "question", ["我服用的 Amlodipine 每次应该吃多少？", "What does my Amlodipine entry say about my dose?"]
)
def test_ingredient_question_limits_choices_and_text_continues_original_task(patient, question):
    reply = patient.ask(question, language="zh")
    choices = reply["medication_choice"]["options"]
    assert len(choices) == 2 and all("Amlodipine" in choice["label"] for choice in choices)
    answer = patient.ask("10 mg 那个", language="zh")
    assert not answer["medication_choice"] and "每次服用 1 片" in answer["message"]
    calls = patient.rows[-1]["tools"]
    assert calls[-1]["parameters"] == {
        "medication_id": choices[1]["medication_id"],
        "question": "personal_instructions",
    }
    assert not patient.requests and len(patient.root.store.events) == 3


def test_trusted_stronger_product_reads_its_plan_not_strength_as_dose(patient):
    reply = patient.ask("What does the stronger Amlodipine entry say about how much I take each time?")
    assert not reply["medication_choice"]
    assert "Amlodipine 10 mg, 1 tablet per dose" in reply["message"]
    assert "08:00" in reply["message"] and "Metformin" not in reply["message"]
    assert patient.rows[-1]["tools"][-1]["parameters"]["medication_id"] == str(patient.plans[2].medication.id)


@pytest.mark.parametrize(
    "difference", ["release", "form", "brand", "route", "unit", "unknown", "duplicate", "ingredient"]
)
def test_incomparable_strengths_remain_choices(difference):
    options = [
        MedicationOption(
            medication_id=uuid4(),
            regimen_id=uuid4(),
            display_name="DEMO medicine",
            label=f"DEMO {strength} mg",
            ingredient_names=["DEMO ingredient"],
        )
        for strength in (3, 9)
    ]
    basis = {"product_name": "DEMO ingredient", "brand": None, "form": "tablet", "route": "oral", "release": "standard"}
    rows = [
        {"medication_id": str(option.medication_id), "strength_text": f"{strength} mg", "comparison_basis": dict(basis)}
        for option, strength in zip(options, (3, 9), strict=True)
    ]
    if difference == "unknown":
        rows[1]["comparison_basis"] = None
    elif difference == "unit":
        rows[1]["strength_text"] = "9 mcg"
    elif difference == "duplicate":
        rows[1]["strength_text"] = "3 mg"
    elif difference == "ingredient":
        options[1] = options[1].model_copy(update={"ingredient_names": ["DEMO other ingredient"]})
    else:
        rows[1]["comparison_basis"][difference] = "DEMO different"
    assert comparative_option("the stronger DEMO medicine", options, rows) == options


def test_ambiguous_click_after_language_switch_retains_entity_and_intent(patient):
    reply = patient.ask("What is this medicine for?")
    choice = reply["medication_choice"]
    assert len(choice["options"]) == 3
    selected = choice["options"][2]
    answer = patient.ask(
        selected["label"],
        language="zh",
        selection={"choice_id": choice["id"], "medication_id": selected["medication_id"]},
    )
    assert not answer["medication_choice"] and "血糖" in answer["message"]
    assert patient.rows[-1]["tools"][-1]["parameters"] == {
        "medication_id": selected["medication_id"],
        "question": "general_use",
    }


def test_named_general_use_needs_no_strength_choice_and_source_followup_is_direct(patient):
    reply = patient.ask("Amlodipine 有什么作用？", language="zh")
    assert not reply["medication_choice"] and "高血压" in reply["message"]
    source = patient.ask("这个回答来源是什么？", language="zh")["message"]
    assert "openFDA / SPL" in source and "NORLIQVA" in source
    assert "高血压" not in source and "https://" not in source


@pytest.mark.parametrize(
    "question,expected",
    [
        ("Did I take Amlodipine 5 mg yesterday?", "reported not taking"),
        ("Show medication records for this week.", "2026-10-15"),
        ("Show my health observations", "DEMO felt well"),
    ],
)
def test_new_independent_question_interrupts_pending_intent(patient, question, expected):
    patient.ask("What is this medicine for?")
    reply = patient.ask(question)
    assert expected in reply["message"] and not reply["medication_choice"]
    assert "hypertension" not in reply["message"]
    assert len(patient.root.store.events) == 3


def test_original_is_preserved_and_only_returned_when_explicitly_requested(patient):
    patient.ask("Show original instructions for Amlodipine")
    choice = patient.rows[-1]["reply"]["medication_choice"]
    assert len(choice["options"]) == 2
    actual = patient.ask("10 mg")["message"]
    assert actual == "Reviewed original instructions:\nDEMO_ONLY reviewed instructions"


@pytest.mark.parametrize("language", ["zh", "en"])
def test_review_prioritises_questions_and_preserves_all_observations(patient, language):
    output = execute_care_tool(
        patient.root.long_term,
        name="prepare_medication_review",
        arguments={"days": 7},
        patient_id=OWNER,
        session_id=uuid4(),
        turn_id="demo-review",
        text="Prepare my visit",
        language=language,
        timezone="Asia/Singapore",
    )
    actual = output.data["patient_safe_summary"]
    questions = "复诊可讨论的问题" if language == "zh" else "Questions to discuss"
    evidence = "记录依据" if language == "zh" else "Supporting records"
    assert actual.index(questions) < actual.index(evidence)
    assert all(
        text in actual for text in ("DEMO felt tired", "DEMO headache resolved", "DEMO felt well", "128/82 mmHg")
    )
    assert "尚未记录不等于未服" in actual if language == "zh" else "Unrecorded does not mean missed" in actual


def test_strength_selection_matches_whole_quantity_not_a_substring():
    options = [
        MedicationOption(
            medication_id=uuid4(), regimen_id=uuid4(), display_name="DEMO medicine", label=f"DEMO {strength} mg"
        )
        for strength in (10, 110)
    ]
    assert resolve_options("10 mg", options, allow_order=False) == options[:1]


def test_readable_knowledge_retains_population_and_other_qualifiers_without_drug_dictionary():
    source = "DEMO product is indicated as an adjunct to diet and exercise to improve glycemic control in adults only."
    result = KnowledgeResult(status="matched", reason="DEMO_ONLY fixture", use_statement=source)
    actual = general_use_text(result, "en")
    assert actual == "Used alongside diet and exercise to help control blood sugar in adults only."
    assert result.use_statement == source  # Original evidence remains byte-for-byte unchanged.
    unsupported = result.model_copy(update={"use_statement": "DEMO product has an unfamiliar qualified indication."})
    assert general_use_text(unsupported, "en") == unsupported.use_statement
