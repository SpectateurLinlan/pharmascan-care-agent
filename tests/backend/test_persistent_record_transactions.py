"""DEMO_ONLY native report confirmation coupled to a workflow transaction."""

import importlib
from uuid import UUID, uuid4

import pytest
from app.contracts.assistant_workflows import BusinessRef
from app.contracts.dto import DoseEventInput
from app.contracts.enums import IntakeStatus
from app.contracts.late_reports import LateReportInput
from app.contracts.workflow_persistence import WorkflowWriteBinding
from app.domain.errors import DuplicateEventError, StaleVersionError

from .test_workflow_late_reports import body, existing_occurrence, path
from .test_workflow_late_reports import prepared as prepared_late
from .test_workflow_report_bindings import headers, prepared, prn_plan


def api(name):
    return getattr(importlib.import_module("app.contracts.workflow_record_writes"), name)


def harness(h):
    cls = importlib.import_module("app.infrastructure.workflow_record_writes").MemoryRecordWorkflowWrites
    workflow = h.container.assistant_workflows
    return cls(
        state=workflow._repository._state,
        store=h.container.store,
        clock=h.clock,
        tasks=workflow._repository,
        controls=workflow._controls,
        actions=h.container.assistant_reports._adapter.actions,
        reports=h.container.self_report,
        late_reports=h.container.late_reports,
        enrollment=h.container.enrollment,
        schedule=h.container.schedule,
    )


def binding(h, port, view, action_key, ref):
    return WorkflowWriteBinding(
        task_id=UUID(view["task_id"]),
        task_revision=view["revision"],
        capability_id=view["capability_id"],
        action_key=action_key,
        prepared_ref=ref,
        expected_domain_revision=port.revision(h.owner_ids["A"]),
    )


def prn_command(h):
    plan = prn_plan(h)
    view = prepared(h, plan)
    key = uuid4()
    values = {"regimen_id": plan["regimen_id"], "intake_status": "taken", "idempotency_key": "report-" + str(key)}
    summary = h._request("POST", "/api/prn/report/challenge", json=values, headers=headers(view))
    port = harness(h)
    command = api("PrnReportWrite")(
        binding=binding(h, port, view, key, BusinessRef(kind="regimen", id=UUID(plan["regimen_id"]), version=1)),
        confirmed=True,
        challenge_id=UUID(summary["challenge_id"]),
        values=DoseEventInput(
            regimen_id=UUID(plan["regimen_id"]),
            occurrence_id=None,
            intake_status="reported_taken",
            idempotency_key=values["idempotency_key"],
            event_time=h.clock.now(),
        ),
    )
    return port, command, summary


def test_report_keeps_native_confirmation_and_plan_version(workflow):
    h, owner = workflow, workflow.owner_ids["A"]
    port, command, summary = prn_command(h)
    challenge_id = UUID(summary["challenge_id"])
    assert h.container.store.challenges[owner, challenge_id].confirmed_at is None
    result = port.apply(owner, command)
    assert result.result.event.ingestion_proven is False
    assert result.receipt.business_ref == BusinessRef(kind="dose_event", id=result.result.event.id)
    assert result.receipt.binding_revision == command.binding.task_revision + 1
    assert h.container.assistant_workflows.view(owner, command.binding.task_id).state == "completed"
    assert h.container.store.challenges[owner, challenge_id].consumed_at is not None
    assert port.apply(owner, command).receipt == result.receipt and len(h.container.store.events) == 1
    changed = command.model_copy(
        update={"values": command.values.model_copy(update={"intake_status": IntakeStatus.UNSURE})}
    )
    with pytest.raises(DuplicateEventError):
        port.apply(owner, changed)


def test_prn_never_materializes_an_occurrence_or_uses_a_client_backfill_time(workflow):
    from datetime import timedelta

    h, owner = workflow, workflow.owner_ids["A"]
    port, command, _summary = prn_command(h)
    before = dict(h.container.store.occurrences)
    command = command.model_copy(
        update={"values": command.values.model_copy(update={"event_time": h.clock.now() - timedelta(days=2)})}
    )
    result = port.apply(owner, command)
    assert result.result.event.event_time == h.clock.now()
    assert result.result.event.occurrence_id is None and dict(h.container.store.occurrences) == before


def test_failed_task_advance_rolls_back_confirmation_report_and_receipt(workflow, monkeypatch):
    h, owner = workflow, workflow.owner_ids["A"]
    port, command, _summary = prn_command(h)
    before = h.snapshot()

    def fail(*args, **kwargs):
        raise StaleVersionError("DEMO concurrent task revision")

    monkeypatch.setattr(h.container.assistant_workflows._repository, "cas", fail)
    with pytest.raises(StaleVersionError):
        port.apply(owner, command)
    assert h.snapshot() == before and port.lookup(owner, command.binding.action_key) is None


def test_correction_preserves_original_event_and_previous_report(workflow):
    h, owner = workflow, workflow.owner_ids["A"]
    occurrence = existing_occurrence(h)
    original = dict(h.container.store.events)
    saved = []
    for correction in (False, True):
        view = prepared_late(h, occurrence, "dose.correction.review" if correction else "dose.late.review")
        values = LateReportInput.model_validate(
            {
                **body(str(saved[0].result.id) if correction else None),
                **({"reason": "correcting_record", "intake_status": "unsure"} if correction else {}),
            }
        )
        summary = h._request(
            "POST", path(occurrence) + "/challenge", json=values.model_dump(mode="json"), headers=headers(view)
        )
        port = harness(h)
        command = api("CorrectionWrite" if correction else "LateReportWrite")(
            binding=binding(
                h, port, view, values.id, BusinessRef(kind="dose_occurrence", id=occurrence.id, version=len(saved) + 1)
            ),
            confirmed=True,
            challenge_id=UUID(summary["challenge_id"]),
            occurrence_id=occurrence.id,
            values=values,
        )
        saved.append(port.apply(owner, command))
    assert h.container.store.events == original
    history = h.container.late_reports.audit(owner, occurrence.id).corrections
    assert [row.intake_status for row in history] == ["reported_taken", "unsure"]
    assert history[0] == saved[0].result and saved[1].result.version == 2
    assert saved[1].receipt.business_ref == BusinessRef(kind="late_report", id=history[1].id, version=2)


def test_unbound_late_report_uses_clinical_fence_before_shared_report_lock(workflow):
    """Reverse acquisition can deadlock a native API against a coupled writer."""
    h, owner = workflow, workflow.owner_ids["A"]
    occurrence = existing_occurrence(h)
    values = LateReportInput.model_validate(body())
    summary = h._request("POST", path(occurrence) + "/challenge", json=values.model_dump(mode="json"))
    original_lock = h.container.store.clinical.lock
    late_lock = h.container.store.late_report_lock

    class RequireClinicalFence:
        def __enter__(self):
            assert not late_lock._is_owned() or original_lock._is_owned(), "Native lock order is reversed"
            original_lock.acquire()
            return self

        def __exit__(self, *args):
            original_lock.release()

    h.container.store.clinical.lock = RequireClinicalFence()
    actual = h.container.late_reports.confirm(owner, occurrence.id, values, UUID(summary["challenge_id"]))
    assert actual.id == values.id and actual.ingestion_proven is False


def test_cancel_blocks_new_challenge_preparation_but_independent_patient_confirmation_survives(workflow):
    from app.contracts.workflow_persistence import RunWriteBinding
    from app.infrastructure.durable_agent_runs import MemoryDurableRunControl

    from .test_durable_agent_runs import claimed

    h, owner = workflow, workflow.owner_ids["A"]
    plan = prn_plan(h)
    view = prepared(h, plan)
    port = harness(h)
    session = h.container.orchestrator.start_session(patient_id=owner)
    session = h.container.orchestrator.await_confirmation(patient_id=owner, session_id=session.id)
    state = h.container.assistant_workflows._repository._state
    runs = MemoryDurableRunControl(clock=h.clock, state=state)
    run = claimed(runs, owner)
    operation_key = uuid4()
    b = binding(h, port, view, uuid4(), BusinessRef(kind="regimen", id=UUID(plan["regimen_id"]), version=1))
    b = b.model_copy(update={"run_binding": RunWriteBinding(run_id=run.run_id, epoch=run.epoch)})
    command = api("PrepareDoseReport")(
        binding=b,
        session_id=session.id,
        session_state_version=session.state_version,
        operation_key=operation_key,
        intake_status="reported_taken",
    )
    prepared_result = port.prepare(owner, command)
    assert prepared_result.receipt.outcome == "prepared" and not h.container.store.events
    assert prepared_result.result.challenge.confirmed_at is None
    import httpx
    from app.infrastructure.enrollment_operations import InMemoryEnrollmentWritePort
    from app.infrastructure.supabase_data import SupabaseDataClient
    from app.infrastructure.workflow_repos import SupabaseWorkflowMutations

    cls = importlib.import_module("app.infrastructure.workflow_record_writes").SupabaseRecordWorkflowWrites
    calls = []

    def remote_result(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(
            200, json=[] if request.method == "GET" else {"result": prepared_result.model_dump(mode="json")}
        )

    data = SupabaseDataClient(
        base_url="https://example.invalid",
        publishable_key="sb_publishable_DEMO",
        access_token="DEMO-token",
        patient_id=owner,
        client=httpx.Client(transport=httpx.MockTransport(remote_result)),
    )
    remote = cls(
        data=data, reads=InMemoryEnrollmentWritePort(h.container.store), receipts=SupabaseWorkflowMutations(data)
    )
    assert remote.prepare(owner, command) == prepared_result
    assert calls == [("GET", "/rest/v1/assistant_business_receipts"), ("POST", "/rest/v1/rpc/assistant_record_prepare")]
    runs.request_cancel(owner, run.run_id)
    before = h.snapshot()
    newer = command.model_copy(update={"binding": b.model_copy(update={"action_key": uuid4()})})
    with pytest.raises(StaleVersionError):
        port.prepare(owner, newer)
    assert h.snapshot() == before
    replay = port.prepare(owner, command)
    assert replay.receipt == prepared_result.receipt and replay.result.token == "" and replay.result.created is False
    h.clock.advance(seconds=46)
    confirm = api("PrnReportWrite")(
        binding=b.model_copy(update={"action_key": operation_key, "run_binding": None}),
        confirmed=True,
        challenge_id=prepared_result.result.challenge.id,
        values=DoseEventInput(
            regimen_id=UUID(plan["regimen_id"]),
            occurrence_id=None,
            intake_status="reported_taken",
            event_time=h.clock.now(),
            idempotency_key="report-" + str(operation_key),
        ),
    )
    result = port.apply(owner, confirm)
    assert result.result.event is not None and result.receipt.outcome == "applied"
    assert port.apply(owner, confirm).receipt == result.receipt and len(h.container.store.events) == 1


def test_scheduled_preparation_requires_an_existing_explicit_occurrence_without_generating_history(workflow):
    from app.domain.errors import ValidationError

    from .test_workflow_medication_management import active_plan

    h, owner = workflow, workflow.owner_ids["A"]
    plan = active_plan(h)
    h.clock.advance(hours=13)
    view = prepared(h, plan, "dose.report")
    port = harness(h)
    session = h.container.orchestrator.start_session(patient_id=owner)
    session = h.container.orchestrator.await_confirmation(patient_id=owner, session_id=session.id)
    command = api("PrepareDoseReport")(
        binding=binding(h, port, view, uuid4(), BusinessRef(kind="regimen", id=UUID(plan["regimen_id"]), version=1)),
        operation_key=uuid4(),
        intake_status="reported_taken",
        session_id=session.id,
        session_state_version=session.state_version,
    )
    before = h.snapshot()
    with pytest.raises(ValidationError):
        port.prepare(owner, command)
    assert h.snapshot() == before


def test_typed_historical_preparation_only_issues_a_bound_unconfirmed_challenge(workflow):
    h, owner = workflow, workflow.owner_ids["A"]
    occurrence = existing_occurrence(h)
    view = prepared_late(h, occurrence)
    port = harness(h)
    values = LateReportInput.model_validate(body())
    session = h.container.orchestrator.start_session(patient_id=owner)
    session = h.container.orchestrator.await_confirmation(patient_id=owner, session_id=session.id)
    command = api("PrepareLateReport")(
        binding=binding(h, port, view, uuid4(), BusinessRef(kind="dose_occurrence", id=occurrence.id, version=1)),
        session_id=session.id,
        session_state_version=session.state_version,
        values=values,
    )
    original = dict(h.container.store.events)
    occurrences = dict(h.container.store.occurrences)
    result = port.prepare(owner, command)
    assert result.result.proposed == values and result.receipt.outcome == "prepared"
    challenge = h.container.store.challenges[owner, result.result.challenge_id]
    assert challenge.confirmed_at is None and challenge.consumed_at is None
    assert h.container.store.events == original and dict(h.container.store.occurrences) == occurrences
    assert not h.container.store.late_reports
    confirmed = api("LateReportWrite")(
        binding=command.binding.model_copy(update={"action_key": values.id}),
        confirmed=True,
        challenge_id=challenge.id,
        occurrence_id=occurrence.id,
        values=values,
    )
    applied = port.apply(owner, confirmed)
    assert applied.result.id == values.id and applied.receipt.outcome == "applied"
    with pytest.raises(StaleVersionError):
        port.prepare(owner, command)


def test_remote_record_uses_fixed_patient_rpc_and_checks_actual_event_owner(workflow):
    import httpx
    from app.domain.errors import AuthenticationRequiredError, ProviderUnavailableError
    from app.infrastructure.enrollment_operations import InMemoryEnrollmentWritePort
    from app.infrastructure.supabase_data import SupabaseDataClient
    from app.infrastructure.workflow_repos import SupabaseWorkflowMutations

    h, owner = workflow, workflow.owner_ids["A"]
    local, command, _summary = prn_command(h)
    applied = local.apply(owner, command)
    cls = importlib.import_module("app.infrastructure.workflow_record_writes").SupabaseRecordWorkflowWrites
    for wrong_owner in (False, True):
        actual = applied
        if wrong_owner:
            event = applied.result.event.model_copy(update={"patient_id": h.owner_ids["B"]})
            actual = applied.model_copy(update={"result": applied.result.model_copy(update={"event": event})})
        calls = []

        def respond(request, calls=calls, actual=actual):
            calls.append((request.method, request.url.path))
            return httpx.Response(
                200, json=[] if request.method == "GET" else {"result": actual.model_dump(mode="json")}
            )

        data = SupabaseDataClient(
            base_url="https://example.invalid",
            publishable_key="sb_publishable_DEMO",
            access_token="DEMO-token",
            patient_id=owner,
            client=httpx.Client(transport=httpx.MockTransport(respond)),
        )
        remote = cls(
            data=data, reads=InMemoryEnrollmentWritePort(h.container.store), receipts=SupabaseWorkflowMutations(data)
        )
        if wrong_owner:
            with pytest.raises(ProviderUnavailableError):
                remote.apply(owner, command)
        else:
            assert remote.apply(owner, command) == applied
        assert calls == [
            ("GET", "/rest/v1/assistant_business_receipts"),
            ("POST", "/rest/v1/rpc/assistant_record_write"),
        ]
        calls.clear()
        with pytest.raises(AuthenticationRequiredError):
            remote.apply(h.owner_ids["B"], command)
        assert calls == []


def test_remote_record_response_loss_only_reads_the_applied_native_record(workflow):
    import httpx
    from app.infrastructure.enrollment_operations import InMemoryEnrollmentWritePort
    from app.infrastructure.supabase_data import SupabaseDataClient
    from app.infrastructure.workflow_repos import SupabaseWorkflowMutations

    h, owner = workflow, workflow.owner_ids["A"]
    local, command, _summary = prn_command(h)
    local.apply(owner, command)
    applied = local.apply(owner, command)
    calls = []

    def respond(request):
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json=[applied.receipt.model_dump(mode="json")])
        assert request.url.path == "/rest/v1/rpc/assistant_record_read"
        return httpx.Response(200, json={"result": applied.model_dump(mode="json"), "replayed": True})

    data = SupabaseDataClient(
        base_url="https://example.invalid",
        publishable_key="sb_publishable_DEMO",
        access_token="DEMO-token",
        patient_id=owner,
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    cls = importlib.import_module("app.infrastructure.workflow_record_writes").SupabaseRecordWorkflowWrites
    remote = cls(
        data=data, reads=InMemoryEnrollmentWritePort(h.container.store), receipts=SupabaseWorkflowMutations(data)
    )
    before = h.snapshot()
    assert remote.apply(owner, command).receipt == applied.receipt and h.snapshot() == before
    assert len(calls) == 2


def test_record_sql_candidate_source_inventory_is_closed_and_complete():
    """Source inventory only; real SQL/ACL/concurrency acceptance remains gated."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "supabase/review/assistant_workflows"
    up, down = root / "records.up.sql", root / "records.down.sql"
    assert up.is_file() and down.is_file(), "Record SQL review pair is missing"
    sql = up.read_text(encoding="utf-8")
    for name in (
        "assistant_record_write",
        "assistant_record_prepare",
        "assistant_record_read",
        "assistant_record_commands",
        "assistant_business_receipts",
        "assistant_run_assert_current",
        "record_confirmed_self_report",
        "record_late_dose_report",
        "assistant_record_assert_current",
    ):
        assert name in sql
    assert sql.rstrip().endswith("COMMIT;") and down.read_text(encoding="utf-8").rstrip().endswith("COMMIT;")
    assert "TO assistant_evidence_login" not in sql and "DELETE FROM storage.objects" not in sql


@pytest.mark.parametrize(("elapsed_hours", "offset_hours"), [(6.75, -4), (7.75, -5)])
def test_scheduled_report_preserves_the_existing_occurrence_across_dst_fold(workflow, elapsed_hours, offset_hours):
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    from .test_workflow_medication_management import active_plan

    h, owner = workflow, workflow.owner_ids["A"]
    plan = active_plan(h)
    h.clock.advance(days=18, hours=23)
    h._request("PUT", "/api/me/preferences", json={"timezone": "America/New_York"})
    h.container.schedule.materialize(patient_id=owner, regimen_id=UUID(plan["regimen_id"]), days=1)
    h.clock.advance(hours=elapsed_hours + 1)
    existing = h.container.schedule.existing_occurrences(
        owner, UUID(plan["regimen_id"]), h.clock.now() - timedelta(days=1), h.clock.now()
    )
    assert existing
    occurrence = existing[0]
    before = dict(h.container.store.occurrences)
    view = prepared(h, plan, "dose.report")
    port = harness(h)
    session = h.container.orchestrator.start_session(patient_id=owner)
    session = h.container.orchestrator.await_confirmation(patient_id=owner, session_id=session.id)
    operation = uuid4()
    b = binding(h, port, view, uuid4(), BusinessRef(kind="regimen", id=UUID(plan["regimen_id"]), version=1))
    ready = port.prepare(
        owner,
        api("PrepareDoseReport")(
            binding=b,
            session_id=session.id,
            session_state_version=session.state_version,
            operation_key=operation,
            intake_status="reported_taken",
            occurrence_id=occurrence.id,
        ),
    )
    assert ready.result.summary.local_timezone == "America/New_York"
    result = port.apply(
        owner,
        api("DoseReportWrite")(
            binding=b.model_copy(update={"action_key": operation}),
            confirmed=True,
            challenge_id=ready.result.challenge.id,
            values=DoseEventInput(
                regimen_id=UUID(plan["regimen_id"]),
                occurrence_id=occurrence.id,
                intake_status="reported_taken",
                event_time=h.clock.now(),
                idempotency_key="report-" + str(operation),
            ),
        ),
    )
    assert set(h.container.store.occurrences) == set(before)
    assert h.container.schedule.get_occurrence(owner, occurrence.id).due_at == occurrence.due_at
    actual = result.result.event.event_time.astimezone(ZoneInfo("America/New_York"))
    assert actual.strftime("%Y-%m-%d %H:%M") == "2026-11-01 01:45"
    assert actual.utcoffset() == timedelta(hours=offset_hours)


def test_registry_prepares_through_typed_record_boundary_without_a_context_callback(workflow):
    from dataclasses import replace

    from app.agent.registry import ToolRegistry
    from app.agent.tools import RecordSelfReportRequest
    from app.application.workflow_message_policy import MessagePersistencePolicy
    from app.contracts.workflow_messages import ConversationWriteScope
    from app.domain.errors import ProviderUnavailableError

    h, owner = workflow, workflow.owner_ids["A"]
    plan = prn_plan(h)
    view = prepared(h, plan)
    port = harness(h)
    session = h.container.orchestrator.start_session(patient_id=owner)
    session = h.container.orchestrator.await_confirmation(patient_id=owner, session_id=session.id)

    class NoConversationMedicalWrite:
        def execute(self, *args, **kwargs):
            raise AssertionError("Conversation persistence cannot publish a native confirmation")

    def no_callback(*args):
        raise AssertionError("Typed preparation cannot execute a generic context callback")

    policy = MessagePersistencePolicy(
        messages=NoConversationMedicalWrite(),
        guard=no_callback,
        scope=ConversationWriteScope(task_id=UUID(view["task_id"]), revision=view["revision"]),
    )
    old = h.container.orchestrator._registry
    registry = ToolRegistry(
        enrollment=h.container.enrollment,
        schedule=h.container.schedule,
        self_report=h.container.self_report,
        traces=old._traces,
        clock=h.clock,
        ids=h.container.ids,
        records=port,
        workflow_tasks=h.container.assistant_workflows._repository,
    )
    request = RecordSelfReportRequest(
        patient_id=owner,
        session_id=session.id,
        correlation_id=uuid4(),
        client_turn_id="DEMO typed report",
        regimen_id=UUID(plan["regimen_id"]),
        intake_status="taken",
        idempotency_key="report-" + str(uuid4()),
    )
    result = registry.prepare_self_report_confirmation(
        request, session_state_version=session.state_version, persistence=policy
    )
    assert (
        result.challenge.confirmed_at is None and result.challenge.patient_id == owner and not h.container.store.events
    )
    assert h.container.store.challenges[owner, result.challenge.id] == result.challenge
    before = h.snapshot()
    assert (
        registry.prepare_self_report_confirmation(
            request, session_state_version=session.state_version, persistence=replace(policy, save_context=False)
        )
        is None
    )
    with pytest.raises(ProviderUnavailableError):
        registry.prepare_self_report_confirmation(
            request,
            session_state_version=session.state_version,
            persistence=replace(policy, scope=ConversationWriteScope()),
        )
    assert h.snapshot() == before


def test_run_expiry_during_native_record_restores_confirmation_and_event(workflow,monkeypatch):
    from app.contracts.workflow_persistence import RunWriteBinding
    from app.infrastructure.durable_agent_runs import MemoryDurableRunControl

    from .test_durable_agent_runs import claimed

    h,owner=workflow,workflow.owner_ids['A']
    port,command,_summary=prn_command(h)
    state=h.container.assistant_workflows._repository._state
    run=claimed(MemoryDurableRunControl(clock=h.clock,state=state),owner)
    command=command.model_copy(update={'binding':command.binding.model_copy(update={
        'run_binding':RunWriteBinding(run_id=run.run_id,epoch=run.epoch)})})
    native_report=h.container.self_report.report
    def slow_report(*args,**kwargs):
        result=native_report(*args,**kwargs)
        h.clock.advance(seconds=46)
        return result
    monkeypatch.setattr(h.container.self_report,'report',slow_report)
    before=h.snapshot()
    with pytest.raises(StaleVersionError):
        port.apply(owner,command)
    assert h.snapshot()==before and port.lookup(owner,command.binding.action_key) is None
