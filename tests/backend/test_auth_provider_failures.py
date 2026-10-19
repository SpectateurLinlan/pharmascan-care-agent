"""Synthetic identity-provider responses. No network/token/provider calls."""

import io
import json
import urllib.error
from contextlib import contextmanager

import pytest
from app.transport.app_factory import create_app
from app.transport.auth import AuthBoundary, SupabaseAuthApiVerifier
from app.transport.container import build_container
from fastapi.testclient import TestClient


@pytest.mark.parametrize("status,expected", [(401, 401), (403, 401), (429, 503), (500, 503), (503, 503), (404, 503)])
def test_identity_http_failures_do_not_mislabel_outage_as_patient_logout(monkeypatch, status, expected):
    def unavailable(request, **_kwargs):
        assert request.get_method() == "GET"
        raise urllib.error.HTTPError("https://demo.invalid/auth/v1/user", status, "PRIVATE_PROVIDER", {}, io.BytesIO())

    monkeypatch.setattr("urllib.request.urlopen", unavailable)
    assert_read_refused(expected)


@pytest.mark.parametrize("failure", [TimeoutError("PRIVATE"), urllib.error.URLError("PRIVATE")])
def test_network_failures_are_503_without_patient_records_or_sensitive_error_text(monkeypatch, failure):
    def unavailable(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr("urllib.request.urlopen", unavailable)
    assert_read_refused(503)


@pytest.mark.parametrize("payload", [b"not JSON", b"{}", b"[]"])
def test_invalid_identity_provider_payload_is_not_a_patient_auth_rejection(monkeypatch, payload):
    @contextmanager
    def result(*_args, **_kwargs):
        yield io.BytesIO(payload)

    monkeypatch.setattr("urllib.request.urlopen", result)
    assert_read_refused(503)


def assert_read_refused(expected):
    verifier = SupabaseAuthApiVerifier(supabase_url="https://demo.invalid", api_key="DEMO-publishable")
    root = build_container(auth=AuthBoundary(mode="supabase", verifier=verifier))
    # Rejection must occur at identity verification, before any patient repository read.
    root.enrollment = None
    with TestClient(create_app(container=root)) as http:
        result = http.get("/api/me/medications", headers={"Authorization": "Bearer PRIVATE_DEMO_TOKEN"})
    assert result.status_code == expected
    assert result.json()["code"] == ("AUTH_REQUIRED" if expected == 401 else "PROVIDER_UNAVAILABLE")
    assert not any(value in json.dumps(result.json()) for value in ["PRIVATE", "demo.invalid"])
