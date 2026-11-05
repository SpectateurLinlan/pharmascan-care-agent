"""DEMO_ONLY request composition and real patient HTTP transaction integration."""

import importlib
from uuid import UUID

import pytest

from .test_persistent_settings_transactions import harness
from .test_workflow_contacts import details
from .test_workflow_preferences import CASES, previous


def persistent_root(monkeypatch, *, evidence_dsn=None, knowledge_http_client_factory=None, knowledge_v2=False):
    import httpx
    import psycopg
    from app.config import Settings
    from app.transport.auth import AuthenticatedPrincipal
    from app.transport.container import build_supabase_container

    calls, connections, profiles = [], [], {}
    owners = {"DEMO-A": UUID(int=1101), "DEMO-B": UUID(int=1102)}
    original_client = httpx.Client

    def respond(request):
        token = request.headers["Authorization"].removeprefix("Bearer ")
        owner = owners[token]
        calls.append((token, request.method, request.url.path))
        if request.url.path.endswith("/patient_profiles"):
            import json

            if request.method == "PATCH":
                profiles[owner].update(json.loads(request.content))
                return httpx.Response(204)
            if owner in profiles:
                return httpx.Response(200, json=[profiles[owner]])
            profiles[owner] = {
                "user_id": str(owner),
                "display_name": None,
                "language": "en",
                "speech_locale": "en-SG",
                "text_size": "standard",
                "text_scale_percent": 100,
                "voice_enabled": True,
                "tts_autoplay": False,
                "conversation_history_enabled": False,
                "reminders_enabled": True,
                "reminder_lead_minutes": 0,
                "timezone": "Asia/Singapore",
                "created_at": "2026-10-29T00:00:00Z",
                "updated_at": "2026-10-29T00:00:00Z",
            }
            return httpx.Response(200, json=[profiles[owner]])
        if request.url.path.endswith("/assistant_enrollment_generations"):
            return httpx.Response(200, json=[])
        if request.url.path.endswith("_revision"):
            return httpx.Response(200, json={"revision": 0})
        raise AssertionError("Unexpected simulated patient operation: " + request.url.path)

    def client(**kwargs):
        return original_client(**(kwargs | {"transport": httpx.MockTransport(respond)}))

    def never_connect(*args, **kwargs):
        connections.append(True)
        raise AssertionError("Home/read composition must not connect to the restricted evidence identity")

    monkeypatch.setattr(httpx, "Client", client)
    monkeypatch.setattr(psycopg, "connect", never_connect)
    settings = Settings(
        database_url=None,
        supabase_url="https://example.invalid",
        supabase_publishable_key="sb_publishable_DEMO",
        supabase_secret_key=None,
        app_env="test",
        app_origin=None,
        vision_api_base_url=None,
        enable_demo_seed=False,
        persistence="supabase",
        auth_mode="supabase",
        source="DEMO_ONLY_EXPLICIT_TEST",
        assistant_workflows_enabled=True,
        assistant_evidence_dsn=evidence_dsn,
        assistant_knowledge_v2_enabled=knowledge_v2,
    )
    options = {"knowledge_http_client_factory": knowledge_http_client_factory} if knowledge_http_client_factory else {}
    root = build_supabase_container(settings=settings, **options)

    def scoped(token):
        owner = owners[token]
        return root.patient_factory(
            AuthenticatedPrincipal(
                patient_id=owner,
                subject=str(owner),
                email=None,
                authenticated=True,
                mode="supabase",
                access_token=token,
            )
        )

    return root, scoped, calls, connections, owners


def test_request_scoped_knowledge_transport_is_explicit_and_closes_without_patient_http_replay(monkeypatch):
    import json
    from pathlib import Path

    import httpx

    client_type = httpx.Client
    clients, requests = [], []
    fixture = json.loads((Path(__file__).parent / "fixtures/ibuprofen_labels_public.json").read_text(encoding="utf-8"))

    def reply(request):
        assert request.url.host == "api.fda.gov"
        requests.append(request)
        return httpx.Response(200, content=fixture["raw_response_utf8"], headers={"Content-Type": "application/json"})

    def factory():
        client = client_type(transport=httpx.MockTransport(reply), trust_env=False)
        clients.append(client)
        return client

    root, scoped, patient_calls, connections, owners = persistent_root(
        monkeypatch, knowledge_http_client_factory=factory, knowledge_v2=True
    )
    assert not clients  # No knowledge transport or provider activity at root startup.
    for token in ("DEMO-A", "DEMO-B"):
        request_container = scoped(token)
        result = request_container.medication_understanding.explain(
            patient_id=owners[token], medication_name="IBUPROFEN", language="en"
        )
        assert result.general_knowledge.status == "matched" and result.general_knowledge.use_facts
        request_container.close_request()
    assert len(clients) == 2 and all(client.is_closed for client in clients)
    assert len(requests) == 2
    assert [call[2] for call in patient_calls] == ["/rest/v1/patient_profiles"] * 2
    assert not connections


def test_home_without_evidence_dsn_never_connects(monkeypatch):
    root, scope, calls, connections, owners = persistent_root(monkeypatch)
    assert root.assistant_transactions is None
    app = scope("DEMO-A")
    try:
        assert app.preferences.get(owners["DEMO-A"]).patient_id == owners["DEMO-A"]
        assert app.assistant_transactions is not None and app.assistant_transactions.verifier is None
        assert app.assistant_workflows is None, (
            "Unaccepted SQL candidates cannot enable the default persistent workflow"
        )
        assert calls == [("DEMO-A", "GET", "/rest/v1/patient_profiles")]
        assert connections == []
    finally:
        app.close_request()


def test_invalid_optional_evidence_identity_cannot_break_home_or_create_a_fallback(monkeypatch):
    _root, scope, calls, connections, _owners = persistent_root(
        monkeypatch, evidence_dsn="postgresql://postgres:DEMO-disallowed@127.0.0.1:6543/demo_isolated?sslmode=disable"
    )
    app = scope("DEMO-A")
    try:
        assert app.assistant_transactions.verifier is None
        assert app.assistant_transactions.verification_reason == "verification_unavailable"
        assert app.assistant_transactions.rollout_ready is False and app.assistant_workflows is None
        assert calls == [("DEMO-A", "GET", "/rest/v1/patient_profiles")] and connections == []
    finally:
        app.close_request()


def test_patient_and_verifier_clients_are_separate(monkeypatch):
    from app.contracts.enums import ToolName
    from app.domain.errors import AuthenticationRequiredError
    from app.infrastructure.workflow_verification import PostgresEvidenceVerifier

    root, scope, calls, connections, owners = persistent_root(
        monkeypatch,
        evidence_dsn="postgresql://assistant_evidence_login:DEMO-only@127.0.0.1:6543/demo_isolated?sslmode=disable",
    )
    first, second = scope("DEMO-A"), scope("DEMO-B")
    try:
        assert root.assistant_transactions is None and first.assistant_transactions is not second.assistant_transactions
        for token, app in (("DEMO-A", first), ("DEMO-B", second)):
            ports = app.assistant_transactions
            assert isinstance(ports.verifier, PostgresEvidenceVerifier)
            for family in ("medications", "records", "care", "media", "settings", "reminders"):
                port = getattr(ports, family)
                before = len(calls)
                assert port.revision(owners[token]) == 0
                assert len(calls) == before + 1 and calls[-1][0] == token
                before = len(calls)
                with pytest.raises(AuthenticationRequiredError):
                    port.revision(owners["DEMO-B" if token == "DEMO-A" else "DEMO-A"])
                assert len(calls) == before
            assert "DEMO-only" not in repr(ports)
        evidence = {
            "record_storage_observation",
            "record_run_observation",
            "record_media_storage_observation",
            "record_media_delete_observation",
        }
        assert not evidence.intersection({x.value for x in ToolName})
        assert connections == []
    finally:
        first.close_request()
        second.close_request()


def test_all_91_capabilities_have_explicit_persistent_boundaries():
    from app.agent.capabilities import build_capability_registry
    from app.contracts.assistant_capabilities import CapabilityAvailability

    module = importlib.import_module("app.transport.persistent_workflow_composition")
    index = module.build_persistence_boundaries()
    definitions = build_capability_registry().list(CapabilityAvailability())
    assert len(index) == 91 and set(index) == {d.id for d in definitions}
    for definition in definitions:
        boundary = index[definition.id]
        assert boundary.capability_id == definition.id and boundary.mode == definition.mode
        assert boundary.patient_ports >= {"tasks", "controls", "mutations", "messages", "runs"}
        assert not {"verifier", "record_storage_observation", "record_run_observation"}.intersection(
            boundary.patient_ports
        )
        if boundary.family in {"medications", "records", "care", "media", "settings", "reminders"}:
            assert boundary.family in boundary.patient_ports and boundary.confirmation == "independent_patient_api"
        if definition.mode in {"device_ui", "navigation"}:
            assert boundary.confirmation == "browser"
    assert index["medication.source.add"].external_boundary == "verified_private_storage"
    assert index["preference.privacy"].external_boundary is None
    with pytest.raises(TypeError):
        index["DEMO.unknown"] = index["preference.privacy"]


def test_manifest_distinguishes_registered_implementation_from_available_authority():
    from app.agent.capabilities import build_capability_registry
    from app.contracts.assistant_capabilities import CapabilityAvailability

    views = {
        v.id: v
        for v in build_capability_registry().list(
            CapabilityAvailability(
                workflows_enabled=True, adapters=frozenset({"reminders"}), services=frozenset({"push"})
            )
        )
    }
    assert views["notification.test"].implemented and not views["notification.test"].available
    assert views["notification.test"].reason == "notification_send_not_authorized"
    assert views["reminder.snooze"].implemented and not views["reminder.snooze"].available
    assert not views["preference.privacy"].implemented


def test_unaccepted_persistent_graph_reports_a_safe_pending_reason_without_claiming_implementation(monkeypatch):
    from app.transport.auth import AuthenticatedPrincipal
    from app.transport.routes.assistant_workflows import capabilities

    _root, scope, _calls, connections, owners = persistent_root(monkeypatch)
    app = scope("DEMO-A")
    try:
        principal = AuthenticatedPrincipal(
            patient_id=owners["DEMO-A"],
            subject=str(owners["DEMO-A"]),
            email=None,
            authenticated=True,
            mode="supabase",
            access_token="DEMO-A",
        )
        catalog = capabilities(principal=principal, container=app)
        assert not catalog.enabled and len(catalog.capabilities) == 91
        assert all(
            not x.available and not x.implemented and x.reason == "persistence_not_ready" for x in catalog.capabilities
        )
        assert connections == []
    finally:
        app.close_request()


def test_unbound_native_requests_keep_existing_contract(monkeypatch):
    from app.contracts.preferences import PreferenceUpdate
    from app.transport.auth import AuthenticatedPrincipal
    from app.transport.routes.preferences import update_preferences

    _root, scope, calls, connections, owners = persistent_root(monkeypatch)
    app = scope("DEMO-A")
    try:
        principal = AuthenticatedPrincipal(
            patient_id=owners["DEMO-A"],
            subject=str(owners["DEMO-A"]),
            email=None,
            authenticated=True,
            mode="supabase",
            access_token="DEMO-A",
        )
        actual = update_preferences(
            payload=PreferenceUpdate(voice_enabled=False),
            principal=principal,
            container=app,
            assistant_task=None,
            assistant_revision=None,
            patient_confirmed=False,
        )
        assert actual.patient_id == owners["DEMO-A"] and actual.voice_enabled is False
        assert calls == [
            ("DEMO-A", "GET", "/rest/v1/patient_profiles"),
            ("DEMO-A", "PATCH", "/rest/v1/patient_profiles"),
            ("DEMO-A", "GET", "/rest/v1/patient_profiles"),
        ]
        assert connections == []
    finally:
        app.close_request()


@pytest.mark.parametrize("fault", [None, "owner", "task"])
def test_receipt_projection_reads_only_the_current_owned_task_collection(workflow, fault):
    from uuid import uuid4

    import httpx
    from app.domain.errors import AuthenticationRequiredError, ProviderUnavailableError
    from app.infrastructure.supabase_data import SupabaseDataClient
    from app.infrastructure.workflow_repos import SupabaseWorkflowMutations

    h, owner = workflow, workflow.owner_ids["A"]
    _coordinator, port = wire_settings(h)
    task = h.start("preference.text", {**CASES["preference.text"], "previous": previous(h)})
    view = h.event(task["task_id"], "prepare_confirmation")
    receipt = port.lookup(owner, UUID(view["result_ref"]["id"]))
    calls = []

    def respond(request):
        calls.append(request)
        assert request.method == "GET" and request.url.path == "/rest/v1/assistant_business_receipts"
        assert request.url.params["owner"] == "eq." + str(owner)
        assert request.url.params["task_id"] == "eq." + str(receipt.task_id)
        row = receipt.model_dump(mode="json")
        if fault:
            row["owner" if fault == "owner" else "task_id"] = str(uuid4())
        return httpx.Response(200, json=[row], headers={"Content-Range": "0-0/1"})

    data = SupabaseDataClient(
        base_url="https://example.invalid",
        publishable_key="sb_publishable_DEMO",
        access_token="DEMO-JWT",
        patient_id=owner,
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    reader = SupabaseWorkflowMutations(data)
    if fault:
        with pytest.raises(ProviderUnavailableError):
            reader.task_receipts(owner, receipt.task_id)
    else:
        assert reader.task_receipts(owner, receipt.task_id) == (receipt,)
    count = len(calls)
    with pytest.raises(AuthenticationRequiredError):
        reader.task_receipts(h.owner_ids["B"], receipt.task_id)
    assert len(calls) == count


@pytest.mark.parametrize("guard", ["confirmation", "payload", "paused", "revoked"])
def test_typed_settings_native_request_rejects_stale_or_unconfirmed_scope(workflow, guard):
    from .test_workflow_preferences import save

    h, owner = workflow, workflow.owner_ids["A"]
    _coordinator, _port = wire_settings(h)
    before = h.container.preferences.get(owner)
    task = h.start("preference.text", {**CASES["preference.text"], "previous": previous(h)})
    view = h.event(task["task_id"], "prepare_confirmation")
    kwargs = {}
    if guard == "confirmation":
        kwargs["confirmed"] = False
    if guard == "payload":
        kwargs["values"] = {"text_scale_percent": 140}
    if guard in {"paused", "revoked"}:
        h.event(task["task_id"], "pause" if guard == "paused" else "cancel_save")
    response = save(h, view, **kwargs)
    assert response.status_code in {403, 404, 409, 422}, response.text
    assert h.container.preferences.get(owner) == before


@pytest.mark.parametrize("family", ["settings", "reminder"])
def test_read_only_native_projection_with_missing_receipt_never_submits_a_write(workflow, family):
    import httpx
    from app.domain.errors import NotFoundError
    from app.infrastructure.supabase_data import SupabaseDataClient
    from app.infrastructure.workflow_repos import SupabaseWorkflowMutations

    h, owner = workflow, workflow.owner_ids["A"]
    if family == "settings":
        from .test_persistent_settings_transactions import preference_command, prepared

        local = harness(h)
        cmd = preference_command(
            h,
            local,
            prepared(h, local, "preference.text", {**CASES["preference.text"], "previous": previous(h)}),
            CASES["preference.text"],
        )
        module, class_name = "app.infrastructure.workflow_settings_writes", "SupabaseSettingsWorkflowWrites"
    else:
        from .test_persistent_reminder_transactions import command, prepared
        from .test_persistent_reminder_transactions import harness as reminder_port

        local = reminder_port(h)
        cmd = command(h, local, prepared(h, local))
        module, class_name = "app.infrastructure.workflow_reminder_writes", "SupabaseReminderWorkflowWrites"
    calls = []

    def respond(request):
        calls.append((request.method, request.url.path))
        assert request.method == "GET", "Read-only recovery cannot fall through to a mutation RPC"
        return httpx.Response(200, json=[])

    data = SupabaseDataClient(
        base_url="https://example.invalid",
        publishable_key="sb_publishable_DEMO",
        access_token="DEMO-JWT",
        patient_id=owner,
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    remote = getattr(importlib.import_module(module), class_name)(data=data, receipts=SupabaseWorkflowMutations(data))
    with pytest.raises(NotFoundError):
        remote.read(owner, cmd)
    assert calls == [("GET", "/rest/v1/assistant_business_receipts")]


def wire_settings(h):
    from app.infrastructure.memory_workflows import MemoryWorkflowMutations

    module = importlib.import_module("app.application.workflow_settings_transactions")
    port = harness(h)
    w = h.container.assistant_workflows
    receipts = MemoryWorkflowMutations(h.clock, state=w._repository._state)
    coordinator = module.SettingsWorkflowTransactions(
        writes=port,
        tasks=w._repository,
        receipts=receipts,
    )
    w._business_transactions = dict.fromkeys(coordinator.capability_ids, coordinator)
    h.container.assistant_settings.transactions = coordinator
    h.container.assistant_feedback.transactions = coordinator
    return coordinator, port


@pytest.mark.parametrize("capability", [*CASES, "caregiver.add", "feedback.submit"])
def test_typed_patient_http_prepares_once_and_reports_actual_native_result_without_another_cas(
    workflow, monkeypatch, capability
):
    from .test_workflow_contacts import save as save_contact
    from .test_workflow_feedback import save as save_feedback
    from .test_workflow_preferences import save as save_preferences

    h, owner = workflow, workflow.owner_ids["A"]
    _coordinator, port = wire_settings(h)
    values = (
        {**CASES[capability], "previous": previous(h)}
        if capability in CASES
        else details()
        if capability == "caregiver.add"
        else {"category": "issue", "message": "DEMO typed application feedback"}
    )
    view = h.start(capability, values)
    w = h.container.assistant_workflows
    cas = w._repository.cas
    writes = []

    def counted(*args, **kwargs):
        writes.append(args)
        return cas(*args, **kwargs)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("A typed patient transaction cannot be wrapped in a generic guarded callback")

    monkeypatch.setattr(w._repository, "cas", counted)
    monkeypatch.setattr(w._controls, "guarded_write", forbidden)
    review = h.event(view["task_id"], "prepare_confirmation")
    ref = UUID(review["result_ref"]["id"])
    receipt = port.lookup(owner, ref)
    assert receipt is not None and receipt.outcome == "prepared"
    assert review["revision"] == view["revision"] + 1 and len(writes) == 1
    save = save_preferences if capability in CASES else save_contact if capability == "caregiver.add" else save_feedback
    first = save(h, review)
    assert first.status_code == 200, first.text
    assert len(writes) == 2, (
        "Business write and task publication must be one transaction, not a later acknowledgement CAS"
    )
    # Duplicate patient confirmation reads the original native result; it never
    # updates the native row or advances the workflow again.
    assert save(h, review).json() == first.json()
    assert len(writes) == 2
    done = h.view(view["task_id"])
    assert done["state"] == "completed" and done["revision"] == review["revision"] + 1
    assert h.event(view["task_id"], "report_business_result")["state"] == "completed"
    assert len(writes) == 2


def test_completed_setting_retains_receipt_when_later_native_profile_changes(workflow, monkeypatch):
    from app.contracts.preferences import PreferenceUpdate

    from .test_workflow_preferences import save

    h, owner = workflow, workflow.owner_ids["A"]
    _coordinator, port = wire_settings(h)
    view = h.start("preference.text", {**CASES["preference.text"], "previous": previous(h)})
    review = h.event(view["task_id"], "prepare_confirmation")
    assert save(h, review).status_code == 200
    receipts = h.container.assistant_workflows._repository._state.business_receipts.copy()
    h.container.preferences.save(owner, PreferenceUpdate(display_name="DEMO later profile"))

    def forbidden(*_args, **_kwargs):
        raise AssertionError("A completed-task projection must only read native results")

    monkeypatch.setattr(port, "apply", forbidden)
    actual = h.view(view["task_id"])
    assert actual["state"] == "completed" and actual["visible_fields"]["actual_result_available"] is False
    assert h.container.assistant_workflows._repository._state.business_receipts == receipts


def test_preparation_recovery_after_run_expiry_reads_immutable_receipt_without_reprepare(workflow, monkeypatch):
    from uuid import uuid4

    from app.contracts.workflow_persistence import RunWriteBinding
    from app.domain.errors import StaleVersionError
    from app.infrastructure.durable_agent_runs import MemoryDurableRunControl

    from .test_durable_agent_runs import claimed

    h, owner = workflow, workflow.owner_ids["A"]
    coordinator, port = wire_settings(h)
    view = h.start("preference.text", {**CASES["preference.text"], "previous": previous(h)})
    w = h.container.assistant_workflows
    task = w._repository.get(owner, UUID(view["task_id"]))
    run = claimed(MemoryDurableRunControl(clock=h.clock, state=w._repository._state), owner)
    event = uuid4()
    receipt = coordinator.prepare(task, task.revision, event, RunWriteBinding(run_id=run.run_id, epoch=run.epoch))
    h.clock.advance(seconds=46)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Known preparation recovery must not submit another transaction")

    monkeypatch.setattr(port, "prepare", forbidden)
    assert coordinator.prepare(w._repository.get(owner, task.id), task.revision, event) == receipt
    with pytest.raises(StaleVersionError):
        coordinator.prepare(w._repository.get(owner, task.id), task.revision + 1, event)


def test_typed_contact_edit_and_delete_preserve_existing_patient_contract(workflow):
    from .test_workflow_contacts import save

    h = workflow
    wire_settings(h)
    view = h.start("caregiver.add", details())
    row = save(h, h.event(view["task_id"], "prepare_confirmation")).json()
    for capability in ("caregiver.edit", "caregiver.delete"):
        values = {
            "contact_id": row["id"],
            "previous": {key: row[key] for key in details()},
            "previous_updated_at": row["updated_at"],
        }
        if capability.endswith("edit"):
            values |= details() | {"name": "DEMO typed edit"}
        view = h.start(capability, values)
        review = h.event(view["task_id"], "prepare_confirmation")
        response = save(h, review)
        assert response.status_code == 200, response.text
        assert save(h, review).json() == response.json()
        assert h.view(view["task_id"])["state"] == "completed"
        row = response.json()


@pytest.mark.parametrize("capability", ["reminder.snooze", "reminder.settings"])
def test_typed_reminder_http_uses_one_native_transaction_and_read_only_acknowledgement(
    workflow, monkeypatch, capability
):
    from app.infrastructure.memory_workflows import MemoryWorkflowMutations

    from .test_persistent_reminder_transactions import harness as reminder_port
    from .test_workflow_reminder_writes import fields, save

    h, owner = workflow, workflow.owner_ids["A"]
    port = reminder_port(h)
    w = h.container.assistant_workflows
    cls = importlib.import_module("app.application.workflow_reminder_transactions").ReminderWorkflowTransactions
    coordinator = cls(
        writes=port, tasks=w._repository, receipts=MemoryWorkflowMutations(h.clock, state=w._repository._state)
    )
    w._business_transactions = dict.fromkeys(coordinator.capability_ids, coordinator)
    h.container.assistant_reminder_writes.transactions = coordinator
    view = h.start(capability, fields(h, capability))
    cas = w._repository.cas
    writes = []

    def counted(*args, **kwargs):
        writes.append(args)
        return cas(*args, **kwargs)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Typed reminder must not enter a generic guarded callback")

    monkeypatch.setattr(w._repository, "cas", counted)
    monkeypatch.setattr(w._controls, "guarded_write", forbidden)
    review = h.event(view["task_id"], "prepare_confirmation")
    assert port.lookup(owner, UUID(review["result_ref"]["id"])).outcome == "prepared" and len(writes) == 1
    first = save(h, review)
    assert first.status_code == 200, first.text
    assert save(h, review).json() == first.json() and len(writes) == 2
    assert h.event(view["task_id"], "report_business_result")["state"] == "completed"
    assert h.view(view["task_id"])["revision"] == review["revision"] + 1 and len(writes) == 2


def test_typed_timezone_save_invalidates_another_open_domain_review_without_suspending_it(workflow):
    from uuid import uuid4

    from app.domain.errors import StaleVersionError

    from .test_persistent_care_transactions import harness as care_port
    from .test_persistent_care_transactions import prepared as care_prepared
    from .test_persistent_care_transactions import save_observation
    from .test_workflow_care import fields
    from .test_workflow_preferences import save

    h, owner = workflow, workflow.owner_ids["A"]
    wire_settings(h)
    care = care_port(h)
    pending = care_prepared(h, "observation.add", fields(h, "observation.add"))
    command = save_observation(h, pending, care)
    before = care.revision(owner)
    h.workspace_id = str(uuid4())
    task = h.start("preference.timezone", {"timezone": "America/New_York", "previous": previous(h)})
    control = h.container.assistant_workflows._controls.get(owner, UUID(pending["task_id"]))
    assert control.status == "idle" and control.revision == command.binding.task_revision
    assert care.revision(owner) == before, "Creating another workspace must not vacuously invalidate the review"
    review = h.event(task["task_id"], "prepare_confirmation")
    assert save(h, review).status_code == 200
    assert care.revision(owner) > before, "Typed profile writes must advance the shared clinical-input epoch"
    with pytest.raises(StaleVersionError):
        care.apply(owner, command)


@pytest.mark.parametrize(
    "capability",
    [
        "observation.add",
        "observation.edit",
        "observation.delete",
        "inventory.count",
        "barrier.add",
        "followup.add",
        "followup.edit",
        "followup.contacted",
        "followup.complete",
        "followup.defer",
        "followup.cancel",
    ],
)
def test_typed_care_http_preserves_native_contract_and_one_task_advancement(workflow, monkeypatch, capability):
    from datetime import timedelta
    from uuid import uuid4

    from app.infrastructure.memory_workflows import MemoryWorkflowMutations

    from .test_persistent_care_transactions import harness as care_port
    from .test_workflow_care import fields, patient_request
    from .test_workflow_medication_management import active_plan

    h, owner = workflow, workflow.owner_ids["A"]
    w = h.container.assistant_workflows
    port = care_port(h)
    cls = importlib.import_module("app.application.workflow_care_transactions").CareWorkflowTransactions
    coordinator = cls(
        writes=port,
        tasks=w._repository,
        receipts=MemoryWorkflowMutations(h.clock, state=w._repository._state),
        adapter=w._adapters["observation.add"],
        preferences=h.container.preferences,
        care=h.container.long_term,
    )
    w._business_transactions = dict.fromkeys(coordinator.capability_ids, coordinator)
    h.container.assistant_care.transactions = coordinator
    medicine = active_plan(h)
    observation = h._request(
        "PUT",
        "/api/me/health-observations",
        json={
            "id": str(uuid4()),
            "description": "DEMO care seed",
            "occurred_at": h.clock.now().isoformat(),
            "confirmed": True,
        },
    )
    followup = h._request(
        "POST",
        "/api/me/care-tasks",
        json={
            "id": str(uuid4()),
            "title": "DEMO care seed",
            "category": "medication_review",
            "due_at": (h.clock.now() + timedelta(days=2)).isoformat(),
            "confirmed": True,
        },
    )
    values = fields(h, capability, medicine, followup, observation)
    if capability == "observation.edit":
        values = {
            "observation_id": observation["id"],
            "description": "DEMO reviewed edit",
            "occurred_at": h.clock.now().isoformat(),
        }
    view = h.start(capability, values)
    cas = w._repository.cas
    writes = []

    def counted(*args, **kwargs):
        writes.append(args)
        return cas(*args, **kwargs)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Typed care cannot enter a generic callback")

    monkeypatch.setattr(w._repository, "cas", counted)
    monkeypatch.setattr(w._controls, "guarded_write", forbidden)
    review = h.event(view["task_id"], "prepare_confirmation")
    assert port.lookup(owner, UUID(review["result_ref"]["id"])).outcome == "prepared" and len(writes) == 1
    method, path, payload = patient_request(h, review)
    args = {"headers": {"X-Assistant-Task": review["task_id"], "X-Assistant-Revision": str(review["revision"])}}
    if method != "DELETE":
        args["json"] = payload
    first = h._request(method, path, **args)
    assert h._request(method, path, **args) == first and len(writes) == 2
    assert h.event(view["task_id"], "report_business_result")["state"] == "completed"
    actual = h.view(view["task_id"])
    assert actual["revision"] == review["revision"] + 1 and len(writes) == 2
    assert actual["visible_fields"].get("actual_result_available") is not False


def test_care_delete_receipt_cannot_claim_a_recreated_observation_is_absent(workflow):
    from uuid import uuid4

    from app.contracts.observations import ObservationInput
    from app.domain.errors import StaleVersionError

    from .test_persistent_care_transactions import api, binding, prepared
    from .test_persistent_care_transactions import harness as care_port

    h, owner = workflow, workflow.owner_ids["A"]
    native = h.container.observations.save(
        owner, ObservationInput(id=uuid4(), description="DEMO original note", occurred_at=h.clock.now(), confirmed=True)
    )
    view = prepared(h, "observation.delete", {"observation_id": str(native.id)})
    port = care_port(h)
    cmd = api("DeleteObservation")(binding=binding(h, port, view), observation_id=native.id, confirmed=True)
    deleted = port.apply(owner, cmd)
    current = h.container.observations.save(
        owner,
        ObservationInput(id=native.id, description="DEMO recreated note", occurred_at=h.clock.now(), confirmed=True),
    )
    with pytest.raises(StaleVersionError):
        port.read(owner, cmd)
    with pytest.raises(StaleVersionError):
        port.apply(owner, cmd)
    assert h.container.observations.get(owner, native.id) == current
    assert port.lookup(owner, cmd.binding.action_key) == deleted.receipt
