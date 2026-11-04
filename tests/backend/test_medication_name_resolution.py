"""General names and patient product choices are different trust scopes."""

from uuid import UUID

import pytest
from app.agent.knowledge_intent import medication_question
from app.application.medication_names import MedicationNameResolver
from app.contracts.medication_names import NameCandidate, NameQuery


@pytest.mark.parametrize("text,name", [
    ("ibuprofen是什么？", "ibuprofen"), ("What is IBUPROFEN?", "IBUPROFEN"),
    ("布洛芬是什么药？", "布洛芬"), ("什么是布洛芬？", "布洛芬"),
    ("Ｉｂｕｐｒｏｆｅｎ 是什么", "Ibuprofen"),
])
def test_common_definition_questions_recognize_the_named_medicine(text, name):
    assert medication_question(text) == {"question": "general_use", "medication_name": name}


@pytest.mark.parametrize("text", [
    "Should I stop ibuprofen?", "What is ibuprofen and should I stop it?", "我想添加一种药物",
    "我的密码是什么", "https://private.example.test 是什么", "DEMO@example.test是什么",
    "这些用途的来源是什么？", "What is the source?", "What is my account password?",
])
def test_education_does_not_capture_actions_secrets_or_contact_details(text):
    assert medication_question(text) is None


@pytest.mark.parametrize("name", ["布洛芬", "Ibuprofen", "IBUPROFEN", "ｉｂｕｐｒｏｆｅｎ"])
def test_sourced_exact_aliases_resolve_without_inventing_patient_identity(name):
    result = MedicationNameResolver().resolve(NameQuery(text=name, purpose="general_use"), ())
    assert result.status == "resolved" and result.canonical_name == "IBUPROFEN"
    assert result.candidates[0].source_refs
    assert result.candidates[0].medication_id is None


def test_typo_never_resolves_without_user_confirmation_even_with_one_candidate():
    result = MedicationNameResolver().resolve(NameQuery(text="ibuprofne", purpose="general_use"), ())
    assert result.status == "needs_confirmation"
    assert result.canonical_name is None
    assert result.candidates[0].canonical_name == "IBUPROFEN"


def test_similar_patient_products_keep_strength_and_identity_distinct():
    owned = tuple(NameCandidate(
        id=f"owned-{index}", canonical_name="IBUPROFEN", display_name=f"DEMO Ibuprofen {strength} mg",
        source_refs=("owned-reviewed-record",), medication_id=UUID(int=index), strength=f"{strength} mg",
    ) for index, strength in [(1, 200), (2, 400)])
    result = MedicationNameResolver().resolve(NameQuery(text="ibuprofen", purpose="patient_product"), owned)
    assert result.status == "ambiguous"
    assert {row.strength for row in result.candidates} == {"200 mg", "400 mg"}


def test_unreviewed_alias_does_not_become_a_verified_mapping():
    resolver = MedicationNameResolver(entries=({
        "alias": "DEMO-unsourced", "canonical_name": "IBUPROFEN", "language": "en",
        "source_url": "", "source_checked_at": "2026-10-25", "scope": "ingredient", "reviewed": False,
    },))
    assert resolver.resolve(NameQuery(text="DEMO-unsourced", purpose="patient_product"), ()).status == "not_found"


@pytest.mark.parametrize("name,expected_calls", [("布洛芬", 1), ("ibuprofne", 0)])
def test_general_knowledge_resolves_names_without_reading_patient_catalogue(wired, name, expected_calls):
    from app.application.medication_understanding import MedicationUnderstandingService
    from app.contracts.medication_knowledge import KnowledgeResult

    class Enrollment:
        def list_medications(self, *args):
            raise AssertionError("General ingredient lookup must not read patient medicines")

    class Provider:
        calls = []

        def lookup(self, product):
            self.calls.append(product)
            return KnowledgeResult(status="no_reliable_match", reason="not_found")

    provider = Provider()
    service = MedicationUnderstandingService(
        Enrollment(), provider, wired.clock, name_resolver=MedicationNameResolver(),
    )
    result = service.explain(patient_id=UUID(int=1), medication_name=name, question="general_use")
    assert len(provider.calls) == expected_calls
    if expected_calls:
        assert provider.calls[0].name == "IBUPROFEN"
    else:
        assert result.clarification_required
        assert result.name_resolution.status == "needs_confirmation"


def test_chinese_spelling_error_is_a_suggestion_not_automatic_identity():
    result = MedicationNameResolver().resolve(NameQuery(text="布洛分", purpose="general_use"), ())
    assert result.status == "needs_confirmation" and result.canonical_name is None


def test_conflicting_reviewed_alias_mappings_remain_ambiguous():
    entries = tuple({"alias": "DEMO-alias", "canonical_name": name, "reviewed": True, "scope": "ingredient",
                     "source_url": "https://example.test/DEMO-name", "source_checked_at": "2026-10-25"}
                    for name in ("DEMO-a", "DEMO-b"))
    result = MedicationNameResolver(entries).resolve(NameQuery(text="DEMO-alias", purpose="general_use"), ())
    assert result.status == "ambiguous" and result.canonical_name is None
