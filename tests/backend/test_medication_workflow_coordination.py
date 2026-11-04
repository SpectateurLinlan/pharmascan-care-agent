"""DEMO_ONLY native enrollment HTTP coordination, without live SQL or providers."""

import importlib
from uuid import UUID, uuid4

import pytest

from .test_persistent_medication_transactions import harness
from .test_workflow_enrollment_operations import ready


def wire(h, *, recovery=False):
    from app.application.assistant_capabilities.enrollment import EnrollmentAdapter
    from app.application.enrollment_operations import EnrollmentOperationService
    from app.infrastructure.enrollment_operations import InMemoryEnrollmentWritePort
    from app.infrastructure.memory_repos import InMemoryConfirmationChallengeRepository
    from app.infrastructure.memory_workflows import MemoryWorkflowMutations
    from app.infrastructure.workflow_medication_writes import CoupledEnrollmentWritePort

    cls = importlib.import_module("app.application.workflow_medication_transactions").MedicationWorkflowTransactions
    w = h.container.assistant_workflows
    writes = harness(h)
    native = InMemoryEnrollmentWritePort(h.container.store)
    coupled = CoupledEnrollmentWritePort(native=native, writes=writes, tasks=w._repository)
    adapter = EnrollmentAdapter(
        h.container.enrollment,
        EnrollmentOperationService(h.container.enrollment, coupled),
        h.container.assistant_attachments,
    )
    preparers = {"medication.enroll": adapter}
    if recovery:
        from app.application.assistant_capabilities.draft_recovery import DraftRecoveryAdapter
        from app.application.assistant_capabilities.plan_changes import PlanChangeAdapter
        from app.infrastructure.clinical_memory import MemoryClinicalMutationGuard

        operations = EnrollmentOperationService(h.container.enrollment, coupled)
        preparers["medication.plan.change"] = PlanChangeAdapter(
            h.container.enrollment, operations, adapter, w._repository
        )
        preparers["medication.draft.resume"] = DraftRecoveryAdapter(
            h.container.enrollment,
            operations,
            adapter,
            w._repository,
            w._controls,
            MemoryClinicalMutationGuard(h.container.store.clinical),
            plan_change_enabled=True,
        )
    coordinator = cls(
        writes=writes,
        bindings=native,
        tasks=w._repository,
        receipts=MemoryWorkflowMutations(h.clock, state=w._repository._state),
        adapter=adapter,
        attachments=h.container.assistant_attachments,
        enrollment=h.container.enrollment,
        challenges=InMemoryConfirmationChallengeRepository(h.container.store),
        orchestrator=h.container.orchestrator,
        preferences=h.container.preferences,
        clock=h.clock,
        preparers=preparers,
        maintenance=w._adapters["medication.plan.end"] if recovery else None,
        deletion=h.container.draft_deletion if recovery else None,
        source_adapter=w._adapters["medication.source.add"] if recovery else None,
    )
    w._adapters.update(preparers)
    w._writers.update(preparers)
    w._business_transactions = dict.fromkeys(coordinator.capability_ids, coordinator)
    h.container.assistant_medications = coordinator
    return coordinator, writes


@pytest.mark.parametrize("capability", ["medication.plan.change", "medication.draft.resume"])
def test_plan_change_and_existing_draft_use_atomic_preparation_and_patient_activation(workflow, capability):
    from .test_workflow_medication_management import active_plan

    h = workflow
    old = active_plan(h) if capability.endswith("change") else h.seed_reviewed_medication()
    wire(h, recovery=True)
    fields = {"regimen_id": old["regimen_id"], "expected_version": 1}
    if capability.endswith("change"):
        fields.update(expected_state="active", details={"frequency_rule": {"kind": "daily", "local_times": ["21:00"]}})
    task = h.start(capability, fields)
    prepared = h.event(task["task_id"], "prepare_confirmation")
    assert prepared["state"] == "awaiting_confirmation"
    row = h.container.enrollment.get_regimen(h.owner_ids["A"], UUID(prepared["result_ref"]["id"]))
    if capability.endswith("change"):
        assert row.supersedes_id == UUID(old["regimen_id"]) and row.state.value == "draft"
        assert h.container.enrollment.get_regimen(h.owner_ids["A"], UUID(old["regimen_id"])).state.value == "active"
        assert review_source(h, prepared).status_code == 200
    else:
        assert str(row.id) == old["regimen_id"]
    session = h._request("POST", "/api/demo/start", json={"client_id": "DEMO-workflow-A"})["session_id"]
    result = summary(h, prepared, session)
    assert result.status_code == 200, result.text
    assert activate(h, prepared, result.json()).status_code == 200
    assert h.view(task["task_id"])["state"] == "completed"


@pytest.mark.parametrize("capability", ["medication.plan.end", "medication.draft.delete"])
def test_typed_maintenance_confirms_actual_owned_target_once(workflow, monkeypatch, capability):
    from .test_workflow_medication_management import active_plan

    h = workflow
    old = active_plan(h) if capability.endswith("end") else h.seed_reviewed_medication()
    wire(h, recovery=True)
    fields = (
        {"regimen_id": old["regimen_id"], "expected_version": 1}
        if capability.endswith("end")
        else {"kind": "draft", "target_id": old["regimen_id"], "expected_version": 1}
    )
    task = h.start(capability, fields)
    prepared = h.event(task["task_id"], "prepare_confirmation")
    monkeypatch.setattr(
        h.container.assistant_workflows,
        "guarded_patient_action",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("No outer callback")),
    )
    endpoint = (
        f"/api/medications/{old['regimen_id']}/end"
        if capability.endswith("end")
        else f"/api/medications/unfinished/draft/{old['regimen_id']}"
    )
    method = "POST" if capability.endswith("end") else "DELETE"
    kwargs = {
        "params": {"client_id": "DEMO-workflow-A"},
        "json": {"confirmed": True},
        "headers": {
            "X-Assistant-Task": task["task_id"],
            "X-Assistant-Revision": str(prepared["revision"]),
        },
    }
    first = h.client.request(method, endpoint, **kwargs)
    assert first.status_code == 200, first.text
    assert h.client.request(method, endpoint, **kwargs).json() == first.json()
    assert h.view(task["task_id"])["state"] == "completed"


def test_source_add_saves_original_then_reviews_and_activates_without_outer_callback(monkeypatch):
    from uuid import uuid5

    from app.application.workflow_verification import WorkflowVerificationService
    from app.infrastructure.verified_original_repos import MemoryStorageVerifier, MemoryVerifiedOriginals

    from .test_workflow_originals import original_png
    from .test_workflow_photo_enrollment import label
    from .workflow_support import WorkflowHarness

    with WorkflowHarness(source_results=[label()]) as h:
        wire(h, recovery=True)
        attachments = h.container.assistant_attachments
        state = attachments._repository._state
        raw = MemoryVerifiedOriginals(
            state=state,
            clock=h.clock,
            originals=attachments._repository,
            controls=attachments._controls,
            cleanup=h.container.assistant_cleanup._repository,
        )
        attachments._verification = WorkflowVerificationService(
            repository=raw,
            storage=attachments._storage,
            verifier=MemoryStorageVerifier(state=state, clock=h.clock),
            clock=h.clock,
        )
        task = h.start("medication.source.add", {})
        uploaded = h.upload(task["task_id"], original_png())
        current = h.event(task["task_id"], "prepare_confirmation")
        target = str(uuid5(UUID(task["task_id"]), "source-registration"))
        headers = {"X-Assistant-Task": task["task_id"], "X-Assistant-Revision": str(current["revision"])}
        payload = {"attachment_id": uploaded["attachment"]["id"], "confirmed": True}
        saved = h.client.post(
            f"/api/evidence/tasks/{target}/saved-original",
            params={"client_id": "DEMO-workflow-A"},
            headers=headers,
            json=payload,
        )
        assert saved.status_code == 200, saved.text
        assert (
            h.client.post(
                f"/api/evidence/tasks/{target}/saved-original",
                params={"client_id": "DEMO-workflow-A"},
                headers=headers,
                json=payload,
            ).json()
            == saved.json()
        )
        current = h.view(task["task_id"])
        review_payload = {
            "draft": {
                "medication_name": saved.json()["product"]["name"],
                "dose_amount": 1,
                "dose_unit": "tablet",
                "frequency_rule": {"kind": "daily", "local_times": ["08:00", "20:00"]},
            },
            "patient_reviewed": True,
        }
        headers["X-Assistant-Revision"] = str(current["revision"])
        reviewed = h.client.post(
            f"/api/evidence/tasks/{target}/review",
            params={"client_id": "DEMO-workflow-A"},
            headers=headers,
            json=review_payload,
        )
        assert reviewed.status_code == 200, reviewed.text
        prepared = h.view(task["task_id"])
        assert prepared["result_ref"]["kind"] == "regimen"
        session = h._request("POST", "/api/demo/start", json={"client_id": "DEMO-workflow-A"})["session_id"]
        assert activate(h, prepared, summary(h, prepared, session).json()).status_code == 200
        assert h.view(task["task_id"])["state"] == "completed"
        assert h.read_original(uploaded["attachment"]["id"]) == original_png()


def test_owned_unbound_source_review_uses_the_typed_existing_registration(workflow, monkeypatch):
    from .test_workflow_sources import inputs, provider

    h = workflow
    provider(h, monkeypatch)
    source = h.container.evidence_enrollment.attach(**inputs(h))
    wire(h, recovery=True)
    task = h.start("medication.source.review", {"source_task_id": str(source.id), "expected_version": source.version})
    current = h.event(task["task_id"], "prepare_confirmation")
    from types import SimpleNamespace

    from .test_workflow_source_transport import source_review

    result = source_review(h, SimpleNamespace(task_id=UUID(task["task_id"]), revision=current["revision"]), source)
    assert result.status_code == 200, result.text
    prepared = h.view(task["task_id"])
    session = h._request("POST", "/api/demo/start", json={"client_id": "DEMO-workflow-A"})["session_id"]
    assert activate(h, prepared, summary(h, prepared, session).json()).status_code == 200
    assert h.view(task["task_id"])["state"] == "completed"


def review_source(h, task):
    regimen = h.container.enrollment.get_regimen(h.owner_ids["A"], UUID(task["result_ref"]["id"]))
    return h.client.post(
        f"/api/medications/drafts/{regimen.source_id}/review",
        params={"client_id": "DEMO-workflow-A"},
        json={"field_ids": None},
    )


def summary(h, task, session):
    return h.client.post(
        f"/api/medications/drafts/{task['result_ref']['id']}/challenge",
        params={"client_id": "DEMO-workflow-A", "session_id": session},
        json={},
    )


def activate(h, task, challenge, **changes):
    return h.client.post(
        "/api/medications/activate",
        params={"client_id": "DEMO-workflow-A"},
        json={
            "regimen_id": task["result_ref"]["id"],
            **{key: challenge[key] for key in ("challenge_id", "session_id", "session_state", "session_state_version")},
            **changes,
        },
    )


def test_enrollment_preparation_review_and_activation_each_publish_one_actual_transaction(workflow, monkeypatch):
    h, owner = workflow, workflow.owner_ids["A"]
    _, port = wire(h)
    task = ready(h)
    w = h.container.assistant_workflows
    cas = w._repository.cas
    changes = []

    def counted(*args, **kwargs):
        changes.append(args)
        return cas(*args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("Outer WorkflowService must not wrap or advance an already atomic medication command")

    monkeypatch.setattr(w._repository, "cas", counted)
    monkeypatch.setattr(w, "guarded_patient_action", forbidden)
    event = str(uuid4())
    prepared = h.event(task["task_id"], "prepare_confirmation", revision=task["revision"], event_id=event)
    receipt = port.lookup(owner, UUID(event))
    assert receipt.outcome == "prepared" and prepared["revision"] == task["revision"] + 1 and len(changes) == 1
    assert (
        h.event(task["task_id"], "prepare_confirmation", revision=task["revision"], event_id=event)["result_ref"]
        == prepared["result_ref"]
    )
    assert len(changes) == 1 and h.snapshot()["regimens"][0]["state"] == "draft"
    assert not h.snapshot()["dose_events"] and not h.container.store.challenges.rows
    reviewed = review_source(h, prepared)
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["reviewed_field_count"] > 0 and len(changes) == 2
    assert review_source(h, prepared).json() == reviewed.json() and len(changes) == 2
    session = h._request("POST", "/api/demo/start", json={"client_id": "DEMO-workflow-A"})["session_id"]
    challenge = summary(h, prepared, session)
    assert challenge.status_code == 200, challenge.text
    assert summary(h, prepared, session).json() == challenge.json() and len(changes) == 2
    assert h.snapshot()["regimens"][0]["state"] == "draft"
    saved = activate(h, prepared, challenge.json())
    assert saved.status_code == 200, saved.text
    assert activate(h, prepared, challenge.json()).json() == saved.json() and len(changes) == 3
    monkeypatch.setattr(port, "apply", forbidden)
    done = h.event(task["task_id"], "report_business_result")
    assert done["state"] == "completed" and done["revision"] == prepared["revision"] + 2 and len(changes) == 3
    assert h.snapshot()["regimens"][0]["state"] == "active"


@pytest.mark.parametrize("guard", ["pause", "revoke", "revision", "session", "challenge"])
def test_independent_activation_rejects_changed_authority_and_keeps_draft(workflow, guard):
    h = workflow
    wire(h)
    task = ready(h)
    prepared = h.event(task["task_id"], "prepare_confirmation")
    assert review_source(h, prepared).status_code == 200
    session = h._request("POST", "/api/demo/start", json={"client_id": "DEMO-workflow-A"})["session_id"]
    challenge = summary(h, prepared, session).json()
    changes = {}
    if guard == "pause":
        h.event(task["task_id"], "pause")
    elif guard == "revoke":
        h.event(task["task_id"], "cancel_save")
    elif guard == "revision":
        changes["session_state_version"] = challenge["session_state_version"] + 1
    elif guard == "session":
        changes["session_id"] = str(uuid4())
    else:
        changes["challenge_id"] = str(uuid4())
    denied = activate(h, prepared, challenge, **changes)
    assert denied.status_code in {404, 409, 422}, denied.text
    assert all(row["state"] == "draft" for row in h.snapshot()["regimens"])


def test_original_name_review_uses_exact_task_revision_and_preserves_other_original_fields(workflow):
    from .test_workflow_enrollment_operations import values

    h, owner = workflow, workflow.owner_ids["A"]
    old = h._request("POST", "/api/medications/drafts", json={"medication_name": values().fields.medication_name})
    wire(h)
    task = ready(h)
    task = h.event(task["task_id"], "select_candidate", {"existing_medication_id": old["medication_id"]})
    prepared = h.event(task["task_id"], "prepare_confirmation")
    assert review_source(h, prepared).status_code == 200
    task = h.view(task["task_id"])
    result = h.client.post(
        f"/api/medications/drafts/{prepared['result_ref']['id']}/identity-review",
        params={"client_id": "DEMO-workflow-A"},
        json={"confirmed": True},
        headers={"X-Assistant-Task": task["task_id"], "X-Assistant-Revision": str(task["revision"])},
    )
    assert result.status_code == 200, result.text
    assert result.json()["reviewed_name_count"] == 1
    assert h.container.enrollment.get_source(owner, UUID(old["source_id"])).reviewed_at is None


def test_photo_enrollment_preserves_exact_verified_original_through_native_activation():
    from app.application.workflow_verification import WorkflowVerificationService
    from app.infrastructure.verified_original_repos import MemoryStorageVerifier, MemoryVerifiedOriginals

    from .test_workflow_enrollment import message
    from .test_workflow_originals import original_png
    from .test_workflow_photo_enrollment import label
    from .workflow_support import WorkflowHarness

    with WorkflowHarness(source_results=[label()]) as h:
        wire(h)
        attachments = h.container.assistant_attachments
        state = attachments._repository._state
        originals = MemoryVerifiedOriginals(
            state=state,
            clock=h.clock,
            originals=attachments._repository,
            controls=attachments._controls,
            cleanup=h.container.assistant_cleanup._repository,
        )
        attachments._verification = WorkflowVerificationService(
            repository=originals,
            storage=attachments._storage,
            verifier=MemoryStorageVerifier(state=state, clock=h.clock),
            clock=h.clock,
        )
        task = h.start("medication.enroll", {"method": "photo"})
        uploaded = h.upload(task["task_id"], original_png())
        message(h, "08:00, 20:00", uploaded["workflow"])
        prepared = h.event(task["task_id"], "prepare_confirmation")
        assert review_source(h, prepared).status_code == 200
        session = h._request("POST", "/api/demo/start", json={"client_id": "DEMO-workflow-A"})["session_id"]
        challenge = summary(h, prepared, session)
        assert challenge.status_code == 200, challenge.text
        assert activate(h, prepared, challenge.json()).status_code == 200
        assert h.view(task["task_id"])["state"] == "completed"
        assert h.read_original(uploaded["attachment"]["id"]) == original_png()


def test_activation_summary_can_be_renewed_after_its_native_expiry(workflow):
    h = workflow
    wire(h)
    task = ready(h)
    prepared = h.event(task["task_id"], "prepare_confirmation")
    assert review_source(h, prepared).status_code == 200
    session = h._request("POST", "/api/demo/start", json={"client_id": "DEMO-workflow-A"})["session_id"]
    first = summary(h, prepared, session).json()
    from datetime import datetime

    expiry = datetime.fromisoformat(first["expires_at"].replace("Z", "+00:00"))
    h.clock.advance(seconds=int((expiry - h.clock.now()).total_seconds()) + 1)
    renewed = summary(h, prepared, session)
    assert renewed.status_code == 200, renewed.text
    assert renewed.json()["challenge_id"] != first["challenge_id"]


def test_absent_original_identity_review_never_claims_a_new_name_was_reviewed(workflow):
    h = workflow
    wire(h)
    task = ready(h)
    prepared = h.event(task["task_id"], "prepare_confirmation")
    assert review_source(h, prepared).status_code == 200
    current = h.view(task["task_id"])
    result = h.client.post(
        f"/api/medications/drafts/{prepared['result_ref']['id']}/identity-review",
        params={"client_id": "DEMO-workflow-A"},
        json={"confirmed": True},
        headers={"X-Assistant-Task": current["task_id"], "X-Assistant-Revision": str(current["revision"])},
    )
    assert result.status_code == 200, result.text
    assert result.json()["reviewed_name_count"] == 0
    assert h.view(task["task_id"])["revision"] == current["revision"]


def assert_expiry_rolls_back(h, port, owner, command, monkeypatch):
    from app.contracts.workflow_persistence import RunWriteBinding
    from app.domain.errors import StaleVersionError
    from app.infrastructure.durable_agent_runs import MemoryDurableRunControl

    from .test_durable_agent_runs import claimed

    w = h.container.assistant_workflows
    run = claimed(MemoryDurableRunControl(clock=h.clock, state=w._repository._state), owner)
    command = command.model_copy(
        update={
            "binding": command.binding.model_copy(
                update={
                    "run_binding": RunWriteBinding(run_id=run.run_id, epoch=run.epoch),
                }
            )
        }
    )
    cas = w._repository.cas

    def expire(*args, **kwargs):
        result = cas(*args, **kwargs)
        h.clock.advance(seconds=46)
        return result

    before = h.snapshot()
    monkeypatch.setattr(w._repository, "cas", expire)
    with pytest.raises(StaleVersionError):
        port.apply(owner, command)
    assert h.snapshot() == before and port.lookup(owner, command.binding.action_key) is None


@pytest.mark.parametrize("stage", ["prepare", "review"])
def test_run_expiring_during_enrollment_task_publication_rolls_back_native_rows(workflow, monkeypatch, stage):
    from .test_persistent_medication_transactions import native_action, prepare

    h = workflow
    port = harness(h)
    owner, command = prepare(h, port)
    if stage == "review":
        native = port.apply(owner, command).result
        command = native_action(
            h, port, owner, command, "ReviewMedicationSource", source_id=native.source_id, confirmed=True
        )
    assert_expiry_rolls_back(h, port, owner, command, monkeypatch)


def test_run_expiring_during_source_marker_publication_rolls_back_review(monkeypatch):
    from app.contracts.assistant_workflows import BusinessRef
    from app.contracts.workflow_medication_writes import PrepareSourceReview
    from app.contracts.workflow_persistence import WorkflowWriteBinding

    from .test_workflow_originals import original_png
    from .test_workflow_photo_enrollment import label
    from .workflow_support import WorkflowHarness

    with WorkflowHarness(source_results=[label()]) as h:
        first = h.start("medication.source.add", {})
        view = h.upload(first["task_id"], original_png())["workflow"]
        port, owner = harness(h), h.owner_ids["A"]
        command = PrepareSourceReview(
            binding=WorkflowWriteBinding(
                task_id=UUID(view["task_id"]),
                task_revision=view["revision"],
                capability_id=view["capability_id"],
                action_key=uuid4(),
                expected_domain_revision=port.revision(owner),
                prepared_ref=BusinessRef(kind="media_review", id=UUID(view["task_id"]), version=view["revision"] + 1),
            )
        )
        assert_expiry_rolls_back(h, port, owner, command, monkeypatch)


def test_direct_bound_enrollment_cannot_drop_a_missing_durable_run_binding(workflow):
    from types import SimpleNamespace

    from app.application.enrollment_operations import EnrollmentOperationService
    from app.contracts.agent_execution import current_execution
    from app.domain.errors import ProviderUnavailableError
    from app.infrastructure.enrollment_operations import InMemoryEnrollmentWritePort
    from app.infrastructure.workflow_medication_writes import CoupledEnrollmentWritePort

    from .test_workflow_enrollment_operations import values

    h, owner = workflow, workflow.owner_ids["A"]
    task = ready(h)
    w = h.container.assistant_workflows
    port = harness(h)
    writer = CoupledEnrollmentWritePort(
        native=InMemoryEnrollmentWritePort(h.container.store), writes=port, tasks=w._repository
    )
    service = EnrollmentOperationService(h.container.enrollment, writer)
    request = values().model_copy(
        update={"workflow_task_id": UUID(task["task_id"]), "workflow_revision": task["revision"]}
    )
    token = current_execution.set(SimpleNamespace(check=lambda: None, write_binding=None))
    try:
        with pytest.raises(ProviderUnavailableError):
            service.prepare_once(owner, request)
    finally:
        current_execution.reset(token)
    assert not h.snapshot()["regimens"] and port.lookup(owner, request.action_key) is None


def test_completed_enrollment_preserves_actual_receipt_when_native_read_is_unavailable(workflow, monkeypatch):
    from app.domain.errors import ProviderUnavailableError

    h = workflow
    _, port = wire(h)
    task = ready(h)
    prepared = h.event(task["task_id"], "prepare_confirmation")
    assert review_source(h, prepared).status_code == 200
    session = h._request("POST", "/api/demo/start", json={"client_id": "DEMO-workflow-A"})["session_id"]
    assert activate(h, prepared, summary(h, prepared, session).json()).status_code == 200
    before = dict(h.container.assistant_workflows._repository._state.business_receipts)

    def unavailable(*args, **kwargs):
        raise ProviderUnavailableError("DEMO native read unavailable")

    monkeypatch.setattr(h.container.enrollment, "get_regimen", unavailable)
    monkeypatch.setattr(port, "apply", unavailable)
    current = h.view(task["task_id"])
    assert current["state"] == "completed" and current["visible_fields"]["actual_result_available"] is False
    assert h.container.assistant_workflows._repository._state.business_receipts == before


def test_native_plan_changed_elsewhere_does_not_invent_a_workflow_completion(workflow):
    from .test_workflow_medication_management import active_plan

    h = workflow
    old = active_plan(h)
    wire(h, recovery=True)
    task = h.start("medication.plan.end", {"regimen_id": old["regimen_id"], "expected_version": 1})
    h.event(task["task_id"], "prepare_confirmation")
    h.container.enrollment.end_regimen(patient_id=h.owner_ids["A"], regimen_id=UUID(old["regimen_id"]))
    current = h.view(task["task_id"])
    assert current["state"] == "outcome_unknown"
    assert current["visible_fields"]["actual_result_available"] is False


def test_native_draft_with_pending_file_cleanup_does_not_publish_completed(workflow, monkeypatch):
    h = workflow
    old = h.seed_reviewed_medication()
    _, port = wire(h, recovery=True)
    task = h.start("medication.draft.delete", {"kind": "draft", "target_id": old["regimen_id"], "expected_version": 1})
    prepared = h.event(task["task_id"], "prepare_confirmation")
    delete = port._deletions.delete_metadata

    def pending(owner, kind, target):
        result = delete(owner, kind, target)
        h.container.store.draft_deletions[(owner, kind, target)]["paths"] = ["DEMO_ONLY-unverified-native-object"]
        return result.model_copy(update={"cleanup_pending": True})

    monkeypatch.setattr(port._deletions, "delete_metadata", pending)
    response = h.client.request(
        "DELETE",
        f"/api/medications/unfinished/draft/{old['regimen_id']}",
        params={"client_id": "DEMO-workflow-A"},
        json={"confirmed": True},
        headers={"X-Assistant-Task": task["task_id"], "X-Assistant-Revision": str(prepared["revision"])},
    )
    assert response.status_code == 200, response.text
    assert response.json()["cleanup_pending"] is True
    assert h.view(task["task_id"])["cleanup_pending"] is True
    assert h.container.assistant_workflows._repository.get(h.owner_ids["A"], UUID(task["task_id"])).state != "completed"
