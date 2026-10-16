"""LOCAL / MOCK: real domain/application/HTTP, no external provider calls."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from app.agent.long_term_tools import CARE_SPECS, execute_care_tool
from app.agent.model_tools import model_tool_schemas
from app.application.long_term import LongTermCareService, observation_trends
from app.application.observations import ObservationService
from app.application.review_summary import ReviewSummaryService
from app.contracts.dto import DoseEventDTO, FrequencyRuleDTO, RegimenDraftInput
from app.contracts.enums import IntakeStatus
from app.contracts.long_term import BarrierInput, CareTaskInput, StockInput, TaskUpdate
from app.contracts.observations import ObservationInput
from app.domain.errors import NotFoundError, ValidationError
from app.domain.inventory import ledger_balance
from app.infrastructure.care_repos import MemoryCareRepository
from app.infrastructure.observation_repos import MemoryObservations
from app.transport.app_factory import create_app
from app.transport.container import build_container
from fastapi.testclient import TestClient
from pydantic import ValidationError as SchemaError


@pytest.fixture()
def care(wired):
    notes = ObservationService(MemoryObservations(), wired.medications, wired.clock)
    summaries = ReviewSummaryService(wired.enrollment, wired.occurrences, wired.events, notes, wired.clock)
    repo = MemoryCareRepository()
    service = LongTermCareService(repo, wired.enrollment, wired.events, notes, summaries, wired.clock)
    patient = uuid4()
    draft = wired.enrollment.enroll_draft(
        patient_id=patient,
        draft=RegimenDraftInput(
            medication_name="DEMO Metformin 500 mg",
            dose_amount=1,
            dose_unit="tablet",
            frequency_rule=FrequencyRuleDTO(kind="daily", local_times=["08:00", "20:00"]),
            food_instruction="after food",
        ),
    )
    wired.enrollment.review_source_fields(patient_id=patient, source_id=draft.regimen.source_id)
    challenge, _ = wired.enrollment.request_activation_challenge(
        patient_id=patient, regimen_id=draft.regimen.id, session_id=uuid4(), session_state_version=1
    )
    wired.enrollment.confirm_challenge(patient_id=patient, challenge_id=challenge.id)
    wired.enrollment.activate_regimen(
        patient_id=patient,
        regimen_id=draft.regimen.id,
        challenge_id=challenge.id,
        session_state="awaiting_confirmation",
        session_state_version=1,
    )
    return service, repo, notes, patient, draft


def stock(quantity=3, **changes):
    return StockInput(id=uuid4(), kind="count", quantity=quantity, unit="tablet", confirmed=True, **changes)


def test_scenario_e_inventory_refill_cross_session_and_task_history(care, wired):
    service, repo, notes, patient, draft = care
    medication = draft.medication.id
    assert service.inventory(patient, medication).estimated_remaining is None
    values = stock()
    first = service.record_stock(patient, medication, values, "Asia/Singapore")
    assert first.low_stock and first.daily_requirement == 2 and first.estimated_days == 1.5
    assert len(service.tasks(patient)) == 1
    task = service.tasks(patient)[0]
    contacted = TaskUpdate(
        id=uuid4(), expected_version=task.version, status="contacted", confirmed=True, notes="DEMO called pharmacy"
    )
    updated = service.update_task(patient, task.id, contacted)
    assert updated.status == "contacted" and len(updated.history) == 2
    assert service.update_task(patient, task.id, contacted) == updated
    assert service.record_stock(patient, medication, values, "Asia/Singapore").estimated_remaining == 3
    refill = StockInput(id=uuid4(), kind="refill", quantity=30, unit="tablet", confirmed=True)
    service.record_stock(patient, medication, refill, "Asia/Singapore")
    result = service.record_stock(patient, medication, refill, "Asia/Singapore")
    assert result.estimated_remaining == 33 and len(result.transactions) == 2
    assert service.tasks(patient)[0].status == "completed"
    assert len(service.tasks(patient)[0].history) == 3
    # A new application/session instance reads the repository, not chat memory.
    fresh = LongTermCareService(
        repo,
        wired.enrollment,
        wired.events,
        notes,
        ReviewSummaryService(wired.enrollment, wired.occurrences, wired.events, notes, wired.clock),
        wired.clock,
    )
    assert fresh.inventory(patient, medication).estimated_remaining == 33
    assert fresh.actionable_tasks(patient, "Asia/Singapore") == []
    assert not wired.store.events


def test_stock_confirmation_units_idempotency_and_owner(care, wired):
    service, _, _, patient, draft = care
    medication = draft.medication.id
    values = stock()
    with pytest.raises(ValidationError):
        service.record_stock(patient, medication, values.model_copy(update={"confirmed": False}), "Asia/Singapore")
    with pytest.raises(NotFoundError):
        service.record_stock(uuid4(), medication, values, "Asia/Singapore")
    service.record_stock(patient, medication, values, "Asia/Singapore")
    with pytest.raises(ValidationError):
        service.record_stock(patient, medication, values.model_copy(update={"quantity": 100}), "Asia/Singapore")
    with pytest.raises(ValidationError):
        service.record_stock(patient, medication, stock(4).model_copy(update={"unit": "capsule"}), "Asia/Singapore")
    with pytest.raises(ValidationError):
        service.record_stock(patient, medication, stock(8).model_copy(update={"kind": "lost"}), "Asia/Singapore")
    assert service.tasks(uuid4()) == [] and not wired.store.events


@pytest.mark.parametrize(
    "kind,quantity,expected",
    [("count", 4, 4), ("refill", 4, 9), ("adjustment", -2, 3), ("lost", 2, 3), ("discarded", 1, 4), ("damaged", 3, 2)],
)
def test_pure_stock_rules(kind, quantity, expected):
    values = StockInput(id=uuid4(), kind=kind, quantity=quantity, unit="tablet")
    assert ledger_balance(5, "tablet", values) == expected
    if kind != "count":
        with pytest.raises(ValidationError):
            ledger_balance(None, None, values)


@pytest.mark.parametrize(
    "change",
    [
        {"unit": "mg"},
        {"quantity": float("nan")},
        {"quantity": float("inf")},
        {"kind": "refill", "quantity": -1},
        {"kind": "lost", "quantity": 0},
        {"patient_id": str(uuid4())},
    ],
)
def test_invalid_inventory_inputs(change):
    with pytest.raises(SchemaError):
        StockInput.model_validate({"id": str(uuid4()), "kind": "count", "quantity": 3, "unit": "tablet", **change})


def test_concurrent_stock_idempotency_and_atomic_refills(care):
    service, _, _, patient, draft = care
    medication = draft.medication.id
    service.record_stock(patient, medication, stock(20), "Asia/Singapore")
    values = StockInput(id=uuid4(), kind="refill", quantity=5, unit="tablet", confirmed=True)
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda _: service.record_stock(patient, medication, values, "Asia/Singapore"), range(12)))
    assert service.inventory(patient, medication).estimated_remaining == 25
    assert len(service.inventory(patient, medication).transactions) == 2


@pytest.mark.parametrize(
    "change", [{"is_prn": True}, {"dose_unit": "mg"}, {"state": "ended"}, {"frequency_rule": None}]
)
def test_prn_stopped_or_incomplete_never_estimates_fixed_demand(care, wired, change, monkeypatch):
    from app.contracts.enums import RegimenState

    service, _, _, patient, draft = care
    if "state" in change:
        change["state"] = RegimenState.ENDED
    regimen = wired.regimens.get(patient, draft.regimen.id)
    # Exercise read-policy variants without weakening immutable active versions.
    monkeypatch.setattr(
        wired.enrollment, "list_regimens", lambda owner, medication: [regimen.model_copy(update=change)]
    )
    result = service.record_stock(patient, draft.medication.id, stock(1), "Asia/Singapore")
    assert result.daily_requirement is None and not result.low_stock and not service.tasks(patient)


def test_estimate_only_compatible_reported_taken_and_physical_recount(care, wired):
    service, _, _, patient, draft = care
    medication = draft.medication.id
    service.record_stock(patient, medication, stock(20), "Asia/Singapore")
    wired.clock.advance(minutes=5)
    # A repository fixture, not a bypass in production: negative B14 tests run separately.
    for status in (IntakeStatus.REPORTED_TAKEN, IntakeStatus.REPORTED_NOT_TAKEN, IntakeStatus.UNSURE):
        wired.events.add(
            DoseEventDTO(
                id=uuid4(),
                patient_id=patient,
                regimen_id=draft.regimen.id,
                occurrence_id=None,
                event_time=wired.clock.now(),
                intake_status=status,
                idempotency_key=str(uuid4()),
                created_at=wired.clock.now(),
            )
        )
    assert service.inventory(patient, medication).estimated_remaining == 19
    refill = StockInput(id=uuid4(), kind="refill", quantity=10, unit="tablet", confirmed=True)
    assert service.record_stock(patient, medication, refill, "Asia/Singapore").estimated_remaining == 29
    wired.clock.advance(minutes=1)
    assert service.record_stock(patient, medication, stock(25), "Asia/Singapore").estimated_remaining == 25


def test_barriers_followup_scenario_f_and_historical_review(care, wired):
    service, _, notes, patient, draft = care
    task = CareTaskInput(
        id=uuid4(),
        category="medication_review",
        title="DEMO pharmacist next week",
        due_at=wired.clock.now() + timedelta(days=7),
        medication_id=draft.medication.id,
        regimen_id=draft.regimen.id,
        confirmed=True,
        notes="DEMO patient reported appointment",
    )
    saved = service.create_task(patient, task)
    assert service.create_task(patient, task) == saved
    barrier = BarrierInput(
        id=uuid4(),
        category="forgetfulness",
        occurred_at=wired.clock.now(),
        regimen_id=draft.regimen.id,
        description="DEMO irregular routine",
        chosen_action="DEMO review reminders",
        follow_up_task_id=saved.id,
        confirmed=True,
    )
    assert service.record_barrier(patient, barrier) == service.record_barrier(patient, barrier)
    with pytest.raises(ValidationError):
        service.record_barrier(patient, barrier.model_copy(update={"description": "changed"}))
    with pytest.raises(NotFoundError):
        service.record_barrier(uuid4(), barrier)
    for offset, value in [(3, 130), (1, 125)]:
        notes.save(
            patient,
            ObservationInput(
                id=uuid4(),
                description="DEMO measured BP",
                kind="blood_pressure",
                value=value,
                secondary_value=80,
                unit="mmHg",
                occurred_at=wired.clock.now() - timedelta(days=offset),
                confirmed=True,
            ),
        )
    data = service.review(patient, 7, "Asia/Singapore").model_dump(mode="json")
    tool = execute_care_tool(
        service,
        name="get_longitudinal_summary",
        arguments={"days": 7},
        patient_id=patient,
        session_id=uuid4(),
        turn_id="demo-private",
        text="DEMO progress",
        language="en",
        timezone="Asia/Singapore",
    )
    assert "patient_id" not in json.dumps(tool.data) and str(patient) not in json.dumps(tool.data)
    assert data["trends"][0]["change"] == -5 and data["trends"][0]["count"] == 2
    assert len(data["barriers"]) == 1 and len(data["follow_ups"]) == 1
    assert data["summary"]["reported_taken"] == 0 and "not missed" in data["adherence_denominator"]
    deferred = TaskUpdate(
        id=uuid4(), expected_version=1, status="deferred", due_at=wired.clock.now() + timedelta(days=8), confirmed=True
    )
    assert service.update_task(patient, saved.id, deferred).version == 2
    with pytest.raises(ValidationError):
        service.update_task(
            patient, saved.id, TaskUpdate(id=uuid4(), expected_version=1, status="completed", confirmed=True)
        )
    cancelled = service.update_task(
        patient, saved.id, TaskUpdate(id=uuid4(), expected_version=2, status="cancelled", confirmed=True)
    )
    assert len(cancelled.history) == 3 and service.actionable_tasks(patient, "Asia/Singapore") == []
    assert not wired.store.events


@pytest.mark.parametrize(
    "values",
    [
        {"kind": "blood_pressure", "value": 120, "unit": "mmHg"},
        {"kind": "blood_glucose", "value": 5, "unit": "kg"},
        {"kind": "note", "value": 1},
        {"kind": "weight", "value": float("nan"), "unit": "kg"},
    ],
)
def test_measurement_unit_and_completeness(values, clock):
    with pytest.raises(SchemaError):
        ObservationInput(id=uuid4(), description="DEMO", occurred_at=clock.now(), **values)


def test_agent_tools_are_read_or_prepare_only_and_cannot_supply_identity(care, wired):
    service, _, _, patient, draft = care
    session = uuid4()
    parameters = {
        "service": service,
        "patient_id": patient,
        "session_id": session,
        "turn_id": "demo-1",
        "text": "DEMO I counted 3 tablets",
        "language": "en",
        "timezone": "Asia/Singapore",
    }
    output = execute_care_tool(
        name="prepare_stock_change",
        arguments={"medication_id": str(draft.medication.id), "kind": "count", "quantity": 3, "unit": "tablet"},
        **parameters,
    )
    assert output.review and output.review.stock.confirmed is False
    assert service.inventory(patient, draft.medication.id).transactions == [] and not wired.store.events
    output2 = execute_care_tool(
        name="prepare_stock_change",
        arguments={"medication_id": str(draft.medication.id), "kind": "count", "quantity": 3, "unit": "tablet"},
        **parameters,
    )
    assert output.review == output2.review
    with pytest.raises(SchemaError):
        execute_care_tool(name="get_unresolved_follow_ups", arguments={"patient_id": str(uuid4())}, **parameters)
    with pytest.raises(SchemaError):
        execute_care_tool(name="prepare_medication_care_task", arguments={"category": "vaccination"}, **parameters)
    schemas = {row["name"]: row for row in model_tool_schemas()}
    assert set(CARE_SPECS) <= set(schemas)
    for name in CARE_SPECS:
        assert not ({"patient_id", "confirmed", "access_token"} & set(schemas[name]["parameters"]["properties"]))


def test_http_confirmations_owner_isolation_and_no_dose_side_effect(clock):
    container = build_container(clock=clock)
    client = TestClient(create_app(container))
    owner = {"client_id": "DEMO-care-a"}
    other = {"client_id": "DEMO-care-b"}
    values = {
        "id": str(uuid4()),
        "category": "medication_review",
        "title": "DEMO review",
        "due_at": (clock.now() + timedelta(days=1)).isoformat(),
        "confirmed": True,
    }
    assert client.post("/api/me/care-tasks", params=owner, json={**values, "confirmed": False}).status_code == 422
    assert (
        client.post("/api/me/care-tasks", params=owner, json={**values, "patient_id": str(uuid4())}).status_code == 422
    )
    assert client.post("/api/me/care-tasks", params=owner, json=values).status_code == 200
    assert len(client.get("/api/me/care-tasks", params=owner).json()) == 1
    assert client.get("/api/me/care-tasks", params=other).json() == []
    assert client.get("/api/me/medication-review", params=owner).json()["follow_ups"][0]["title"] == "DEMO review"
    assert not container.store.events


def test_no_numeric_records_no_fabricated_trend():
    assert observation_trends([]) == []


def test_task_retry_cannot_silently_change_the_reviewed_date_or_notes(care, wired):
    service, _, _, patient, _ = care
    value = CareTaskInput(
        id=uuid4(),
        category="medication_review",
        title="DEMO review",
        due_at=wired.clock.now() + timedelta(days=1),
        notes="DEMO original",
        confirmed=True,
    )
    row = service.create_task(patient, value)
    assert len(row.history) == 1
    for change in ({"due_at": value.due_at + timedelta(days=1)}, {"notes": "DEMO changed"}):
        with pytest.raises(ValidationError):
            service.create_task(patient, value.model_copy(update=change))


def test_weekly_demand_and_course_boundary_use_stored_rule_timezone(care, wired):
    from app.domain.inventory import scheduled_daily_requirement

    _, _, _, patient, draft = care
    regimen = wired.regimens.get(patient, draft.regimen.id)
    rule = {"kind": "weekly", "local_times": ["08:00"], "days_of_week": [1, 3, 5]}
    row = regimen.model_copy(update={"frequency_rule": rule})
    assert scheduled_daily_requirement([row], "tablet", wired.clock.now(), "Asia/Singapore") == 3 / 7
    # At23:00UTC it is the next day in Singapore, still the previous day in NY.
    row = row.model_copy(update={"course_end_date": wired.clock.now().date()})
    assert scheduled_daily_requirement([row], "tablet", wired.clock.now(), "Asia/Singapore") is None
    assert (
        scheduled_daily_requirement([row], "tablet", wired.clock.now(), "Asia/Singapore", {row.id: "America/New_York"})
        == 3 / 7
    )


def test_stopping_plan_cancels_derived_supply_task_without_deleting_history(care, wired):
    service, _, _, patient, draft = care
    service.record_stock(patient, draft.medication.id, stock(1), "Asia/Singapore")
    assert len(service.tasks(patient)) == 1
    wired.enrollment.end_regimen(patient_id=patient, regimen_id=draft.regimen.id)
    assert service.refresh_refill_tasks(patient, "Asia/Singapore") == []
    assert service.tasks(patient)[0].status == "cancelled" and len(service.tasks(patient)[0].history) == 2


def test_query_days_coercion_and_invalid_window(clock):
    app = TestClient(create_app(build_container(clock=clock)))
    assert app.get("/api/me/medication-review", params={"client_id": "DEMO-query", "days": "7"}).status_code == 200
    assert app.get("/api/me/medication-review", params={"client_id": "DEMO-query", "days": "8"}).status_code == 422


@pytest.mark.parametrize(
    "name", ["prepare_medication_care_task", "prepare_adherence_barrier", "prepare_care_task_update"]
)
def test_other_prepared_actions_never_write_before_human_review(care, wired, name):
    from app.agent.memory import record_context
    from app.agent.tools import ToolResult
    from app.contracts.agent_context import AgentContext
    from app.contracts.enums import ToolName, ToolStatus

    service, _, _, patient, draft = care
    task = service.create_task(
        patient,
        CareTaskInput(
            id=uuid4(),
            category="medication_review",
            title="DEMO appointment",
            due_at=wired.clock.now() + timedelta(days=7),
            confirmed=True,
        ),
    )
    arguments = {
        "prepare_medication_care_task": {
            "category": "medication_review",
            "title": "DEMO next review",
            "due_at": (wired.clock.now() + timedelta(days=8)).isoformat(),
            "medication_id": str(draft.medication.id),
            "regimen_id": str(draft.regimen.id),
        },
        "prepare_adherence_barrier": {
            "category": "forgetfulness",
            "occurred_at": wired.clock.now().isoformat(),
            "regimen_id": str(draft.regimen.id),
        },
        "prepare_care_task_update": {"task_id": str(task.id), "status": "completed"},
    }[name]
    output = execute_care_tool(
        service,
        name=name,
        arguments=arguments,
        patient_id=patient,
        session_id=uuid4(),
        turn_id="DEMO-propose",
        text="DEMO my own description",
        language="en",
        timezone="Asia/Singapore",
    )
    assert output.review and not service.barriers(patient)
    assert service.tasks(patient) == [task] and not wired.store.events
    context = record_context(
        AgentContext(),
        text="DEMO",
        message="Review",
        intent="clarification",
        language="en",
        results=[
            ToolResult(tool_name=ToolName.PREPARE_CARE_ACTION, status=ToolStatus.SUCCESS, payload={"action": name})
        ],
    )
    assert context.active_task == name and len(context.recent_turns) == 1


@pytest.mark.parametrize("repair", [False, True])
def test_narrow_followup_read_cannot_erase_verified_symptoms_from_review(clock, repair):
    from app.agent.conversation import ConversationService
    from app.agent.model_tools import ModelTools
    from app.agent.orchestrator import AgentTurn
    from app.contracts.model import FunctionCall, ModelReply

    container = build_container(clock=clock)
    patient = uuid4()
    container.observations.save(
        patient,
        ObservationInput(
            id=uuid4(), description="DEMO felt tired", occurred_at=clock.now() - timedelta(minutes=1), confirmed=True
        ),
    )
    container.long_term.create_task(
        patient,
        CareTaskInput(
            id=uuid4(),
            category="medication_review",
            title="DEMO pharmacist visit",
            due_at=clock.now() + timedelta(days=1),
            confirmed=True,
        ),
    )
    session = container.orchestrator.start_session(patient_id=patient)

    class Model:
        model = "SIMULATED"

        def __init__(self):
            self.rounds = 0

        def create(self, **kwargs):
            self.rounds += 1
            if repair and self.rounds == 1:
                return ModelReply(
                    calls=[FunctionCall(id="demo-tasks-first", name="get_unresolved_follow_ups", arguments={})]
                )
            if repair and self.rounds == 2:
                return ModelReply(text="Partial task read only")
            if self.rounds == (3 if repair else 1):
                return ModelReply(
                    calls=[
                        FunctionCall(id="demo-review", name="prepare_medication_review", arguments={}),
                        FunctionCall(id="demo-tasks", name="get_unresolved_follow_ups", arguments={}),
                    ]
                )
            return ModelReply(text="UNTRUSTED: all drugs are safe")

    from app.infrastructure.memory_repos import InMemoryAgentSessionRepository

    model = Model()
    service = ConversationService(
        model=model,
        tools=ModelTools(registry=container.registry, fallback=container.orchestrator, long_term=container.long_term),
        fallback=container.orchestrator,
        sessions=InMemoryAgentSessionRepository(container.store),
        ids=container.ids,
    )
    response = service.handle_turn(
        patient_id=patient, session_id=session.id, turn=AgentTurn(text="DEMO prepare my pharmacist visit and symptoms")
    )
    assert (
        model.rounds == (4 if repair else 2)
        and "DEMO felt tired" in response.message
        and "DEMO pharmacist visit" in response.message
    )
    assert "all drugs are safe" not in response.message and not container.store.events


@pytest.mark.parametrize(
    "field",
    [
        "medication",
        "stock_quantity",
        "stock_unit",
        "follow_up_date",
        "follow_up_type",
        "barrier_time",
        "support_action",
    ],
)
def test_bounded_care_clarification_has_no_write_and_retains_only_verified_field(care, field):
    from app.agent.memory import record_context
    from app.agent.tools import ToolResult
    from app.contracts.agent_context import AgentContext
    from app.contracts.enums import ToolName, ToolStatus

    service, _, _, patient, _ = care
    output = execute_care_tool(
        service,
        name="clarify_medication_care",
        arguments={"missing_field": field},
        patient_id=patient,
        session_id=uuid4(),
        turn_id="demo-clarify",
        text="DEMO help",
        language="zh",
        timezone="Asia/Singapore",
    )
    assert any("\u4e00" <= char <= "\u9fff" for char in output.data["patient_safe_summary"])
    context = record_context(
        AgentContext(),
        text="DEMO",
        message=output.data["patient_safe_summary"],
        intent="clarification",
        language="zh",
        results=[
            ToolResult(
                tool_name=ToolName.GET_LONG_TERM_CARE,
                status=ToolStatus.SUCCESS,
                payload={"action": "clarify_medication_care", "care_clarification": output.data["care_clarification"]},
            )
        ],
    )
    assert (
        context.care_clarification.missing_field == field
        and not service.tasks(patient)
        and not service.barriers(patient)
    )
