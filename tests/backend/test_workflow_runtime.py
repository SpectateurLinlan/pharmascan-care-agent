"""Synthetic browser runtime is opt-in and cannot call a model or persist a patient plan."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


def test_workflow_runtime_requires_explicit_opt_in(monkeypatch):
    from .assistant_workflow_runtime import create_app
    monkeypatch.delenv("MEDITHREAD_LOCAL_ACCEPTANCE", raising=False)
    with pytest.raises(RuntimeError):
        create_app()


def test_workflow_runtime_is_memory_only_and_handles_enrollment_without_model(monkeypatch):
    from .assistant_workflow_runtime import create_app
    monkeypatch.setenv("MEDITHREAD_LOCAL_ACCEPTANCE", "1")
    with TestClient(create_app()) as client:
        params = {"client_id": "DEMO-workflow-browser"}
        assert client.get("/api/health").json()["database"] == "simulated_in_memory"
        assert client.get("/api/agent/workflows/capabilities", params=params).json()["enabled"]
        response = client.post("/api/agent/workflows/messages", params=params, json={
            "workspace_id": str(uuid4()), "text": "Add a medication", "client_turn_id": str(uuid4()),
        })
        assert response.status_code == 200 and response.json()["workflow"]["state"] == "choose_method"
        assert client.get("/api/me/medications", params=params).json()["medications"] == []
