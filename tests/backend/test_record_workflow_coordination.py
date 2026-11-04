"""DEMO_ONLY actual patient record HTTP bridges, with no live database or provider."""

import importlib
from uuid import UUID

import pytest

from .test_persistent_record_transactions import harness
from .test_workflow_late_reports import body, existing_occurrence, path
from .test_workflow_medication_management import active_plan
from .test_workflow_report_bindings import choice, headers, prn_plan

CAPS = ("dose.report", "dose.prn.report", "dose.late.review", "dose.correction.review")


def wire(h):
    from app.infrastructure.memory_workflows import MemoryWorkflowMutations

    cls = importlib.import_module("app.application.workflow_record_transactions").RecordWorkflowTransactions
    w = h.container.assistant_workflows
    port = harness(h)
    coordinator = cls(
        writes=port,
        tasks=w._repository,
        receipts=MemoryWorkflowMutations(h.clock, state=w._repository._state),
        adapters={cap: w._adapters[cap] for cap in CAPS},
        preferences=h.container.preferences,
        reports=h.container.self_report,
        late_reports=h.container.late_reports,
        orchestrator=h.container.orchestrator,
    )
    w._business_transactions = dict.fromkeys(coordinator.capability_ids, coordinator)
    h.container.assistant_reports.transactions = coordinator
    h.container.assistant_late_reports.transactions = coordinator
    return coordinator, port


def selected(h, capability):
    if capability in {"dose.report", "dose.prn.report"}:
        plan = prn_plan(h) if capability == "dose.prn.report" else active_plan(h)
        occurrence = None
        if capability == "dose.report":
            h.container.schedule.materialize(patient_id=h.owner_ids["A"], regimen_id=UUID(plan["regimen_id"]), days=1)
            h.clock.advance(hours=13)
            occurrence = h._request("GET", "/api/doses/due", params={"regimen_id": plan["regimen_id"]})["occurrence_id"]
            assert occurrence
        return (
            {"regimen_id": plan["regimen_id"], "expected_version": 1},
            ("/api/prn/report" if occurrence is None else f"/api/doses/{occurrence}/report"),
            choice(plan),
        )
    occurrence = existing_occurrence(h)
    previous = None
    if capability == "dose.correction.review":
        original = body()
        summary = h._request("POST", path(occurrence) + "/challenge", json=original)
        previous = h._request(
            "POST", path(occurrence), json={"report": original, "challenge_id": summary["challenge_id"]}
        )["id"]
    values = body(previous)
    if previous:
        values.update(intake_status="unsure", reason="correcting_record")
    return (
        {"occurrence_id": str(occurrence.id), "expected_version": 2 if previous else 1, "expected_report_id": previous},
        path(occurrence),
        values,
    )


@pytest.mark.parametrize("capability", CAPS)
def test_typed_patient_report_prepares_target_then_summary_then_atomic_confirmation(workflow, monkeypatch, capability):
    h, owner = workflow, workflow.owner_ids["A"]
    fields, endpoint, values = selected(h, capability)
    _, port = wire(h)
    w = h.container.assistant_workflows
    before_events = dict(h.container.store.events)
    before_occurrences = dict(h.container.store.occurrences.rows)
    before_challenges = dict(h.container.store.challenges.rows)
    task = h.start(capability, fields)
    cas = w._repository.cas
    changes = []

    def counted(*args, **kwargs):
        changes.append(args)
        return cas(*args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("Typed record coordination cannot execute generic business callbacks")

    monkeypatch.setattr(w._repository, "cas", counted)
    monkeypatch.setattr(w._controls, "guarded_write", forbidden)
    review = h.event(task["task_id"], "prepare_confirmation")
    assert review["state"] == "awaiting_confirmation" and review["revision"] == task["revision"] + 1
    assert len(changes) == 1 and h.container.store.events == before_events
    assert h.container.store.challenges.rows == before_challenges
    assert port.review(owner, UUID(task["task_id"]), review["revision"]).outcome == "prepared"
    summary = h._request("POST", endpoint + "/challenge", json=values, headers=headers(review))
    repeated_summary = h._request("POST", endpoint + "/challenge", json=values, headers=headers(review))
    assert repeated_summary["challenge_id"] == summary["challenge_id"] and len(changes) == 1
    payload = ({"report": values} if capability in CAPS[2:] else values) | {"challenge_id": summary["challenge_id"]}
    saved = h._request("POST", endpoint, json=payload, headers=headers(review))
    retry = h._request("POST", endpoint, json=payload, headers=headers(review))
    assert retry.get("event_id", retry.get("id")) == saved.get("event_id", saved.get("id"))
    assert len(changes) == 2 and saved["ingestion_proven"] is False
    monkeypatch.setattr(port, "apply", forbidden)
    done = h.event(task["task_id"], "report_business_result")
    assert done["state"] == "completed" and done["revision"] == review["revision"] + 1
    assert done["visible_fields"]["ingestion_proven"] is False and len(changes) == 2
    assert "DEMO synthetic patient report" not in str(w._repository._state.business_receipts)
    if capability in CAPS[2:]:
        assert h.container.store.events == before_events
        # The existing native patient report closes an occurrence; its identity,
        # rule, scheduled instant and generation must remain unchanged.
        assert {k: v.model_dump(exclude={"status"}) for k, v in h.container.store.occurrences.rows.items()} == {
            k: v.model_dump(exclude={"status"}) for k, v in before_occurrences.items()
        }


@pytest.mark.parametrize("guard", ["pause", "revoke", "target", "choice", "challenge"])
def test_typed_report_rejects_changed_patient_authority_without_new_event(workflow, guard):
    from uuid import uuid4

    h = workflow
    fields, endpoint, values = selected(h, "dose.prn.report")
    wire(h)
    task = h.start("dose.prn.report", fields)
    review = h.event(task["task_id"], "prepare_confirmation")
    summary = h._request("POST", endpoint + "/challenge", json=values, headers=headers(review))
    payload = values | {"challenge_id": summary["challenge_id"]}
    if guard == "pause":
        h.event(task["task_id"], "pause")
    elif guard == "revoke":
        h.event(task["task_id"], "cancel_save")
    elif guard == "target":
        payload["regimen_id"] = str(uuid4())
    elif guard == "choice":
        payload["intake_status"] = "unsure"
    else:
        payload["challenge_id"] = str(uuid4())
    denied = h.client.post(endpoint, params={"client_id": "DEMO-workflow-A"}, json=payload, headers=headers(review))
    assert denied.status_code in {404, 409, 422}, denied.text
    assert not h.container.store.events


def test_remote_record_results_use_only_owned_fixed_reads(workflow):
    import json

    import httpx
    from app.domain.errors import AuthenticationRequiredError, NotFoundError, ProviderUnavailableError
    from app.infrastructure.supabase_data import SupabaseDataClient
    from app.infrastructure.workflow_record_writes import SupabaseRecordWorkflowWrites

    h, owner = workflow, workflow.owner_ids["A"]
    fields, endpoint, values = selected(h, "dose.prn.report")
    _, port = wire(h)
    view = h.start("dose.prn.report", fields)
    view = h.event(view["task_id"], "prepare_confirmation")
    review = port.review(owner, UUID(view["task_id"]), view["revision"])
    summary = h._request("POST", endpoint + "/challenge", json=values, headers=headers(view))
    h._request("POST", endpoint, json=values | {"challenge_id": summary["challenge_id"]}, headers=headers(view))
    receipt = next(
        r
        for r in h.container.assistant_workflows._repository._state.business_receipts.values()
        if r.task_id == UUID(view["task_id"]) and r.outcome == "applied"
    )
    actual = port.read_result(owner, receipt)
    calls = []
    wrong_target = False

    def respond(request):
        calls.append((request.url.path, json.loads(request.content)))
        if wrong_target and request.url.path.endswith("assistant_record_result"):
            changed = actual.model_dump(mode="json")
            changed["result"]["event"]["regimen_id"] = str(UUID(int=999))
            return httpx.Response(200, json={"result": changed})
        return httpx.Response(
            200,
            json={
                "result": (review if request.url.path.endswith("review_receipt") else actual).model_dump(mode="json")
            },
        )

    data = SupabaseDataClient(
        base_url="https://example.invalid",
        publishable_key="sb_publishable_DEMO",
        access_token="DEMO-token",
        patient_id=owner,
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )

    class Receipts:
        def read_receipt(self, patient, key):
            assert patient == owner
            return receipt if key == receipt.action_key else None

    remote = SupabaseRecordWorkflowWrites(data=data, reads=None, receipts=Receipts())
    assert remote.review(owner, review.task_id, review.binding_revision) == review
    assert remote.read_result(owner, receipt) == actual
    assert [p for p, _ in calls] == [
        "/rest/v1/rpc/assistant_record_review_receipt",
        "/rest/v1/rpc/assistant_record_review_receipt",
        "/rest/v1/rpc/assistant_record_result",
    ]
    with pytest.raises(AuthenticationRequiredError):
        remote.read_result(UUID(int=999), receipt)
    with pytest.raises(NotFoundError):
        remote.read_result(owner, review)
    assert len(calls) == 3
    wrong_target = True
    with pytest.raises(ProviderUnavailableError):
        remote.read_result(owner, receipt)


def test_record_source_candidates_cover_target_preparation_and_receipt_only_read():
    from pathlib import Path

    sql = Path("supabase/review/assistant_workflows/records.up.sql").read_text(encoding="utf-8")
    assert "WHEN 'prepare_review' THEN ARRAY['kind','binding']" in sql
    assert "CREATE FUNCTION public.assistant_record_review_receipt" in sql
    assert "CREATE FUNCTION public.assistant_record_result" in sql


def test_run_expiring_during_target_publication_rolls_back_selection(workflow, monkeypatch):
    from uuid import uuid4

    from app.contracts.assistant_workflows import BusinessRef
    from app.contracts.workflow_persistence import RunWriteBinding, WorkflowWriteBinding
    from app.contracts.workflow_record_writes import PrepareRecordReview
    from app.domain.errors import StaleVersionError
    from app.infrastructure.durable_agent_runs import MemoryDurableRunControl

    from .test_durable_agent_runs import claimed

    h, owner = workflow, workflow.owner_ids["A"]
    fields, _, _ = selected(h, "dose.prn.report")
    _, port = wire(h)
    view = h.start("dose.prn.report", fields)
    w = h.container.assistant_workflows
    before = w._repository.get(owner, UUID(view["task_id"]))
    run = claimed(MemoryDurableRunControl(clock=h.clock, state=w._repository._state), owner)
    b = WorkflowWriteBinding(
        task_id=before.id,
        task_revision=before.revision,
        capability_id=before.capability_id,
        action_key=uuid4(),
        prepared_ref=BusinessRef(kind="regimen", id=UUID(fields["regimen_id"]), version=1),
        expected_domain_revision=port.revision(owner),
        run_binding=RunWriteBinding(run_id=run.run_id, epoch=run.epoch),
    )
    cas = w._repository.cas

    def expire(*args, **kwargs):
        result = cas(*args, **kwargs)
        h.clock.advance(seconds=46)
        return result

    monkeypatch.setattr(w._repository, "cas", expire)
    with pytest.raises(StaleVersionError):
        port.prepare(owner, PrepareRecordReview(binding=b))
    assert w._repository.get(owner, before.id) == before and port.lookup(owner, b.action_key) is None


def test_native_event_dto_keeps_the_patient_http_response_contract(workflow, monkeypatch):
    from app.contracts.workflow_persistence import NativeWriteResult

    h = workflow
    fields, endpoint, values = selected(h, "dose.prn.report")
    _, port = wire(h)
    task = h.start("dose.prn.report", fields)
    review = h.event(task["task_id"], "prepare_confirmation")
    summary = h._request("POST", endpoint + "/challenge", json=values, headers=headers(review))
    apply = port.apply

    def native_event(*args, **kwargs):
        result = apply(*args, **kwargs)
        return NativeWriteResult(receipt=result.receipt, result=result.result.event)

    monkeypatch.setattr(port, "apply", native_event)
    payload = values | {"challenge_id": summary["challenge_id"]}
    first = h._request("POST", endpoint, json=payload, headers=headers(review))
    second = h._request("POST", endpoint, json=payload, headers=headers(review))
    assert first["event_id"] == second["event_id"] and not first["already_recorded"] and second["already_recorded"]
