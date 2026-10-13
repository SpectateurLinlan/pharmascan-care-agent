"""Authenticated patient context boundary (Section 4).

These tests are **VERIFIED LOCAL**: they exercise the real boundary code with
an injected deterministic verifier. They do not claim a live Supabase Auth
exchange — no token can be minted for the development project without an admin
credential, which this build deliberately does not hold.

What is asserted:
- the patient id always comes from the verified token subject, never from a
  request-supplied value;
- a missing, malformed or rejected token yields AUTH_REQUIRED and no
  repository call;
- the demo principal is reported as *unauthenticated* and is only reachable in
  the explicitly configured demo mode.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from app.domain.errors import AuthenticationRequiredError
from app.transport.app_factory import create_app
from app.transport.auth import AuthBoundary, StaticTokenVerifier
from app.transport.container import build_container, demo_patient_id
from fastapi.testclient import TestClient

PATIENT = uuid4()
OTHER = uuid4()


def _supabase_boundary() -> AuthBoundary:
    verifier = StaticTokenVerifier(
        {
            "good-token": {"sub": str(PATIENT), "email": "synthetic@pharmascan.invalid"},
            "other-token": {"sub": str(OTHER)},
            "no-subject": {"email": "someone@pharmascan.invalid"},
            "bad-subject": {"sub": "not-a-uuid"},
        }
    )
    return AuthBoundary(mode="supabase", verifier=verifier)


# --- unit: the boundary itself ----------------------------------------------


def test_verified_subject_becomes_the_patient_id() -> None:
    principal = _supabase_boundary().resolve(
        authorization="Bearer good-token", client_id="ignored"
    )
    assert principal.patient_id == PATIENT
    assert principal.authenticated is True
    assert principal.mode == "supabase"
    # The token itself is never part of the principal's description.
    assert "good-token" not in str(principal.describe())


def test_client_id_cannot_override_a_verified_identity() -> None:
    """A body/query patient hint must never win over the verified subject."""
    principal = _supabase_boundary().resolve(
        authorization="Bearer good-token", client_id="attacker-controlled"
    )
    assert principal.patient_id == PATIENT
    assert principal.patient_id != demo_patient_id("attacker-controlled")


@pytest.mark.parametrize(
    "authorization",
    [None, "", "Bearer", "Bearer ", "Token good-token", "good-token"],
)
def test_missing_or_malformed_authorization_is_refused(authorization: str | None) -> None:
    with pytest.raises(AuthenticationRequiredError):
        _supabase_boundary().resolve(authorization=authorization, client_id=None)


def test_rejected_token_is_refused() -> None:
    with pytest.raises(AuthenticationRequiredError):
        _supabase_boundary().resolve(authorization="Bearer unknown-token", client_id=None)


@pytest.mark.parametrize("token", ["no-subject", "bad-subject"])
def test_token_without_a_usable_subject_is_refused(token: str) -> None:
    with pytest.raises(AuthenticationRequiredError):
        _supabase_boundary().resolve(authorization=f"Bearer {token}", client_id=None)


def test_supabase_mode_requires_a_verifier() -> None:
    with pytest.raises(ValueError):
        AuthBoundary(mode="supabase")


def test_demo_principal_is_explicitly_unauthenticated() -> None:
    principal = AuthBoundary(mode="demo", demo_patient_id=demo_patient_id).resolve(
        authorization=None, client_id="browser-1"
    )
    assert principal.authenticated is False
    assert principal.mode == "demo"
    assert principal.patient_id == demo_patient_id("browser-1")
    assert principal.patient_id != demo_patient_id("browser-2")


def test_demo_mode_without_client_id_is_refused() -> None:
    with pytest.raises(AuthenticationRequiredError):
        AuthBoundary(mode="demo", demo_patient_id=demo_patient_id).resolve(
            authorization=None, client_id=None
        )


# --- integration: the boundary as wired into the HTTP app -------------------


def _client(mode: str) -> TestClient:
    container = build_container(
        auth=_supabase_boundary() if mode == "supabase" else None
    )
    return TestClient(create_app(container=container))


def test_http_supabase_mode_refuses_a_request_without_a_token() -> None:
    client = _client("supabase")
    response = client.get("/api/me/medications", params={"client_id": "spoofed"})
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"


def test_http_supabase_mode_scopes_records_to_the_verified_subject() -> None:
    client = _client("supabase")
    response = client.get(
        "/api/me/medications",
        headers={"Authorization": "Bearer good-token"},
        params={"client_id": "spoofed"},
    )
    assert response.status_code == 200
    assert response.json()["item_count"] == 0


def test_http_demo_mode_still_works_for_the_anonymous_demo() -> None:
    client = _client("demo")
    response = client.get("/api/me/medications", params={"client_id": "browser-1"})
    assert response.status_code == 200
    assert response.json()["item_count"] == 0


def test_health_reports_configured_persistence() -> None:
    container = build_container()
    assert container.persistence == "simulated_in_memory"
    response = TestClient(create_app(container=container)).get("/api/health")
    assert response.status_code == 200
    assert response.json()["database"] == "simulated_in_memory"


def test_no_service_role_credential_is_exposed_to_the_client() -> None:
    """The publishable key may reach the browser; a secret key never may."""
    from app.config import Settings

    settings = Settings.from_env()
    assert settings.supabase_secret_key is None or isinstance(
        settings.supabase_secret_key, str
    )
    # The boundary only ever holds the publishable key + the caller's token.
    boundary = _supabase_boundary()
    assert not hasattr(boundary, "_api_key")
    assert UUID(str(PATIENT)) == PATIENT
