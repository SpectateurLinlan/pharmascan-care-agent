"""Deployment boundary checks with synthetic configuration; no cloud calls."""

from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from app.config import ConfigError, Settings
from app.transport.app_factory import create_app
from fastapi.testclient import TestClient

from scripts.run_patient_api import REPO_ROOT, check_resources, check_settings, main


def deployment_settings() -> Settings:
    return Settings(
        database_url=None,
        supabase_url="https://synthetic.supabase.co",
        supabase_publishable_key="sb_publishable_demo_only",
        supabase_secret_key=None,
        app_env="production",
        app_origin="https://synthetic.example.invalid",
        vision_api_base_url="https://stage2.example.invalid",
        enable_demo_seed=False,
        persistence="supabase",
        auth_mode="supabase",
        source="synthetic_process_environment",
    )


def test_resources_present_and_missing(tmp_path: Path) -> None:
    check_resources(REPO_ROOT)
    with pytest.raises(ConfigError, match="resource is missing"):
        check_resources(tmp_path)


@pytest.mark.parametrize(
    "changes",
    [
        {"database_url": "synthetic_admin_secret"},
        {"supabase_secret_key": "synthetic_admin_secret"},
        {"push_dispatch_token": "synthetic_worker_secret"},
        {"vapid_private_key": "synthetic_worker_secret"},
        {"enable_web_push": True},
        {"auth_mode": "demo"},
        {"persistence": "in_memory"},
        {"enable_demo_seed": True},
        {"app_origin": "http://example.invalid"},
        {"app_origin": "https://example.invalid/path"},
        {"app_origin": "https://example.invalid/"},
        {"supabase_url": "https://user:secret@example.invalid"},
        {"model_provider": "gemini", "gemini_api_key": None},
        {"supabase_publishable_key": "sb_secret_demo_only"},
        {"tts_provider": "tencent"},
    ],
)
def test_unsafe_deployment_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(ConfigError) as caught:
        check_settings(replace(deployment_settings(), **changes))
    assert "synthetic_admin_secret" not in str(caught.value)
    assert "synthetic_worker_secret" not in str(caught.value)


def test_patient_health_and_unauthenticated_request_without_provider_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny_network(*args: object, **kwargs: object) -> None:
        pytest.fail("Deployment smoke must not contact providers")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", deny_network)
    settings = deployment_settings()
    check_settings(settings)
    with TestClient(create_app(settings=settings)) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["database"] == "supabase"
        assert client.get("/api/me/preferences").status_code == 401
        assert client.post("/internal/notifications/dispatch").status_code == 404


def test_resource_only_cli_needs_no_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["run_patient_api.py", "--check-resources"])
    assert main() == 0


def test_launcher_ignores_local_dotenv_and_uses_one_worker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import os

    import uvicorn

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("DATABASE_URL=synthetic_admin_secret\n", encoding="utf-8")
    monkeypatch.setattr(
        os,
        "environ",
        {
            "AUTH_MODE": "supabase",
            "PERSISTENCE": "supabase",
            "APP_ORIGIN": "https://synthetic.example.invalid",
            "SUPABASE_URL": "https://synthetic.supabase.co",
            "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_demo_only",
            "VISION_API_BASE_URL": "https://stage2.example.invalid",
            "MODEL_PROVIDER": "deterministic",
            "PORT": "10001",
        },
    )
    calls: list[dict[str, object]] = []

    def capture_server(app: object, **kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(uvicorn, "run", capture_server)
    monkeypatch.setattr("sys.argv", ["run_patient_api.py"])
    assert main() == 0
    assert calls[0]["port"] == 10001
    assert calls[0]["workers"] == 1
    assert calls[0]["host"] == "0.0.0.0"
