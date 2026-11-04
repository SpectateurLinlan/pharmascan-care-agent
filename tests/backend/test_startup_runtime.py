import pytest
from fastapi.testclient import TestClient

from .assistant_startup_runtime import create_startup_app


def test_startup_fixture_requires_explicit_opt_in(monkeypatch):
    monkeypatch.delenv("MEDITHREAD_LOCAL_ACCEPTANCE", raising=False)
    with pytest.raises(RuntimeError):
        create_startup_app()


def test_startup_fixture_has_three_owned_plans_and_no_foreign_owner_data(monkeypatch):
    monkeypatch.setenv("MEDITHREAD_LOCAL_ACCEPTANCE", "1")
    with TestClient(create_startup_app()) as client:
        own = client.get("/api/me/medications", params={"client_id": "DEMO-startup"})
        assert own.status_code == 200 and len(own.json()["medications"]) == 3
        foreign = client.get("/api/me/medications", params={"client_id": "DEMO-startup-foreign"})
        assert foreign.json()["medications"] == []
