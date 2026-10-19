"""DEMO_ONLY HTTP/subprocess scope tests; no real provider or production I/O."""

import hashlib
import hmac
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.contracts.notifications import DispatchResult
from app.infrastructure.dispatch_process import ProcessDispatchRunner
from app.transport.dispatcher import create_dispatcher_app
from app.transport.worker_container import build_worker_dispatch
from fastapi.testclient import TestClient

TOKEN = "DEMO_ONLY-" + "x" * 40
PATH = "/internal/notifications/dispatch-synthetic"


def headers(path=PATH):
    return {
        "X-Dispatch-Timestamp": "2000",
        "X-Dispatch-Signature": hmac.new(TOKEN.encode(), f"POST\n{path}\n2000".encode(), hashlib.sha256).hexdigest(),
    }


def test_scope_is_server_selected_and_normal_dispatch_unchanged():
    calls = []

    def normal():
        calls.append("normal")
        return DispatchResult(status="completed")

    def scoped():
        calls.append("synthetic")
        return DispatchResult(status="completed", profiles=1)

    client = TestClient(
        create_dispatcher_app(
            token=TOKEN,
            runner=SimpleNamespace(run=normal),
            synthetic_runner=SimpleNamespace(run=scoped),
            wall_time=lambda: 2000,
        )
    )
    assert client.post(PATH, headers=headers()).json()["profiles"] == 1
    normal_path = "/internal/notifications/dispatch"
    assert client.post(normal_path, headers=headers(normal_path)).status_code == 200
    assert calls == ["synthetic", "normal"]
    assert client.post(PATH, headers=headers(normal_path)).status_code == 401
    assert client.post(PATH, headers=headers(), json={"patient_id": "other"}).status_code == 400
    assert client.post(PATH + "?patient_id=other", headers=headers()).status_code == 400
    assert calls == ["synthetic", "normal"]


def test_unconfigured_scope_never_falls_back_to_global_runner():
    def forbidden():
        raise AssertionError("Global dispatch must not run")

    client = TestClient(
        create_dispatcher_app(token=TOKEN, runner=SimpleNamespace(run=forbidden), wall_time=lambda: 2000)
    )
    assert client.post(PATH, headers=headers()).status_code == 404
    assert client.post(PATH).status_code == 401


def test_stale_scoped_signature_rejected():
    client = TestClient(
        create_dispatcher_app(
            token=TOKEN,
            synthetic_runner=SimpleNamespace(run=lambda: (_ for _ in ()).throw(AssertionError())),
            wall_time=lambda: 2061,
        )
    )
    assert client.post(PATH, headers=headers()).status_code == 401


def test_scoped_subprocess_has_no_client_account_argument():
    def execute(command, **kwargs):
        assert "--synthetic-only" in command
        assert not any("patient" in part for part in command)
        assert kwargs["timeout"] == 25
        return SimpleNamespace(returncode=0, stdout='{"status":"completed","profiles":1}')

    assert ProcessDispatchRunner(execute=execute, root=Path("/demo"), synthetic_only=True).run().profiles == 1


@pytest.mark.parametrize("configured", [None, "not-an-account"])
def test_scoped_composition_rejects_missing_or_invalid_server_scope(configured):
    with pytest.raises(ValueError, match="Synthetic dispatcher account"):
        build_worker_dispatch(
            SimpleNamespace(enable_web_push=True, push_synthetic_patient_id=configured), synthetic_only=True
        )
