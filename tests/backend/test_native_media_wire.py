"""Recording patient/technical wires, not database or Storage acceptance."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from app.contracts.native_media_verification import (
    NativeMediaObservation,
    NativeMediaTarget,
    NativeMediaTicket,
    NativeMediaUploadIntent,
)
from app.domain.errors import AuthenticationRequiredError, ProviderUnavailableError
from app.infrastructure.supabase_data import SupabaseDataClient


def port(owner, response, calls):
    from importlib import import_module
    from importlib.util import find_spec

    assert find_spec("app.infrastructure.native_media_verification"), "Missing fixed native intent adapter"

    def reply(request):
        calls.append(request)
        return httpx.Response(200, json=response)

    data = SupabaseDataClient(
        base_url="https://demo.invalid",
        publishable_key="sb_publishable_DEMO",
        access_token="DEMO-native-patient",
        patient_id=owner,
        client=httpx.Client(transport=httpx.MockTransport(reply)),
    )
    return import_module("app.infrastructure.native_media_verification").SupabaseNativeMediaIntents(data)


def request_fixture():
    owner, med = uuid4(), uuid4()
    checksum = hashlib.sha256(b"DEMO").hexdigest()
    target = NativeMediaTarget.from_path(owner, "visual-references", f"{owner}/{med}/{checksum}.png", byte_size=4)
    intent = NativeMediaUploadIntent(operation_id=uuid4(), target=target)
    ticket = NativeMediaTicket(
        ticket_id=intent.operation_id,
        nonce=uuid4(),
        generation=1,
        operation="upload",
        target=target,
        expires_at=datetime.now(UTC) + timedelta(seconds=45),
    )
    return owner, intent, ticket


def test_native_patient_reservation_is_fixed_owned_and_has_no_task_or_sql():
    owner, intent, ticket = request_fixture()
    calls = []
    p = port(owner, {"result": {"ticket": ticket.model_dump(mode="json"), "proof": None}}, calls)
    assert p.prepare_upload(owner, intent) == ticket
    assert calls[0].url.path == "/rest/v1/rpc/assistant_native_media_command"
    body = json.loads(calls[0].content)["p_command"]
    assert body["kind"] == "prepare_upload" and "task_id" not in body and "sql" not in body
    with pytest.raises(AuthenticationRequiredError):
        p.prepare_upload(uuid4(), intent)
    assert len(calls) == 1


@pytest.mark.parametrize("bad", ["id", "owner", "checksum"])
def test_native_response_must_match_the_exact_requested_target(bad):
    owner, intent, ticket = request_fixture()
    raw = ticket.model_dump(mode="json")
    if bad == "id":
        raw["ticket_id"] = str(uuid4())
    elif bad == "owner":
        raw["target"]["owner"] = str(uuid4())
    else:
        raw["target"]["checksum"] = "a" * 64
    p = port(owner, {"result": {"ticket": raw, "proof": None}}, [])
    with pytest.raises(ProviderUnavailableError):
        p.prepare_upload(owner, intent)


def test_native_observer_adds_one_fixed_function_and_never_a_clinical_query():
    from app.infrastructure.workflow_verification import (
        EvidenceConnectionSettings,
        PostgresEvidenceVerifier,
        RestrictedEvidenceConnection,
    )

    from .test_workflow_verification_transport import DSN, RecordingConnection, Row

    class DB(RecordingConnection):
        def execute(self, sql, params=None):
            if "record_native_media_observation" in sql:
                self.calls.append((sql, params))
                body = params[0].obj
                return Row(
                    {
                        "result": {
                            "family": "native_object",
                            "ticket_id": body["ticket_id"],
                            "verification_id": str(uuid4()),
                            "generation": body["generation"],
                            "result": body["result"],
                        }
                    }
                )
            return super().execute(sql, params)

    db = DB()
    verifier = PostgresEvidenceVerifier(
        RestrictedEvidenceConnection(EvidenceConnectionSettings(DSN), connect=lambda **kwargs: db)
    )
    assert hasattr(verifier, "record_native_media"), "Missing task-independent technical observation"
    observation = NativeMediaObservation(
        ticket_id=uuid4(),
        nonce=uuid4(),
        generation=1,
        result="bytes_verified",
        observed_at=datetime.now(UTC),
        checksum="a" * 64,
        byte_size=4,
        bucket_id="visual-references",
    )
    result = verifier.record_native_media(observation, timeout_seconds=3)
    assert result.ticket_id == observation.ticket_id
    command = [sql for sql, _ in db.calls if "record_native_media_observation" in sql]
    assert command == ["SELECT assistant_evidence.record_native_media_observation(%s) AS result"]
    assert not any("regimen_versions" in sql or "SET ROLE" in sql for sql, _ in db.calls)
