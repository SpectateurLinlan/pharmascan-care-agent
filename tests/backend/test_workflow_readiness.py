"""Synthetic release snapshots; no provider, SQL or patient writes."""

from uuid import UUID

import httpx
import pytest
from app.application.workflow_readiness import compare_release_snapshots
from app.contracts.workflow_runtime import RUNTIME_RELEASE_CONTRACT, RuntimeReleaseSnapshot
from app.domain.errors import ProviderUnavailableError
from app.infrastructure.workflow_readiness import SupabaseRuntimeReadiness
from pydantic import ValidationError

APP_HASH = "a" * 64


def release(**changes):
    return RuntimeReleaseSnapshot(
        **(
            {
                "contract_version": RUNTIME_RELEASE_CONTRACT,
                "accepted": True,
                "release_id": UUID(int=9901),
                "application_hash": APP_HASH,
                "catalog_digest": "b" * 32,
                "native_media_ready": True,
            }
            | changes
        )
    )


def test_matching_independent_releases_admit_the_current_source():
    result = compare_release_snapshots(release(), release(), expected_application_hash=APP_HASH)
    assert result.available is True and result.reason == "ready"


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"accepted": False}, "release_not_accepted"),
        ({"contract_version": "other"}, "release_contract_mismatch"),
        ({"release_id": UUID(int=9902)}, "release_target_mismatch"),
        ({"catalog_digest": "c" * 32}, "release_target_mismatch"),
        ({"application_hash": "c" * 64}, "application_mismatch"),
        ({"native_media_ready": False}, "native_media_not_ready"),
    ],
)
def test_any_unaccepted_stale_or_mismatched_release_is_refused(changes, reason):
    result = compare_release_snapshots(release(), release(**changes), expected_application_hash=APP_HASH)
    assert result.available is False and result.reason == reason


def test_missing_build_identity_cannot_be_declared_ready():
    result = compare_release_snapshots(release(), release(), expected_application_hash=None)
    assert result.available is False and result.reason == "application_unidentified"


@pytest.mark.parametrize("change", [{"accepted": "true"}, {"unexpected": "DEMO-secret"}])
def test_release_snapshot_rejects_truthy_strings_and_extra_fields(change):
    with pytest.raises(ValidationError):
        release(**change)


def test_fixed_patient_readiness_rpc_is_read_only_bounded_and_owner_bound():
    calls = []

    class Data:
        def request(self, method, path, **kwargs):
            calls.append((method, path, kwargs))
            return release().model_dump(mode="json")

    result = SupabaseRuntimeReadiness(Data()).read_release(timeout_seconds=3)
    assert result == release()
    assert calls == [
        (
            "POST",
            "/rest/v1/rpc/assistant_runtime_readiness",
            {
                "body": {},
                "timeout_seconds": 3,
            },
        )
    ]


@pytest.mark.parametrize("raw", [[], {"accepted": "true"}, {"accepted": True}, None])
def test_malformed_release_response_is_safely_unavailable(raw):
    class Data:
        def request(self, *args, **kwargs):
            return raw

    with pytest.raises(ProviderUnavailableError) as error:
        SupabaseRuntimeReadiness(Data()).read_release(timeout_seconds=3)
    assert "DEMO-secret" not in str(error.value)


def test_provider_failure_does_not_expose_raw_values_or_retry():
    calls = []

    class Data:
        def request(self, *args, **kwargs):
            calls.append(True)
            raise httpx.ConnectError("DEMO-secret-dsn")

    with pytest.raises(ProviderUnavailableError) as error:
        SupabaseRuntimeReadiness(Data()).read_release(timeout_seconds=3)
    assert calls == [True] and "DEMO-secret" not in str(error.value)


@pytest.mark.parametrize("identity", [None, {"rolbypassrls": True}, {"login": "postgres"}])
def test_restricted_probe_is_read_only_and_checks_identity_before_reading(identity):
    from app.infrastructure.workflow_verification import (
        EvidenceConnectionSettings,
        PostgresEvidenceVerifier,
        RestrictedEvidenceConnection,
    )

    from .test_workflow_verification_transport import DSN, RecordingConnection, Row

    class Connection(RecordingConnection):
        def execute(self, sql, params=None):
            if sql == "SET TRANSACTION READ ONLY":
                self.calls.append((sql, params))
                return Row({})
            if "assistant_evidence.runtime_readiness()" in sql:
                self.calls.append((sql, params))
                return Row({"result": release().model_dump(mode="json")})
            return super().execute(sql, params)

    db = Connection(identity=identity)
    verifier = PostgresEvidenceVerifier(
        RestrictedEvidenceConnection(
            EvidenceConnectionSettings(DSN),
            connect=lambda **kwargs: db,
        )
    )
    if identity:
        with pytest.raises(ProviderUnavailableError):
            verifier.read_release(timeout_seconds=3)
        assert not any("runtime_readiness()" in sql for sql, _ in db.calls)
    else:
        assert verifier.read_release(timeout_seconds=3) == release()
        assert db.calls[0] == ("SET TRANSACTION READ ONLY", None)
        assert not any("record_" in sql for sql, _ in db.calls)
    assert db.closed
