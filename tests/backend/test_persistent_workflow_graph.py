"""DEMO_ONLY full request graph construction is not real target acceptance."""

import pytest

from .test_persistent_workflow_composition import persistent_root


@pytest.mark.parametrize(
    "dsn",
    [
        None,
        "not-an-approved-dsn",
        "postgresql://assistant_evidence_login:DEMO-only@127.0.0.1:6543/demo_isolated?sslmode=disable",
    ],
)
def test_complete_candidate_graph_is_request_local_lazy_and_rollout_gated(monkeypatch, dsn):
    root, scoped, calls, connections, owners = persistent_root(monkeypatch, evidence_dsn=dsn)
    first = scoped("DEMO-A")
    graph = first.assistant_candidate
    assert graph is not None and graph.container.assistant_workflows is not None
    assert graph.rollout_ready is False and first.assistant_workflows is None
    assert len(graph.ports.boundaries) == 91
    assert graph.container.assistant_medications.capability_ids == {
        "medication.enroll",
        "medication.plan.change",
        "medication.plan.end",
        "medication.draft.resume",
        "medication.draft.delete",
        "medication.source.add",
        "medication.source.review",
    }
    assert graph.container.assistant_reports.transactions is not None
    assert graph.container.assistant_photo_upload.transactions is not None
    assert graph.container.assistant_care.transactions is not None
    second = scoped("DEMO-B")
    assert second.assistant_candidate is not graph
    assert second.assistant_candidate.ports.tasks is not graph.ports.tasks
    assert not connections
    assert calls == [("DEMO-A", "GET", "/rest/v1/patient_profiles"), ("DEMO-B", "GET", "/rest/v1/patient_profiles")]
    assert "DEMO-A" not in repr(graph) and "dsn" not in repr(graph)
    assert graph.container.store is None


def test_candidate_graph_has_explicit_adapters_or_unavailable_dependencies_for_all_91(monkeypatch):
    _, scoped, calls, _, _ = persistent_root(monkeypatch)
    graph = scoped("DEMO-A").assistant_candidate
    implemented = graph.implemented_capabilities
    assert implemented | graph.unavailable_capabilities == set(graph.ports.boundaries)
    assert not (implemented & graph.unavailable_capabilities)
    assert graph.container.assistant_transactions is graph.ports
    assert graph.container.messages().message_persistence is graph.ports.messages
    assert graph.container.assistant_execution is not None
    assert len(calls) == 1


def test_native_candidate_session_start_and_confirmation_use_typed_message_port(monkeypatch):
    from app.contracts.workflow_messages import MessageWriteAck

    _, scoped, calls, _, owners = persistent_root(monkeypatch)
    graph = scoped("DEMO-A").assistant_candidate
    commands = []

    def save(owner, command):
        assert owner == owners["DEMO-A"]
        commands.append(command)
        return MessageWriteAck()

    monkeypatch.setattr(graph.ports.messages, "execute", save)
    session = graph.container.orchestrator.start_session(patient_id=owners["DEMO-A"])
    assert len(commands) == 1 and commands[0].kind == "create_session"
    monkeypatch.setattr(graph.container.orchestrator._sessions, "get", lambda *a: session)
    graph.container.orchestrator.await_confirmation(patient_id=owners["DEMO-A"], session_id=session.id)
    assert commands[-1].kind == "update_context"
    assert graph.container.registry._records is graph.ports.records
    assert len(calls) == 1


def test_candidate_deletion_projection_has_read_only_native_receipt_lookup(monkeypatch):
    from uuid import uuid4

    _, scoped, _, _, owners = persistent_root(monkeypatch)
    graph = scoped("DEMO-A").assistant_candidate
    seen = []
    data = graph.ports.medications._data

    def request(method, path, **kwargs):
        seen.append((method, path, kwargs))
        assert path == "/rest/v1/rpc/assistant_draft_deletion_result"
        return {"deleted": True, "medication_deleted": True, "cleanup_pending": True}

    monkeypatch.setattr(data, "request", request)
    result = graph.container.draft_deletion.receipt(owners["DEMO-A"], "draft", uuid4())
    assert result.cleanup_pending
    assert len(seen) == 1


@pytest.mark.parametrize("operation", ["read", "put", "delete"])
def test_raw_object_access_requires_fixed_owned_server_decision(monkeypatch, operation):
    from uuid import uuid4

    from app.domain.errors import AuthenticationRequiredError, ProviderUnavailableError
    from app.infrastructure.workflow_objects import SupabaseWorkflowObjectAccess

    _, scoped, _, _, owners = persistent_root(monkeypatch)
    graph = scoped("DEMO-A").assistant_candidate
    data = graph.ports.medications._data
    called = []

    def request(method, path, **kwargs):
        called.append((method, path, kwargs))
        assert path == "/rest/v1/rpc/assistant_original_object_access"
        return {"allowed": False}

    monkeypatch.setattr(data, "request", request)
    gate = SupabaseWorkflowObjectAccess(data)
    assert gate.permit(owners["DEMO-A"], uuid4(), uuid4(), operation) is False
    with pytest.raises(AuthenticationRequiredError):
        gate.permit(owners["DEMO-B"], uuid4(), uuid4(), operation)
    assert len(called) == 1
    monkeypatch.setattr(data, "request", lambda *a, **kw: {"allowed": "true"})
    with pytest.raises(ProviderUnavailableError):
        gate.permit(owners["DEMO-A"], uuid4(), uuid4(), operation)


def test_every_registered_business_writer_uses_an_explicit_transaction(monkeypatch):
    _, scoped, _, _, _ = persistent_root(monkeypatch)
    graph = scoped("DEMO-A").assistant_candidate
    workflows = graph.container.assistant_workflows
    assert set(workflows._writers) <= set(workflows._business_transactions)
    assert len(workflows._business_transactions) == 43
    assert not any(type(value).__module__.endswith("memory") for value in workflows._business_transactions.values())


def test_candidate_model_uses_same_typed_registry_and_fallback_without_provider_calls(monkeypatch):
    from types import SimpleNamespace

    root, scoped, calls, connections, _ = persistent_root(monkeypatch)
    root.conversational_model = SimpleNamespace()
    candidate = scoped("DEMO-A").assistant_candidate.container
    assert candidate.ai_agent._fallback is candidate.orchestrator
    assert candidate.ai_agent._conversation._fallback is candidate.orchestrator
    assert candidate.registry._records is candidate.assistant_transactions.records
    assert not connections and len(calls) == 1


def test_all_91_adapters_construct_with_explicit_optional_services_without_io(monkeypatch):
    from dataclasses import replace

    from app.transport import container as composition

    original = composition.build_supabase_container

    def full(*, settings):
        return original(
            settings=replace(
                settings,
                assistant_knowledge_v2_enabled=True,
                enable_medication_library_files=True,
                enable_late_dose_reports=True,
                enable_care_task_followups=True,
            )
        )

    monkeypatch.setattr(composition, "build_supabase_container", full)
    _, scoped, calls, connections, _ = persistent_root(
        monkeypatch,
        evidence_dsn="postgresql://assistant_evidence_login:DEMO-only@127.0.0.1:6543/demo_isolated?sslmode=disable",
    )
    graph = scoped("DEMO-A").assistant_candidate
    assert graph.implemented_capabilities == frozenset(graph.ports.boundaries)
    assert not graph.unavailable_capabilities
    assert graph.container.assistant_knowledge is not None
    assert graph.container.assistant_pdf_upload is not None
    assert graph.container.assistant_late_reports is not None
    assert len(calls) == 1 and not connections
