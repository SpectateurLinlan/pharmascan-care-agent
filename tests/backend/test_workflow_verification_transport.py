"""Real verifier validation over a recording DB wire; never a SQL execution claim."""

import importlib
import importlib.util
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.contracts.workflow_verification import StorageObservation
from app.domain.errors import ProviderUnavailableError

DSN = "postgresql://assistant_evidence_login:DEMO-evidence-secret@db.demo.invalid:5432/DEMO_test"


def module():
    name = "app.infrastructure.workflow_verification"
    assert importlib.util.find_spec(name), "Missing approved restricted verifier adapter"
    return importlib.import_module(name)


def observation():
    return StorageObservation(
        ticket_id=uuid4(),
        nonce=uuid4(),
        generation=1,
        result="bytes_verified",
        checksum="a" * 64,
        byte_size=42,
        observed_at=datetime(2026, 10, 28, tzinfo=UTC),
    )


class Row:
    def __init__(self, value):
        self.value = value

    def fetchone(self):
        return self.value


class RecordingConnection:
    def __init__(self, *, identity=None, failure=False, reply=None):
        self.identity = {
            "login": "assistant_evidence_login",
            "role": "assistant_evidence_login",
            "rolsuper": False,
            "rolcreatedb": False,
            "rolcreaterole": False,
            "rolreplication": False,
            "rolbypassrls": False,
            "rolinherit": False,
            "has_memberships": False,
        } | (identity or {})
        self.failure, self.reply = failure, reply
        self.calls, self.closed = [], False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def transaction(self):
        return self

    def close(self):
        self.closed = True

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if "session_user" in sql:
            return Row(self.identity)
        if "record_storage_observation" in sql:
            if self.failure:
                raise RuntimeError("DEMO-evidence-secret DEMO-private-body")
            body = params[0].obj
            return Row(
                {
                    "result": self.reply
                    or {
                        "ticket_id": body["ticket_id"],
                        "verification_id": str(uuid4()),
                        "generation": body["generation"],
                        "result": body["result"],
                    }
                }
            )
        assert "set_config" in sql
        return Row({})


def build(**kwargs):
    api = module()
    calls, db = [], RecordingConnection(**kwargs)

    def connect(*args, **options):
        calls.append((args, options))
        return db

    settings = api.EvidenceConnectionSettings(DSN)
    connection = api.RestrictedEvidenceConnection(settings, connect=connect)
    return api.PostgresEvidenceVerifier(connection), settings, calls, db


def test_constructing_verifier_does_not_connect():
    verifier, settings, calls, db = build()
    assert calls == [] and db.calls == []
    assert "DEMO-evidence-secret" not in repr(settings) + repr(verifier)


@pytest.mark.parametrize(
    "identity",
    [
        {"login": "postgres"},
        {"role": "authenticated"},
        {"rolsuper": True},
        {"rolcreatedb": True},
        {"rolcreaterole": True},
        {"rolreplication": True},
        {"rolbypassrls": True},
        {"rolinherit": True},
        {"has_memberships": True},
        {"rolsuper": "false"},
    ],
)
def test_wrong_session_identity_stops_before_observation(identity):
    verifier, _, calls, db = build(identity=identity)
    with pytest.raises(ProviderUnavailableError):
        verifier.record_storage(observation(), timeout_seconds=3)
    assert len(calls) == 1 and db.closed
    assert not any("record_storage_observation" in sql for sql, _ in db.calls)


def test_timeout_uses_remaining_budget_and_never_retries_write():
    verifier, _, calls, db = build(failure=True)
    with pytest.raises(ProviderUnavailableError) as error:
        verifier.record_storage(observation(), timeout_seconds=3)
    assert len(calls) == 1 and calls[0][1]["connect_timeout"] <= 3
    assert calls[0][1]["sslmode"] == "verify-full"
    assert calls[0][1]["options"].startswith("-c statement_timeout=")
    assert sum("record_storage_observation" in sql for sql, _ in db.calls) == 1
    assert "DEMO-evidence-secret" not in str(error.value) and "DEMO-private-body" not in str(error.value)
    assert db.closed


@pytest.mark.parametrize("remaining", [0, -1, 0.5, True, float("inf"), float("nan")])
def test_exhausted_or_invalid_budget_never_opens_connection(remaining):
    verifier, _, calls, _ = build()
    with pytest.raises(ProviderUnavailableError):
        verifier.record_storage(observation(), timeout_seconds=remaining)
    assert calls == []


def test_only_fixed_observation_function_receives_bound_json():
    verifier, _, _, db = build()
    data = observation()
    result = verifier.record_storage(data, timeout_seconds=3)
    assert result.ticket_id == data.ticket_id and result.result == "bytes_verified"
    sql, params = next(row for row in db.calls if "record_storage_observation" in row[0])
    assert sql == "SELECT assistant_evidence.record_storage_observation(%s) AS result"
    assert params[0].obj == data.model_dump(mode="json")
    assert db.closed


@pytest.mark.parametrize(
    "reply",
    [
        {"ticket_id": str(uuid4()), "verification_id": str(uuid4()), "generation": 1, "result": "bytes_verified"},
        {"body": "DEMO-private-body"},
    ],
)
def test_malformed_or_wrong_bound_proof_is_not_accepted(reply):
    verifier, _, _, db = build(reply=reply)
    with pytest.raises(ProviderUnavailableError) as error:
        verifier.record_storage(observation(), timeout_seconds=3)
    assert "DEMO-private-body" not in str(error.value) and db.closed


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://postgres:DEMO@db.demo.invalid/DEMO",
        "postgresql://assistant_evidence_login:DEMO@db.demo.invalid/DEMO?sslmode=disable",
        "postgresql://assistant_evidence_login:DEMO@db.demo.invalid/DEMO?options=-c%20role=postgres",
        "postgresql://assistant_evidence_login@db.demo.invalid/DEMO",
        "service=DEMO",
        "",
    ],
)
def test_invalid_or_privileged_dsn_is_refused_without_connection(dsn):
    api = module()
    with pytest.raises(ValueError) as error:
        api.EvidenceConnectionSettings(dsn)
    assert "DEMO@" not in str(error.value)


def test_secret_configuration_is_env_only_and_never_defaults_to_database_url(monkeypatch, tmp_path):
    from app import config

    file = tmp_path / "DEMO-config.env"
    file.write_text(f"ASSISTANT_EVIDENCE_DSN={DSN}\nDATABASE_URL={DSN}\n", encoding="utf-8")
    monkeypatch.setattr(config.os, "environ", {})
    settings = config.Settings.from_env(env_file=file)
    assert getattr(settings, "assistant_evidence_dsn", "MISSING") is None
    monkeypatch.setattr(config.os, "environ", {"ASSISTANT_EVIDENCE_DSN": DSN})
    settings = config.Settings.from_env(env_file=file)
    assert settings.assistant_evidence_dsn == DSN
    assert DSN not in repr(settings)


def test_loopback_disabled_tls_does_not_request_a_system_trust_store():
    api = module()
    options = []
    db = RecordingConnection()

    def connect(**kwargs):
        options.append(kwargs)
        return db

    settings = api.EvidenceConnectionSettings(
        "postgresql://assistant_evidence_login:DEMO@127.0.0.1:55439/mt_assistant_test_DEMO?sslmode=disable"
    )
    api.PostgresEvidenceVerifier(api.RestrictedEvidenceConnection(settings, connect=connect)).record_storage(
        observation(), timeout_seconds=3
    )
    assert options[0]["sslmode"] == "disable" and options[0].get("sslrootcert") != "system"


def test_multiple_hosts_cannot_multiply_the_connection_deadline():
    api = module()
    with pytest.raises(ValueError):
        api.EvidenceConnectionSettings(DSN.replace("db.demo.invalid", "db.demo.invalid,other.demo.invalid"))


def test_elapsed_connection_budget_prevents_any_proof_command():
    api = module()
    db = RecordingConnection()
    clock_values = iter([0.0, 4.0])
    connection = api.RestrictedEvidenceConnection(
        api.EvidenceConnectionSettings(DSN), connect=lambda **kwargs: db, clock=lambda: next(clock_values)
    )
    with pytest.raises(ProviderUnavailableError):
        api.PostgresEvidenceVerifier(connection).record_storage(observation(), timeout_seconds=3)
    assert db.calls == [] and db.closed
