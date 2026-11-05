"""Synthetic request admission; no real provider, database or patient writes."""

from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID

import pytest
from app.contracts.workflow_runtime import RUNTIME_RELEASE_CONTRACT, RuntimeReleaseSnapshot
from app.domain.errors import ProviderUnavailableError
from fastapi.testclient import TestClient
from starlette.requests import Request

from .test_persistent_workflow_composition import persistent_root


def reader(snapshot=None, *, fail=False):
    calls = []

    def read_release(*, timeout_seconds):
        calls.append(timeout_seconds)
        if fail:
            raise ProviderUnavailableError("DEMO-secret must not escape")
        return snapshot or RuntimeReleaseSnapshot(
            contract_version=RUNTIME_RELEASE_CONTRACT,
            accepted=True,
            release_id=UUID(int=909),
            application_hash="a" * 64,
            catalog_digest="b" * 32,
            native_media_ready=True,
        )

    return SimpleNamespace(read_release=read_release), calls


def prepared(monkeypatch, *, native=True, progress=False, fail=False):
    from app.application.workflow_readiness import WorkflowRuntime

    root, scope, calls, connections, _owners = persistent_root(monkeypatch)
    scoped = scope("DEMO-A")
    patient, patient_calls = reader(fail=fail)
    technical, technical_calls = reader()
    scoped.assistant_runtime = WorkflowRuntime(
        patient=patient,
        technical=technical,
        application_hash="a" * 64,
        native_media_enabled=native,
        progress_enabled=progress,
    )
    root.patient_factory = lambda _principal: scoped
    return root, scoped, patient_calls, technical_calls, calls, connections


def request_for(root, path, *, method="GET", bound=False):
    request = Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": b"",
            "headers": [(b"x-assistant-task", b"DEMO-task")] if bound else [],
            "app": SimpleNamespace(state=SimpleNamespace(container=root)),
        }
    )
    request.state.principal = SimpleNamespace(patient_id=UUID(int=1101))
    return request


def test_ordinary_home_read_has_no_readiness_io(monkeypatch):
    from app.transport.deps import get_container

    root, scoped, patient_calls, technical_calls, _, connections = prepared(monkeypatch)
    assert get_container(request_for(root, "/api/preferences")) is scoped
    assert patient_calls == technical_calls == connections == []


def test_production_composition_installs_lazy_readiness_without_verifier_or_flags_bypass(monkeypatch):
    from app.infrastructure.workflow_readiness import SupabaseRuntimeReadiness

    _, scope, calls, connections, _ = persistent_root(monkeypatch)
    scoped = scope("DEMO-A")
    assert isinstance(scoped.assistant_runtime.patient, SupabaseRuntimeReadiness)
    assert scoped.assistant_runtime.technical is None
    assert len(scoped.assistant_runtime.application_hash) == 64
    assert scoped.assistant_runtime.native_media_enabled is False
    assert scoped.assistant_runtime.progress_enabled is False
    assert calls == [("DEMO-A", "GET", "/rest/v1/patient_profiles")] and connections == []


@pytest.mark.parametrize("progress", [False, True])
def test_valid_release_mounts_request_candidate_once_and_respects_progress(monkeypatch, progress):
    from app.transport.deps import get_container

    root, scoped, pc, tc, _, connections = prepared(monkeypatch, progress=progress)
    request = request_for(root, "/api/agent/workflows/capabilities")
    admitted = get_container(request)
    assert admitted is not scoped and admitted.assistant_workflows is not None
    assert admitted.assistant_transactions is scoped.assistant_candidate.ports
    assert admitted.assistant_transactions.tasks is scoped.assistant_transactions.tasks
    assert admitted.assistant_admission.available is True
    assert (admitted.assistant_execution is not None) is progress
    assert get_container(request) is admitted
    assert pc == tc == [4.0] and connections == []
    assert scoped.assistant_workflows is None


def test_failed_readiness_is_safe_and_does_not_disable_ordinary_conversation(monkeypatch):
    from app.transport.deps import get_container

    root, scoped, pc, tc, _, _ = prepared(monkeypatch, fail=True)
    fallback = get_container(request_for(root, "/api/agent/messages", method="POST"))
    assert fallback is scoped and fallback.messages() is not None
    assert fallback.assistant_admission.reason == "readiness_unavailable"
    assert "DEMO-secret" not in repr(fallback.assistant_admission)
    assert pc == [4.0] and tc == []


@pytest.mark.parametrize(
    "path,bound",
    [
        ("/api/agent/workflows/tasks", False),
        ("/api/preferences", True),
        ("/api/evidence/gallery/DEMO/images", False),
    ],
)
def test_unready_workflow_and_paired_native_writes_fail_closed(monkeypatch, path, bound):
    from app.transport.deps import get_container

    root, _, _, _, _, _ = prepared(monkeypatch, fail=True)
    with pytest.raises(ProviderUnavailableError, match="Assistant persistence is unavailable"):
        get_container(request_for(root, path, method="POST", bound=bound))


def test_native_pairing_is_required_even_when_release_marker_is_accepted(monkeypatch):
    from app.transport.deps import get_container

    root, _, pc, tc, _, _ = prepared(monkeypatch, native=False)
    result = get_container(request_for(root, "/api/agent/workflows/capabilities"))
    assert result.assistant_admission.reason == "native_media_not_ready"
    assert result.assistant_workflows is None and pc == tc == []


@pytest.mark.parametrize("fail", [False, True])
def test_independent_native_bridge_checks_release_without_enabling_assistant(monkeypatch, fail):
    from app.transport.deps import get_container

    root, scoped, pc, tc, _, _ = prepared(monkeypatch, fail=fail)
    scoped.assistant_candidate = None
    scoped.assistant_transactions = None
    req = request_for(root, "/api/evidence/gallery/DEMO/images", method="POST")
    if fail:
        with pytest.raises(ProviderUnavailableError):
            get_container(req)
        assert tc == []
    else:
        assert get_container(req) is scoped
        assert scoped.assistant_workflows is None
        assert tc == [4.0]
    assert pc == [4.0]


def test_revoked_release_blocks_native_only_writes_without_blocking_ordinary_reads(monkeypatch):
    from app.application.native_media_verification import VerifiedNativeMediaStore
    from app.transport.deps import get_container

    from .test_native_media_composition import enable

    enable(monkeypatch, assistant_native_media_enabled=True, assistant_workflows_enabled=False)
    root, scope, _, connections, _ = persistent_root(monkeypatch)
    scoped = scope("DEMO-A")
    assert isinstance(scoped.gallery._storage, VerifiedNativeMediaStore)
    patient, pc = reader(RuntimeReleaseSnapshot(contract_version=RUNTIME_RELEASE_CONTRACT, accepted=False))
    technical, tc = reader()
    scoped.assistant_runtime = replace(
        scoped.assistant_runtime,
        patient=patient,
        technical=technical,
        application_hash="a" * 64,
    )
    root.patient_factory = lambda _principal: scoped
    with pytest.raises(ProviderUnavailableError):
        get_container(request_for(root, "/api/evidence/gallery/DEMO/images", method="POST"))
    assert pc == tc == [4.0]
    assert get_container(request_for(root, "/api/evidence/gallery")) is scoped
    assert pc == tc == [4.0] and connections == []
    assert scoped.assistant_workflows is None


def test_absent_verifier_cannot_use_patient_record_as_acceptance(monkeypatch):
    from app.transport.deps import get_container

    root, scoped, pc, tc, _, _ = prepared(monkeypatch)
    scoped.assistant_runtime = replace(scoped.assistant_runtime, technical=None)
    result = get_container(request_for(root, "/api/agent/workflows/capabilities"))
    assert result.assistant_admission.reason == "verification_unavailable"
    assert pc == tc == []


def test_admitted_patients_keep_distinct_services_and_clients(monkeypatch):
    from app.application.workflow_readiness import WorkflowRuntime
    from app.transport.deps import get_container

    root, scope, _, connections, owners = persistent_root(monkeypatch)
    admitted = []
    scopes = [(token, scope(token)) for token in ("DEMO-A", "DEMO-B")]
    for token, scoped in scopes:
        patient, _ = reader()
        technical, _ = reader()
        scoped.assistant_runtime = WorkflowRuntime(
            patient=patient,
            technical=technical,
            application_hash="a" * 64,
            native_media_enabled=True,
            progress_enabled=False,
        )
        root.patient_factory = lambda _principal, scoped=scoped: scoped
        req = request_for(root, "/api/agent/workflows/capabilities")
        req.state.principal.patient_id = owners[token]
        admitted.append(get_container(req))
    assert admitted[0].assistant_transactions is not admitted[1].assistant_transactions
    assert admitted[0].assistant_workflows is not admitted[1].assistant_workflows
    assert connections == []


def test_public_health_reports_configuration_without_patient_or_verifier_io(monkeypatch):
    from app.config import Settings
    from app.transport.app_factory import create_app

    root, _, pc, tc, calls, connections = prepared(monkeypatch)
    before = list(calls)
    settings = Settings.from_env()
    settings = replace(settings, assistant_workflows_enabled=True, assistant_native_media_enabled=True)
    response = TestClient(create_app(root, settings=settings)).get("/api/health")
    assert response.status_code == 200
    health = response.json()
    assert health["assistant_workflows_configured"] is True
    assert health["assistant_runtime_status"] == "not_checked"
    assert len(health["application_hash"]) == 64
    assert "dsn" not in response.text.lower() and "DEMO-" not in response.text
    assert pc == tc == connections == [] and calls == before


@pytest.mark.parametrize("fail", [False, True])
def test_authenticated_capabilities_reports_actual_admission_and_keeps_no_store(monkeypatch, fail):
    from app.transport.app_factory import create_app
    from app.transport.auth import AuthBoundary, StaticTokenVerifier

    root, _, _, _, _, _ = prepared(monkeypatch, fail=fail)
    root.auth = AuthBoundary(
        mode="supabase",
        verifier=StaticTokenVerifier(
            {
                "DEMO-A": {"sub": str(UUID(int=1101)), "role": "authenticated"},
            }
        ),
    )
    response = TestClient(create_app(root)).get(
        "/api/agent/workflows/capabilities",
        headers={"Authorization": "Bearer DEMO-A"},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["enabled"] is (not fail)
    assert response.json()["admission"]["reason"] == ("readiness_unavailable" if fail else "ready")


@pytest.mark.parametrize("code", ["22023", "42725"])
def test_real_data_api_validation_failure_becomes_safe_unavailable_and_preserves_chat(monkeypatch, code):
    import httpx
    from app.agent.orchestrator import AgentReply
    from app.contracts.assistant_workflows import WorkflowMessageResult
    from app.contracts.enums import AgentIntent
    from app.infrastructure.supabase_data import SupabaseDataClient
    from app.infrastructure.workflow_readiness import SupabaseRuntimeReadiness
    from app.transport.app_factory import create_app
    from app.transport.auth import AuthBoundary, StaticTokenVerifier
    from app.transport.deps import get_container

    calls = []

    def rejected(request):
        calls.append(request.url.path)
        return httpx.Response(400, json={"code": code, "message": "DEMO-private-detail"})

    # Construct the real HTTP adapter before the production fixture patches its
    # default client. Only this explicit synthetic transport serves the RPC.
    with httpx.Client(transport=httpx.MockTransport(rejected)) as http:
        root, scoped, _, technical_calls, _, _ = prepared(monkeypatch)
        data = SupabaseDataClient(
            base_url="https://example.invalid",
            publishable_key="sb_publishable_DEMO",
            access_token="DEMO-A",
            patient_id=UUID(int=1101),
            client=http,
        )
        scoped.assistant_runtime = replace(scoped.assistant_runtime, patient=SupabaseRuntimeReadiness(data))
        root.auth = AuthBoundary(
            mode="supabase",
            verifier=StaticTokenVerifier(
                {
                    "DEMO-A": {"sub": str(UUID(int=1101)), "role": "authenticated"},
                }
            ),
        )
        response = TestClient(create_app(root)).get(
            "/api/agent/workflows/capabilities",
            headers={"Authorization": "Bearer DEMO-A"},
        )
        assert response.status_code == 200
        assert response.json()["admission"]["reason"] == "readiness_unavailable"
        assert "DEMO-private-detail" not in response.text
        fallback = get_container(request_for(root, "/api/agent/messages", method="POST"))
        assert fallback is scoped and fallback.messages() is not None
        handled = []

        def existing_conversation(owner, payload):
            handled.append((owner, payload.text))
            return WorkflowMessageResult(
                reply=AgentReply(
                    message="DEMO existing conversation available",
                    intent=AgentIntent.CLARIFICATION,
                    session_id=UUID(int=707),
                    session_state="idle",
                )
            )

        monkeypatch.setattr(scoped, "messages", lambda: SimpleNamespace(handle=existing_conversation))
        message = TestClient(create_app(root)).post(
            "/api/agent/messages",
            json={"text": "DEMO question"},
            headers={"Authorization": "Bearer DEMO-A"},
        )
        assert message.status_code == 200
        assert message.json()["message"] == "DEMO existing conversation available"
        assert handled == [(UUID(int=1101), "DEMO question")]
        assert calls == ["/rest/v1/rpc/assistant_runtime_readiness"] * 3
        assert technical_calls == []
