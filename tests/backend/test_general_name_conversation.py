"""DEMO_ONLY empty-account HTTP conversations with public-label replay, no LLM."""

import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from app.agent.conversation import ConversationService
from app.agent.model_tools import ModelTools
from app.application.medication_names import MedicationNameResolver
from app.application.medication_understanding import MedicationUnderstandingService
from app.contracts.model import ModelReply
from app.infrastructure.memory_repos import InMemoryAgentSessionRepository
from app.infrastructure.openfda_knowledge import OpenFDAKnowledge


@pytest.fixture
def name_patient(workflow):
    h = workflow
    fixture = json.loads((Path(__file__).parent / "fixtures/ibuprofen_labels_public.json").read_text(encoding="utf-8"))
    requests = []

    def replay(request):
        requests.append(request)
        return httpx.Response(200, content=fixture["raw_response_utf8"], headers={"Content-Type": "application/json"})

    client = httpx.Client(transport=httpx.MockTransport(replay))
    knowledge = MedicationUnderstandingService(
        h.container.enrollment, OpenFDAKnowledge(client, h.clock, monotonic=lambda: 0, scoped_facts=True), h.clock,
        name_resolver=MedicationNameResolver(),
    )

    class Model:
        def create(self, **kwargs):
            return ModelReply(text="DEMO_ONLY: Please ask a new medicine question.")

    h.container.ai_agent = ConversationService(
        model=Model(), tools=ModelTools(registry=h.container.registry, fallback=h.container.orchestrator,
                                     medication_understanding=knowledge, clock=h.clock),
        fallback=h.container.orchestrator, sessions=InMemoryAgentSessionRepository(h.container.store),
        ids=h.container.ids,
    )
    h.label_requests = requests
    yield h
    client.close()


def ask(h, text, *, session=None, selection=None, owner="A"):
    return h._request("POST", "/api/agent/messages", owner=owner, json={
        "text": text, "session_id": session, "client_turn_id": "DEMO-name-" + str(uuid4()),
        **({"name_selection": selection} if selection else {}),
    })


@pytest.mark.parametrize("question", ["ibuprofen是什么", "布洛芬是什么", "What is IBUPROFEN?"])
def test_common_name_question_needs_no_registered_medicine(name_patient, question):
    h = name_patient
    reply = ask(h, question)
    assert not reply.get("medication_choice") and not reply.get("name_choice")
    assert reply["tool_traces"][0]["payload"]["general_knowledge"]["status"] == "matched"
    assert len(h.label_requests) == 1 and not h.snapshot()["medications"]


def test_typo_requires_choice_then_resumes_original_question_without_patient_identity(name_patient):
    h = name_patient
    reply = ask(h, "What is ibuprofne?")
    choice = reply["name_choice"]
    assert len(choice["options"]) <= 5 and not h.label_requests
    candidate = choice["options"][0]
    assert candidate["medication_id"] is None
    answer = ask(h, candidate["display_name"], session=reply["session_id"], selection={
        "choice_id": choice["id"], "candidate_id": candidate["id"], "expected_version": choice["version"],
    })
    assert not answer.get("name_choice") and len(h.label_requests) == 1
    assert answer["tool_traces"][0]["payload"]["general_knowledge"]["status"] == "matched"
    assert not h.snapshot()["medications"] and not h.snapshot()["dose_events"]


def test_expired_candidate_is_rejected_before_public_lookup(name_patient):
    h = name_patient
    reply = ask(h, "What is ibuprofne?")
    choice = reply["name_choice"]
    h.clock.advance(minutes=11)
    response = h.client.post("/api/agent/messages?client_id=DEMO-workflow-A", json={
        "text": "IBUPROFEN", "session_id": reply["session_id"], "client_turn_id": "DEMO-expired",
        "name_selection": {"choice_id": choice["id"], "candidate_id": choice["options"][0]["id"],
                           "expected_version": choice["version"]},
    })
    assert response.status_code in {400, 409, 422}
    assert not h.label_requests


@pytest.mark.parametrize("structured", [False, True])
def test_topic_change_invalidates_pending_name_confirmation(name_patient, structured):
    h = name_patient
    reply = ask(h, "What is ibuprofne?")
    choice = reply["name_choice"]
    ask(h, "Show my medication history", session=reply["session_id"])
    if structured:
        response = h.client.post("/api/agent/messages?client_id=DEMO-workflow-A", json={
            "text": "IBUPROFEN", "session_id": reply["session_id"], "client_turn_id": "DEMO-obsolete",
            "name_selection": {"choice_id": choice["id"], "candidate_id": choice["options"][0]["id"],
                               "expected_version": choice["version"]},
        })
        assert response.status_code in {400, 409, 422}
    else:
        ask(h, "yes", session=reply["session_id"])
    assert not h.label_requests


@pytest.mark.parametrize("change", ["choice", "candidate", "version", "owner"])
def test_forged_or_foreign_choices_cannot_trigger_public_lookup(name_patient, change):
    h = name_patient
    reply = ask(h, "What is ibuprofne?")
    choice = reply["name_choice"]
    selection = {"choice_id": choice["id"], "candidate_id": choice["options"][0]["id"],
                 "expected_version": choice["version"]}
    if change == "choice":
        selection["choice_id"] = str(uuid4())
    elif change == "candidate":
        selection["candidate_id"] = "ingredient:other"
    elif change == "version":
        selection["expected_version"] = 99
    response = h.client.post("/api/agent/messages", params={"client_id": "DEMO-workflow-B" if change == "owner"
                                                       else "DEMO-workflow-A"}, json={
        "text": "IBUPROFEN", "session_id": reply["session_id"], "client_turn_id": "DEMO-forged",
        "name_selection": selection,
    })
    assert response.status_code in {400, 403, 404, 409, 422}
    assert not h.label_requests
