"""DEMO_ONLY exact source/native byte proofs; no SQL or provider acceptance."""

import hashlib
import importlib
from uuid import uuid4, uuid5

import pytest
from app.domain.errors import ProviderUnavailableError, StaleVersionError
from app.infrastructure.evidence_images import patient_reference_image
from app.infrastructure.evidence_repos import MemoryImageStore

from .test_verified_workflow_originals import harness as original_harness


def setup_copy():
    raw_service, raw_port, _verifier, state, clock, originals, controls, context, source, content = original_harness(
        kind="reference_photo"
    )
    raw_service.save(context, source.id, source.upload_id, content)
    context = context.model_copy(update={"revision": controls.get(context.owner, context.task_id).revision})
    contracts = importlib.import_module("app.contracts.workflow_media_storage")
    module = importlib.import_module("app.infrastructure.workflow_media_storage")
    service_module = importlib.import_module("app.application.workflow_media_storage")
    normalized = patient_reference_image(content)
    digest = hashlib.sha256(normalized).hexdigest()
    med = uuid4()
    target = contracts.MediaCopyTarget(
        owner=context.owner,
        medication_id=med,
        native_id=uuid5(med, digest),
        media_kind="photo",
        checksum=digest,
        content_type="image/png",
        byte_size=len(normalized),
    )
    port = module.MemoryMediaCopyTickets(state=state, clock=clock, originals=raw_port, controls=controls)
    verifier = module.MemoryMediaCopyVerifier(state=state, clock=clock)
    native = MemoryImageStore()
    service = service_module.MediaCopyVerificationService(
        tickets=port,
        originals=raw_port,
        source_storage=raw_service._storage,
        target_storage=native,
        verifier=verifier,
        clock=clock,
        normalize=patient_reference_image,
    )
    return service, port, verifier, state, clock, originals, context, source, content, target, native, normalized


def test_copy_proof_verifies_actual_normalized_bytes_without_native_registration():
    service, port, _verifier, state, _clock, _originals, context, source, content, target, native, normalized = (
        setup_copy()
    )
    before_receipts = dict(state.business_receipts)
    proof = service.copy(context, source.id, target)
    ticket = port.read_verified(context.owner, proof)
    assert ticket.source_checksum == hashlib.sha256(content).hexdigest()
    assert ticket.target == target and native.get(target.object_ref) == normalized
    assert len(state.originals) == 1 and state.business_receipts == before_receipts
    assert not state.deleting_originals and proof.result == "bytes_verified"


def test_native_copy_ack_cannot_publish_a_proof_or_replace_saved_original():
    service, _port, _verifier, state, _clock, originals, context, source, content, target, _native, _normalized = (
        setup_copy()
    )

    class FalseAck:
        bucket_id = "visual-references"

        def put(self, *args):
            pass

        def get(self, *args):
            return b"DEMO wrong native bytes"

    service._target_storage = FalseAck()
    with pytest.raises(ProviderUnavailableError):
        service.copy(context, source.id, target)
    assert originals.get(context.owner, context.task_id, source.id).state == "saved"
    assert service._source_storage.read(context.owner, source.object_ref) == content
    assert len(state.media_storage_verifications) == 1
    assert all(proof.result == "outcome_unknown" for proof in state.media_storage_verifications.values())


def test_native_copy_cannot_adopt_an_unrelated_transformation_checksum():
    service, _port, _verifier, state, _clock, _originals, context, source, _content, target, _native, _normalized = (
        setup_copy()
    )
    target = target.model_copy(update={"checksum": "b" * 64})
    with pytest.raises((ValueError, StaleVersionError)):
        service.copy(context, source.id, target)
    assert not state.media_storage_tickets


def test_original_delete_exclusion_blocks_new_native_copy_before_storage_io():
    service, _port, _verifier, state, _clock, _originals, context, source, _content, target, _native, _normalized = (
        setup_copy()
    )
    state.deleting_originals.add((context.owner, source.id))
    with pytest.raises(StaleVersionError):
        service.copy(context, source.id, target)
    assert not state.media_storage_tickets


def test_native_copy_proof_cannot_be_used_as_an_original_upload_proof():
    service, _port, _verifier, state, _clock, _originals, context, source, _content, target, _native, _normalized = (
        setup_copy()
    )
    proof = service.copy(context, source.id, target)
    with pytest.raises(ProviderUnavailableError):
        service._originals.read_verified(context.owner, proof)
    assert proof.verification_id not in state.storage_verifications


def test_cancelled_copy_can_settle_technical_proof_but_cannot_authorize_registration():
    service, port, _verifier, state, _clock, _originals, context, source, _content, target, native, _normalized = (
        setup_copy()
    )
    put = native.put

    def cancel_during_put(path, data):
        put(path, data)
        port._controls.revoke(context.owner, context.task_id, context.revision)

    native.put = cancel_during_put
    proof = service.copy(context, source.id, target)
    assert proof.result == "bytes_verified"
    assert state.media_storage_tickets[proof.ticket_id].state == "settled"
    with pytest.raises(StaleVersionError):
        port.assert_current_copy(context, proof)
    assert not state.business_receipts


@pytest.mark.parametrize("wrong_identity", [False, True])
def test_native_copy_verifier_uses_only_its_fixed_restricted_command(wrong_identity):
    from app.contracts.workflow_media_storage import MediaStorageObservation
    from app.infrastructure.workflow_verification import (
        EvidenceConnectionSettings,
        PostgresEvidenceVerifier,
        RestrictedEvidenceConnection,
    )

    from .test_workflow_verification_transport import DSN, RecordingConnection, Row, observation

    original = observation()
    value = MediaStorageObservation(**original.model_dump(), source_checksum="c" * 64, bucket_id="visual-references")

    class MediaConnection(RecordingConnection):
        def execute(self, sql, params=None):
            if "record_media_storage_observation" in sql:
                self.calls.append((sql, params))
                body = params[0].obj
                return Row(
                    {
                        "result": {
                            "ticket_id": body["ticket_id"],
                            "verification_id": str(uuid4()),
                            "generation": body["generation"],
                            "result": body["result"],
                            "family": "native_media",
                        }
                    }
                )
            return super().execute(sql, params)

    db = MediaConnection(identity={"login": "postgres"} if wrong_identity else None)
    verifier = PostgresEvidenceVerifier(
        RestrictedEvidenceConnection(EvidenceConnectionSettings(DSN), connect=lambda **kwargs: db)
    )
    if wrong_identity:
        with pytest.raises(ProviderUnavailableError):
            verifier.record_media_storage(value, timeout_seconds=3)
        assert not any("record_media_storage_observation" in sql for sql, _params in db.calls)
    else:
        proof = verifier.record_media_storage(value, timeout_seconds=3)
        assert proof.ticket_id == value.ticket_id and proof.family == "native_media"
        commands = [sql for sql, _params in db.calls if "record_" in sql]
        assert commands == ["SELECT assistant_evidence.record_media_storage_observation(%s) AS result"]
    assert db.closed


def test_independent_patient_can_adopt_a_verified_copy_after_its_chat_run_expires():
    from app.contracts.workflow_persistence import RunWriteBinding
    from app.infrastructure.durable_agent_runs import MemoryDurableRunControl

    from .test_durable_agent_runs import claimed

    service, port, _verifier, state, clock, _originals, context, source, _content, target, _native, _normalized = (
        setup_copy()
    )
    run = claimed(MemoryDurableRunControl(clock=clock, state=state), context.owner)
    binding = RunWriteBinding(run_id=run.run_id, epoch=run.epoch)
    proof = service.copy(context, source.id, target, run_binding=binding)
    clock.advance(seconds=46)
    assert port.assert_current_copy(context, proof).target == target


def test_remote_copy_reads_only_the_owned_independent_proof_through_a_fixed_command():
    import json

    import httpx
    from app.domain.errors import AuthenticationRequiredError
    from app.infrastructure.supabase_data import SupabaseDataClient

    service, local, _verifier, _state, _clock, _originals, context, source, _content, target, _native, _normalized = (
        setup_copy()
    )
    proof = service.copy(context, source.id, target)
    ticket = local.read_verified(context.owner, proof)
    calls = []

    def respond(request):
        calls.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"result": ticket.model_dump(mode="json")})

    data = SupabaseDataClient(
        base_url="https://example.invalid",
        publishable_key="sb_publishable_DEMO",
        access_token="DEMO-token",
        patient_id=context.owner,
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    cls = importlib.import_module("app.infrastructure.workflow_media_storage").SupabaseMediaCopyTickets
    remote = cls(data=data)
    assert remote.read_verified(context.owner, proof) == ticket
    assert calls == [
        (
            "/rest/v1/rpc/assistant_media_copy_command",
            {"p_command": {"kind": "read_verified", "reference": proof.model_dump(mode="json")}},
        )
    ]
    calls.clear()
    with pytest.raises(AuthenticationRequiredError):
        remote.read_verified(uuid4(), proof)
    assert calls == []


def test_native_copy_transport_failure_is_unknown_and_does_not_expose_provider_details():
    service, _port, _verifier, state, _clock, originals, context, source, _content, target, _native, _normalized = (
        setup_copy()
    )

    class FailedTransport:
        bucket_id = "visual-references"

        def put(self, *args):
            raise RuntimeError("DEMO-private-provider-secret")

    service._target_storage = FailedTransport()
    with pytest.raises(ProviderUnavailableError) as caught:
        service.copy(context, source.id, target)
    assert "DEMO-private-provider-secret" not in str(caught.value)
    assert originals.get(context.owner, context.task_id, source.id).state == "saved"
    assert len(state.media_storage_verifications) == 1
    assert all(proof.result == "outcome_unknown" for proof in state.media_storage_verifications.values())


def test_native_copy_cannot_attest_bytes_in_another_storage_bucket():
    service, _port, _verifier, state, _clock, _originals, context, source, _content, target, _native, normalized = (
        setup_copy()
    )

    class WrongBucket:
        bucket_id = "medication-sources"

        def put(self, *args):
            pass

        def get(self, *args):
            return normalized

    service._target_storage = WrongBucket()
    with pytest.raises(ProviderUnavailableError):
        service.copy(context, source.id, target)
    assert not state.media_storage_tickets
