"""VERIFIED LOCAL provider failures and request-scoped credential boundary."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import httpx
import pytest
from app.config import ConfigError, Settings
from app.domain.errors import AuthenticationRequiredError, ProviderUnavailableError, ValidationError
from app.infrastructure.supabase_data import SupabaseDataClient
from app.infrastructure.supabase_repos import build_supabase_repositories
from app.transport.auth import AuthBoundary, StaticTokenVerifier
from app.transport.container import build_container_from_settings

OWNER = UUID(int=1)
TOKEN = "SIMULATED-user-token"


def client_for(handler):
    return SupabaseDataClient(
        base_url="https://example.invalid",
        publishable_key="SIMULATED-publishable",
        access_token=TOKEN,
        patient_id=OWNER,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_complete_read_handles_provider_page_cap_without_skipping_rows():
    calls = []

    def handler(request):
        assert request.headers["Prefer"] == "count=exact"
        offset = int(request.url.params["offset"])
        calls.append(offset)
        # Provider chooses a smaller page than our requested200.
        batch = [{"id": i} for i in range(offset, min(offset + 3, 8))]
        return httpx.Response(200, json=batch, headers={"Content-Range": f"{offset}-{offset + len(batch) - 1}/8"})

    assert client_for(handler).all_rows("dose_events") == [{"id": i} for i in range(8)]
    assert calls == [0, 3, 6]


@pytest.mark.parametrize("header,payload", [("0-0/*", [{"id": 1}]), ("0-0/2001", [{"id": 1}]), ("*/2", [])])
def test_incomplete_unknown_or_oversized_history_is_not_a_fake_complete_result(header, payload):
    with pytest.raises(ProviderUnavailableError):
        client_for(lambda _: httpx.Response(200, json=payload, headers={"Content-Range": header})).all_rows(
            "dose_events"
        )


def test_changed_count_or_duplicate_page_aborts_complete_statistics():
    for changed in [True, False]:
        call = 0

        def handler(request, changed=changed):
            nonlocal call
            call += 1
            return httpx.Response(
                200, json=[{"id": 1}], headers={"Content-Range": f"0-0/{3 if call > 1 and changed else 2}"}
            )

        with pytest.raises(ProviderUnavailableError):
            client_for(handler).all_rows("dose_events")


@pytest.mark.parametrize(
    "status,error",
    [
        (401, AuthenticationRequiredError),
        (403, AuthenticationRequiredError),
        (400, ValidationError),
        (409, ValidationError),
        (429, ProviderUnavailableError),
        (500, ProviderUnavailableError),
        (503, ProviderUnavailableError),
    ],
)
def test_provider_failures_never_echo_response_or_token(status, error):
    def handler(request):
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert request.headers["apikey"] == "SIMULATED-publishable"
        return httpx.Response(status, json={"code": "23505", "message": TOKEN})

    with pytest.raises(error) as refused:
        client_for(handler).rows("patient_medications")
    assert TOKEN not in str(refused.value)


def test_timeout_is_unavailable_and_no_implicit_write_retry():
    calls = []

    def handler(request):
        calls.append(request.method)
        raise httpx.ReadTimeout(TOKEN, request=request)

    with pytest.raises(ProviderUnavailableError) as refused:
        client_for(handler).request("POST", "/rest/v1/patient_medications", body={})
    assert calls == ["POST"] and TOKEN not in str(refused.value)


@pytest.mark.parametrize("payload", [b"<html>unavailable</html>", b"{}", b"[1]"])
def test_malformed_provider_rows_are_refused(payload):
    with pytest.raises(ProviderUnavailableError):
        client_for(lambda _: httpx.Response(200, content=payload)).rows("patient_medications")


def test_patient_context_cannot_be_reused_for_another_owner():
    client = client_for(lambda _: pytest.fail("Foreign identity must fail before network I/O"))
    with pytest.raises(AuthenticationRequiredError):
        build_supabase_repositories(client).medications.list_for_patient(UUID(int=2))


def test_verified_context_hides_token_from_repr_and_diagnostics():
    boundary = AuthBoundary(mode="supabase", verifier=StaticTokenVerifier({TOKEN: {"sub": str(OWNER)}}))
    principal = boundary.resolve(authorization="Bearer " + TOKEN, client_id="forged")
    assert principal.access_token == TOKEN
    assert TOKEN not in repr(principal) and TOKEN not in str(principal.describe())


def test_persistent_wiring_requires_verified_auth_and_never_database_fallback():
    settings = replace(Settings.from_env(), persistence="postgres", auth_mode="demo")
    with pytest.raises(ConfigError, match="AUTH_MODE=supabase"):
        build_container_from_settings(settings)
    settings = replace(
        settings,
        auth_mode="supabase",
        database_url=None,
        supabase_url="https://example.invalid",
        supabase_publishable_key="SIMULATED-publishable",
    )
    root = build_container_from_settings(settings)
    assert root.patient_data_path == "supabase_user_jwt_rls"
    assert root.patient_factory is not None and root.admin is None and root.store is None


@pytest.mark.parametrize("key", ["sb_secret_SIMULATED", "eyJ0eXAiOiJKV1QifQ.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.SIMULATED"])
def test_service_credentials_cannot_be_mislabelled_as_publishable(key):
    from app.config import validate_publishable_key

    with pytest.raises(ConfigError) as refused:
        validate_publishable_key(key)
    assert key not in str(refused.value)


def test_idempotent_close_does_not_patch_frozen_occurrence():
    row = {
        "id": str(UUID(int=3)),
        "patient_id": str(OWNER),
        "regimen_id": str(UUID(int=4)),
        "rule_id": str(UUID(int=5)),
        "due_at": "2026-10-14T00:00:00Z",
        "status": "closed",
        "generation_key": "DEMO-key",
    }
    methods = []

    def handler(request):
        methods.append(request.method)
        return httpx.Response(200, json=[row])

    repo = build_supabase_repositories(client_for(handler)).occurrences
    occurrence = repo.get(OWNER, UUID(int=3))
    repo.update(occurrence)
    assert methods == ["GET", "GET"]


def test_occurrence_generation_ignores_only_same_owned_key_without_updating_history():
    from datetime import UTC, datetime

    from app.contracts.dto import DoseOccurrenceDTO
    from app.contracts.enums import OccurrenceStatus

    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(201)

    occurrence = DoseOccurrenceDTO(
        id=UUID(int=3),
        patient_id=OWNER,
        regimen_id=UUID(int=4),
        rule_id=UUID(int=5),
        due_at=datetime(2026, 10, 14, tzinfo=UTC),
        status=OccurrenceStatus.SCHEDULED,
        generation_key="DEMO-key",
    )
    build_supabase_repositories(client_for(handler)).occurrences.add(occurrence)
    assert len(requests) == 1 and requests[0].method == "POST"
    assert requests[0].url.params["on_conflict"] == "patient_id,generation_key"
    assert requests[0].headers["Prefer"] == "resolution=ignore-duplicates,return=minimal"
