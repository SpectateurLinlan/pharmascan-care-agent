"""DEMO_ONLY explicit knowledge reads with actual service and public-label replay."""

import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from .test_workflow_records import clinical


def knowledge_engine(h, mode="matched"):
    from app.application.assistant_capabilities.knowledge import KnowledgeAdapter
    from app.application.assistant_workflows import WorkflowService
    from app.application.medication_names import MedicationNameResolver
    from app.application.medication_understanding import MedicationUnderstandingService
    from app.application.workflow_knowledge import WorkflowKnowledgeService
    from app.infrastructure.openfda_knowledge import OpenFDAKnowledge

    fixture = json.loads((Path(__file__).parent / "fixtures/ibuprofen_labels_public.json").read_text(encoding="utf-8"))

    def replay(request):
        h.knowledge_requests.append(request)
        if mode == "timeout":
            raise httpx.ReadTimeout("DEMO replay timeout")
        if mode == "conflict":
            from .test_medication_facts import scoped_label

            return httpx.Response(
                200,
                json={
                    "results": [
                        scoped_label(f"DEMO is {negative}indicated for the treatment of pain in adults.", index)
                        for index, negative in ((1, ""), (2, "not "))
                    ]
                },
            )
        return (
            httpx.Response(404)
            if mode == "not_found"
            else httpx.Response(200, content=fixture["raw_response_utf8"], headers={"Content-Type": "application/json"})
        )

    h.knowledge_http.close()
    h.knowledge_http = httpx.Client(transport=httpx.MockTransport(replay))
    resolver = MedicationNameResolver()
    understanding = MedicationUnderstandingService(
        h.container.enrollment,
        OpenFDAKnowledge(h.knowledge_http, h.clock, monotonic=lambda: 0, scoped_facts=True),
        h.clock,
        name_resolver=resolver,
    )
    adapter = KnowledgeAdapter(resolver=resolver)
    old = h.container.assistant_workflows
    service = WorkflowService(
        repository=old._repository,
        registry=old._registry,
        adapters={**old._adapters, "medication.knowledge": adapter},
        clock=h.clock,
        ids=h.container.ids,
        conversations=h.container.conversation_threads,
        preferences=h.container.preferences,
        controls=old._controls,
    )
    h.container.assistant_workflows = service
    h.container.assistant_knowledge = WorkflowKnowledgeService(
        workflows=service, understanding=understanding, resolver=resolver
    )
    return service


def query(h, task, **kwargs):
    return h._request(
        "POST",
        f"/api/agent/workflows/tasks/{task['task_id']}/knowledge",
        json={"expected_revision": task["revision"], **kwargs},
    )


@pytest.mark.parametrize("name", ["IBUPROFEN", "ibuprofen", "IbUpRoFeN", "\u5e03\u6d1b\u82ac"])
def test_only_explicit_knowledge_request_contacts_provider_and_preserves_clinical_records(workflow, name):
    h = workflow
    service = knowledge_engine(h)
    before = clinical(h)
    task = h.start("medication.knowledge", {"medication_name": name})
    h.view(task["task_id"])
    service.list_views(h.owner_ids["A"])
    assert not h.knowledge_requests and clinical(h) == before
    result = query(h, task)
    assert len(h.knowledge_requests) == 1 and '"IBUPROFEN"' in h.knowledge_requests[0].url.params["search"]
    assert result["general_knowledge"]["status"] == "matched" and result["general_knowledge"]["sources"]
    assert result["explanations"] and not result["general_knowledge"]["personal_dosing_authority"]
    assert clinical(h) == before
    assert "general_knowledge" not in h.view(task["task_id"])["visible_fields"]


@pytest.mark.parametrize("name", ["ibuprofne", "\u5e03\u6d1b\u5206"])
def test_typo_requires_a_current_offered_patient_name_choice(workflow, name):
    h = workflow
    knowledge_engine(h)
    task = h.start("medication.knowledge", {"medication_name": name})
    candidates = task["visible_fields"]["name_resolution"]["candidates"]
    assert candidates and not h.knowledge_requests
    response = h.client.post(
        f"/api/agent/workflows/tasks/{task['task_id']}/knowledge",
        params={"client_id": "DEMO-workflow-A"},
        json={"expected_revision": task["revision"]},
    )
    assert response.status_code == 422 and not h.knowledge_requests
    result = query(h, task, candidate_id=candidates[0]["id"])
    assert result["general_knowledge"]["status"] == "matched" and len(h.knowledge_requests) == 1


@pytest.mark.parametrize(
    "mode,status,reason", [("not_found", "no_reliable_match", "not_found"), ("timeout", "unavailable", "timeout")]
)
def test_provider_failure_is_a_distinct_sourced_attempt_not_generic_tool_success(workflow, mode, status, reason):
    h = workflow
    knowledge_engine(h, mode)
    task = h.start("medication.knowledge", {"medication_name": "ibuprofen"})
    result = query(h, task)
    assert result["general_knowledge"]["status"] == status and result["general_knowledge"]["reason"] == reason
    assert result["explanations"][0]["operation_key"] == "knowledge.lookup"


def test_no_save_query_uses_page_input_without_retaining_body_or_hash(workflow):
    h = workflow
    knowledge_engine(h)
    task = h.start("medication.knowledge", {"medication_name": "ibuprofen"}, save=False)
    result = query(
        h, task, ephemeral={"capability_id": "medication.knowledge", "fields": {"medication_name": "ibuprofen"}}
    )
    assert result["general_knowledge"]["status"] == "matched"
    state = h.container.assistant_workflows._repository._state
    assert not state.tasks and not state.events and not state.actions
    assert "ibuprofen" not in repr(state.controls).casefold()


@pytest.mark.parametrize(
    "failure", ["foreign", "stale", "paused", "forged_candidate", "ephemeral_missing", "wrong_capability"]
)
def test_unowned_or_changed_query_never_contacts_provider(workflow, failure):
    h = workflow
    knowledge_engine(h)
    task = h.start(
        "medication.knowledge" if failure != "wrong_capability" else "record.catalogue",
        {"medication_name": "ibuprofen"} if failure != "wrong_capability" else {},
        save=failure != "ephemeral_missing",
    )
    if failure == "paused":
        h.event(task["task_id"], "pause")
    data = {"expected_revision": task["revision"] + (1 if failure == "stale" else 0)}
    if failure == "forged_candidate":
        data["candidate_id"] = "ingredient:DEMO-forged"
    response = h.client.post(
        f"/api/agent/workflows/tasks/{task['task_id']}/knowledge",
        params={"client_id": "DEMO-workflow-B" if failure == "foreign" else "DEMO-workflow-A"},
        json=data,
    )
    assert response.status_code in {404, 409, 422} and not h.knowledge_requests


def test_model_fields_cannot_supply_answers_or_patient_name_confirmation():
    from app.contracts.assistant_workflows import validate_workflow_values
    from pydantic import ValidationError

    for field in ("patient_id", "medication_id", "general_knowledge", "candidate_id", "confirmed", "question"):
        with pytest.raises(ValidationError):
            validate_workflow_values("medication.knowledge", {field: str(uuid4())})


@pytest.mark.parametrize("text", ["look up a medicine", "\u67e5\u8be2\u836f\u7269\u77e5\u8bc6"])
def test_dedicated_chat_entry_prepares_without_lookup(workflow, text):
    from .test_workflow_enrollment import message

    h = workflow
    knowledge_engine(h)
    reply = message(h, text)
    assert reply["workflow"]["capability_id"] == "medication.knowledge" and not h.knowledge_requests


def test_query_revision_change_while_reading_does_not_return_stale_answer(workflow, monkeypatch):
    h = workflow
    knowledge_engine(h)
    task = h.start("medication.knowledge", {"medication_name": "ibuprofen"})
    understanding = h.container.assistant_knowledge.understanding
    original = understanding.explain

    def changed(**kwargs):
        result = original(**kwargs)
        h.event(task["task_id"], "pause")
        return result

    monkeypatch.setattr(understanding, "explain", changed)
    response = h.client.post(
        f"/api/agent/workflows/tasks/{task['task_id']}/knowledge",
        params={"client_id": "DEMO-workflow-A"},
        json={"expected_revision": task["revision"]},
    )
    assert response.status_code == 409 and len(h.knowledge_requests) == 1
    assert "general_knowledge" not in h.view(task["task_id"])["visible_fields"]


def test_actual_conflicting_label_response_is_withheld_and_explained(workflow):
    h = workflow
    knowledge_engine(h, "conflict")
    task = h.start("medication.knowledge", {"medication_name": "DEMO"})
    result = query(h, task)
    assert result["general_knowledge"]["reason"] == "true_scope_conflict"
    assert result["general_knowledge"]["status"] == "no_reliable_match"
    assert result["explanations"][0]["reason_key"] == "true_scope_conflict"
