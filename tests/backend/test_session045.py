"""LOCAL/MOCK evidence for Session04.5; no provider inference or hidden clinical writes."""

from datetime import timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from app.application.conversation_history import ConversationHistoryService
from app.contracts.dose_display import DoseBasis, DoseDisplayInput
from app.domain.dose_display import dose_display
from app.domain.errors import AuthenticationRequiredError, NotFoundError, ValidationError
from app.infrastructure.conversation_history import MemoryConversationHistory
from app.infrastructure.supabase_data import SupabaseDataClient
from app.transport.app_factory import create_app
from app.transport.container import build_container
from fastapi.testclient import TestClient


def basis(**changes):
    return DoseBasis(
        strength_text="500 mg",
        form="tablet",
        formulation="standard",
        single_ingredient=True,
        instructions_text="Take 1 tablet daily",
        patient_checked=True,
    ).model_copy(update=changes)


def test_total_is_display_arithmetic_from_explicit_count_not_count_from_strength():
    result = dose_display(DoseDisplayInput(basis=basis(), units_per_dose=1, dose_unit="tablet"))
    assert (result.status, result.total_amount, result.total_unit) == ("calculated", 500, "mg")
    assert dose_display(DoseDisplayInput(basis=basis(), units_per_dose=2, dose_unit="tablet")).status == "conflict"
    assert (
        dose_display(
            DoseDisplayInput(basis=basis(instructions_text="Take half tablet"), units_per_dose=0.5, dose_unit="tablet")
        ).total_amount
        == 250
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"form": "liquid"},
        {"formulation": "unknown"},
        {"single_ingredient": False},
        {"single_ingredient": None},
        {"patient_checked": False},
        {"strength_text": "500 mg /5 mL"},
        {"instructions_text": ""},
        {"instructions_text": "Do not take1 tablet".replace("take1", "take 1")},
        {"instructions_text": "Take 1 tablet or 2 tablets"},
        {"instructions_text": "Take 1 tablet if advised; then take 2"},
        {"instructions_text": "每次1片，服用2片"},
        {"instructions_text": "如果需要，每次1片"},
        {"instructions_text": "Take1 tablet. Take2 tablets".replace("Take1", "Take 1").replace("Take2", "Take 2")},
    ],
)
def test_incomplete_conditional_liquid_and_combination_abstain(changes):
    assert (
        dose_display(DoseDisplayInput(basis=basis(**changes), units_per_dose=1, dose_unit="tablet")).status
        == "not_calculated"
    )


@pytest.mark.parametrize("formulation", ["modified_release", "enteric"])
def test_fractional_modified_release_is_not_converted(formulation):
    assert (
        dose_display(
            DoseDisplayInput(
                basis=basis(formulation=formulation, instructions_text="Take half tablet"),
                units_per_dose=0.5,
                dose_unit="tablet",
            )
        ).status
        == "not_calculated"
    )


def test_history_is_paginated_bounded_owned_retry_safe_and_clear_is_confirmed(clock):
    repo = MemoryConversationHistory()
    service = ConversationHistoryService(repo, clock)
    owner = uuid4()
    other = uuid4()
    session = uuid4()
    for index in range(205):
        service.append(owner, session, str(index), f"DEMO {index}", "DEMO response")
    service.append(other, uuid4(), "B", "DEMO B", "DEMO B reply")
    page = service.page(owner)
    assert len(page.entries) == 20 and page.next_before
    second = service.page(owner, page.next_before)
    assert len(second.entries) == 20
    assert not {r.id for r in page.entries} & {r.id for r in second.entries}
    assert len(repo.page(owner, clock.now() - timedelta(days=30), None, 1000)) == 200
    with pytest.raises(NotFoundError):
        service.page(other, page.next_before)
    with pytest.raises(ValidationError):
        service.append(owner, session, "204", "changed", "DEMO response")
    with pytest.raises(ValidationError):
        service.clear(owner, confirmed=False)
    service.clear(owner, confirmed=True)
    assert service.page(owner).entries == []
    assert service.page(other).entries[0].user_text == "DEMO B"


def test_history_visibility_window_does_not_promise_a_timed_physical_purge(clock):
    repo = MemoryConversationHistory()
    service = ConversationHistoryService(repo, clock)
    owner = uuid4()
    service.append(owner, uuid4(), "DEMO-old", "DEMO retained text", "DEMO response")
    clock.advance(days=31)
    assert service.page(owner).entries == []
    # Public adapter diagnostic: older text can still be stored. The patient
    # service's30-day visibility must not be described as scheduled erasure.
    assert len(repo.page(owner, clock.now() - timedelta(days=365), None, 20)) == 1
    service.clear(owner, confirmed=True)
    assert repo.page(owner, clock.now() - timedelta(days=365), None, 20) == []


def test_history_opt_in_is_independent_of_model_context_and_b14():
    root = build_container()
    client = TestClient(create_app(root))
    query = "?client_id=DEMO-history"
    start = client.post("/api/demo/start", json={"client_id": "DEMO-history"}).json()
    payload = {"session_id": start["session_id"], "text": "DEMO hello", "client_turn_id": "one"}
    client.post("/api/agent/messages" + query, json=payload)
    assert client.get("/api/agent/history" + query).json()["entries"] == []
    client.put("/api/me/preferences" + query, json={"conversation_history_enabled": True})
    payload["client_turn_id"] = "two"
    client.post("/api/agent/messages" + query, json=payload)
    assert len(client.get("/api/agent/history" + query).json()["entries"]) == 1
    assert client.get("/api/agent/history?client_id=DEMO-foreign").json()["entries"] == []
    assert client.request("DELETE", "/api/agent/history" + query, json={"confirmed": False}).status_code == 422
    assert client.request("DELETE", "/api/agent/history" + query, json={"confirmed": True}).status_code == 200
    session = root.orchestrator.get_session(patient_id=UUID(start["patient_id"]), session_id=UUID(start["session_id"]))
    assert session.context.recent_turns == []
    assert not root.store.events


def test_request_pool_is_explicit_and_keeps_user_headers_without_cross_owner_cache():
    calls = []

    def handle(request):
        calls.append(request.headers["authorization"])
        return httpx.Response(200, json=[])

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        db = SupabaseDataClient(
            base_url="https://example.invalid",
            publishable_key="SIMULATED-publishable",
            access_token="SIMULATED-user",
            patient_id=UUID(int=1),
            client=http,
        )
        db.rows("patient_medications")
        db.rows("patient_medications")
        assert not http.is_closed
        with pytest.raises(AuthenticationRequiredError):
            db.check_patient(UUID(int=2))
    assert http.is_closed and calls == ["Bearer SIMULATED-user"] * 2
