"""Synthetic scope cases plus one frozen, read-only public response replay."""

import hashlib
import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest


def fact(*, quote="DEMO is indicated for the treatment of pain.", route="oral", population="adults",
         polarity="affirmed", ingredients=("demo",), source="DEMO-a"):
    from app.contracts.medication_facts import UseFact

    return UseFact(source_id=source, ingredient_set=ingredients, route_scope=route,
                   formulation_scope="tablet", release_scope="standard", population_scope=population,
                   polarity=polarity, claim_key="treatment:pain", quote=quote, field="indications_and_usage")


def test_only_opposed_claims_in_the_same_explicit_scope_conflict():
    from app.application.medication_facts import reconcile_use_facts

    positive = fact()
    negative = fact(quote="DEMO is not indicated for the treatment of pain.", polarity="denied", source="DEMO-b")
    result = reconcile_use_facts((positive, negative))
    assert result.reports_same_scope_conflict and len(result.withheld) == 2
    assert not result.supported
    different_route = reconcile_use_facts((positive, negative.model_copy(update={"route_scope": "topical"})))
    assert not different_route.reports_same_scope_conflict and positive in different_route.supported


def test_population_ingredients_release_and_unknown_scope_are_not_equated():
    from app.application.medication_facts import reconcile_use_facts

    positive = fact()
    negative = fact(polarity="denied", source="DEMO-b")
    for changes in ({"population_scope": "children"}, {"ingredient_set": ("demo", "other")},
                    {"release_scope": "modified_release"}, {"formulation_scope": None}):
        assert not reconcile_use_facts((positive, negative.model_copy(update=changes))).reports_same_scope_conflict


def test_complete_use_qualifiers_and_negation_survive_extraction():
    from app.application.medication_facts import extract_use_facts
    from app.contracts.medication_facts import UseLabelEvidence

    quote = "DEMO is not indicated for the treatment of pain in children under 12 years."
    facts = extract_use_facts(UseLabelEvidence(
        source_id="DEMO-a", names=("DEMO",), ingredient_set=("demo",), route_scope="oral",
        formulation_scope="tablet", release_scope="standard", sections={"indications_and_usage": quote},
    ))
    assert facts[0].quote == quote and facts[0].polarity == "denied"
    assert facts[0].population_scope == "children under 12 years"


def test_long_unparsed_sentences_are_withheld_without_truncating_a_qualifier():
    from app.application.medication_facts import extract_use_facts
    from app.contracts.medication_facts import UseLabelEvidence

    result = extract_use_facts(UseLabelEvidence(
        source_id="DEMO-a", names=("DEMO",), ingredient_set=("demo",),
        sections={"indications_and_usage": "DEMO is indicated for " + "pain " * 150 + "only in adults."},
    ))
    assert not result


def test_qualifying_sentence_is_not_silently_dropped_or_translated_away():
    from app.application.medication_facts import extract_use_facts
    from app.contracts.medication_facts import UseLabelEvidence
    from app.infrastructure.openfda_knowledge import chinese_use

    label = UseLabelEvidence(source_id="DEMO-a", names=("DEMO",), ingredient_set=("demo",), sections={
        "indications_and_usage": "DEMO is indicated for the treatment of pain. Only in adults with prior therapy."
    })
    facts = extract_use_facts(label)
    assert not facts or all("Only in adults" in fact.quote for fact in facts)
    assert chinese_use("DEMO is indicated for the treatment of hypertension in children over 12 years.",
                       strict=True) is None


def test_public_ibuprofen_replay_provides_scoped_partial_knowledge_without_intersection_rejection(wired):
    from app.contracts.medication_knowledge import KnowledgeProduct
    from app.infrastructure.openfda_knowledge import OpenFDAKnowledge

    fixture = json.loads((Path(__file__).parent / "fixtures/ibuprofen_labels_public.json").read_text(encoding="utf-8"))
    raw = fixture["raw_response_utf8"].encode("utf-8")
    assert hashlib.sha256(raw).hexdigest() == fixture["sha256"]
    requests = []

    def replay(request):
        requests.append(request)
        return httpx.Response(200, content=raw, headers={"Content-Type": "application/json"})

    with httpx.Client(transport=httpx.MockTransport(replay)) as client:
        provider = OpenFDAKnowledge(client, wired.clock, monotonic=lambda: 0, scoped_facts=True)
        result = provider.lookup(KnowledgeProduct(scope="ingredient", name="ibuprofen"))
    assert result.status == "matched" and result.coverage == "partial"
    assert result.sources and result.use_facts and len(requests) == 1
    assert result.translation_status == "controlled_translation" and "止痛" in result.use_statement_zh
    source_ids = {str(row.label_id) for row in result.sources}
    assert all(row.source_id in source_ids for row in result.use_facts)
    assert not result.personal_dosing_authority


def scoped_label(quote, index=1):
    return {"id": str(UUID(int=index)), "set_id": str(UUID(int=index + 100)), "version": "1",
            "effective_time": "20260101", "openfda": {"generic_name": ["DEMO"], "substance_name": ["DEMO"],
                "route": ["ORAL"], "product_type": ["HUMAN PRESCRIPTION DRUG"]},
            "dosage_forms_and_strengths": ["Modified-release tablets"], "indications_and_usage": [quote]}


@pytest.mark.parametrize("quote", [
    "DEMO is indicated for the treatment of pain in patients aged 1.5 years and older.",
    "In patients aged 18 years and older, DEMO is indicated for the treatment of pain.",
    "DEMO is indicated for the treatment of pain. Use is limited to patients aged 18 years and older.",
])
def test_provider_never_publishes_a_truncated_population_qualifier(wired, quote):
    from app.contracts.medication_knowledge import KnowledgeProduct
    from app.infrastructure.openfda_knowledge import OpenFDAKnowledge

    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={
        "results": [scoped_label(quote)]}))) as client:
        result = OpenFDAKnowledge(client, wired.clock, monotonic=lambda: 0, scoped_facts=True).lookup(
            KnowledgeProduct(scope="ingredient", name="DEMO"))
    assert result.status != "matched" or all(fact.quote == quote for fact in result.use_facts)
    if result.status == "matched":
        from app.application.medication_presentation import general_use_text
        assert general_use_text(result, "en") == quote


def test_provider_extracts_and_withholds_true_same_scope_opposed_claims(wired):
    from app.contracts.medication_knowledge import KnowledgeProduct
    from app.infrastructure.openfda_knowledge import OpenFDAKnowledge

    rows = [scoped_label(f"DEMO is {negative}indicated for the treatment of pain in adults.", index)
            for index, negative in ((1, ""), (2, "not "))]
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"results": rows}))) as client:
        result = OpenFDAKnowledge(client, wired.clock, monotonic=lambda: 0, scoped_facts=True).lookup(
            KnowledgeProduct(scope="ingredient", name="DEMO"))
    assert result.status == "no_reliable_match" and result.reason == "true_scope_conflict"
