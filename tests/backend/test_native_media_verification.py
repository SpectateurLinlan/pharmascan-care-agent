"""DEMO_ONLY task-independent native object protocol; no live target or original retention."""

import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.domain.errors import ProviderUnavailableError, StaleVersionError, ValidationError


def api():
    from importlib import import_module
    from importlib.util import find_spec

    assert find_spec("app.contracts.native_media_verification"), "Missing native intent contracts"
    assert find_spec("app.application.native_media_verification"), "Missing native verified store"
    return import_module("app.contracts.native_media_verification"), import_module(
        "app.application.native_media_verification"
    )


def setup(*, observer=True, owner_id=None, bucket="visual-references"):
    c, a = api()
    owner, med = owner_id or uuid4(), uuid4()
    content = b"DEMO_ONLY-native-derived-bytes"
    digest = hashlib.sha256(content).hexdigest()
    path = f"{owner}/{med}/{digest}.png"
    events = []
    objects = {}
    state = {"claimed": False, "proof": None}
    now = datetime(2026, 10, 30, tzinfo=UTC)

    class Port:
        def prepare_upload(self, o, intent):
            assert o == owner
            events.append("reserve")
            if state["proof"]:
                return state["proof"]
            if state["claimed"]:
                raise StaleVersionError("Unknown earlier native write")
            state["ticket"] = c.NativeMediaTicket(
                ticket_id=uuid4(),
                nonce=uuid4(),
                generation=1,
                operation="upload",
                target=intent.target,
                expires_at=now + timedelta(seconds=45),
            )
            return state["ticket"]

        def prepare_delete(self, o, intent):
            assert o == owner
            events.append("delete-reserve")
            state["ticket"] = c.NativeMediaTicket(
                ticket_id=uuid4(),
                nonce=uuid4(),
                generation=2,
                operation="delete",
                target=c.NativeMediaTarget.from_path(owner, intent.bucket_id, intent.object_ref),
                expires_at=now + timedelta(seconds=45),
            )
            return state["ticket"]

        def claim(self, o, ticket):
            events.append("claim")
            state["claimed"] = True

        def settle_delete(self, o, proof):
            events.append("settle-delete")

    class Store:
        bucket_id = bucket

        def put(self, key, data):
            events.append("put")
            objects.setdefault(key, data)

        def get(self, key):
            events.append("get")
            return objects[key]

        def observe(self, key):
            events.append("observe")
            return objects.get(key)

        def delete(self, key):
            events.append("delete")
            objects.pop(key, None)

    class Observer:
        def record_native_media(self, observation, *, timeout_seconds):
            events.append(observation.result)
            proof = c.VerifiedNativeMediaRef(
                ticket_id=observation.ticket_id,
                verification_id=uuid4(),
                generation=observation.generation,
                result=observation.result,
            )
            if observation.result == "bytes_verified":
                state["proof"] = proof
            return proof

    port, store, verify = Port(), Store(), Observer()
    service = a.VerifiedNativeMediaStore(
        owner=owner,
        storage=store,
        intents=port,
        verifier=verify if observer else None,
        clock=SimpleNamespace(now=lambda: now),
    )
    return c, service, owner, path, content, events, objects, state, verify


def test_native_put_verifies_actual_bytes_without_task_or_raw_original():
    _, service, _, path, content, events, _, _, _ = setup()
    assert service.put(path, content) is None
    assert events == ["reserve", "claim", "put", "get", "bytes_verified"]
    before = events.count("put")
    service.put(path, content)
    assert events.count("put") == before


def test_native_delete_requires_actual_absence_then_independent_settlement():
    _, service, _, path, content, events, objects, _, _ = setup()
    service.put(path, content)
    events.clear()
    service.delete(path)
    assert events == ["delete-reserve", "claim", "delete", "observe", "absent_after_delete", "settle-delete"]
    assert path not in objects


def test_missing_native_verifier_never_claims_or_touches_storage():
    _, service, _, path, content, events, _, _, _ = setup(observer=False)
    with pytest.raises(ProviderUnavailableError):
        service.put(path, content)
    with pytest.raises(ProviderUnavailableError):
        service.delete(path)
    assert not events


@pytest.mark.parametrize("kind", ["owner", "path", "bytes"])
def test_native_target_cannot_substitute_foreign_key_or_bytes(kind):
    _, service, owner, path, content, events, _, _, _ = setup()
    if kind == "owner":
        path = path.replace(str(owner), str(uuid4()))
    elif kind == "path":
        path += "?untrusted"
    else:
        content += b"different"
    with pytest.raises((ValueError, ValidationError)):
        service.put(path, content)
    assert not events


def test_read_after_put_mismatch_is_unknown_not_published_or_replayed():
    _, service, _, path, content, events, objects, state, _ = setup()
    objects[path] = b"DEMO-other-object"
    with pytest.raises(ProviderUnavailableError):
        service.put(path, content)
    assert events[-1] == "outcome_unknown" and state["proof"] is None
    with pytest.raises(StaleVersionError):
        service.put(path, content)
    assert events.count("put") == 1


def test_native_observer_result_is_correlated_to_claimed_ticket(monkeypatch):
    c, service, _, path, content, _, _, _, verify = setup()
    monkeypatch.setattr(
        verify,
        "record_native_media",
        lambda observation, **k: c.VerifiedNativeMediaRef(
            ticket_id=uuid4(), verification_id=uuid4(), generation=observation.generation, result=observation.result
        ),
    )
    with pytest.raises(ProviderUnavailableError):
        service.put(path, content)


def test_agent_execution_cannot_use_unbound_native_mutation_authority():
    from app.contracts.agent_execution import current_execution

    _, service, _, path, content, events, _, _, _ = setup()
    token = current_execution.set(SimpleNamespace())
    try:
        with pytest.raises(ProviderUnavailableError):
            service.put(path, content)
        with pytest.raises(ProviderUnavailableError):
            service.delete(path)
    finally:
        current_execution.reset(token)
    assert not events


def test_native_bridge_preserves_owned_historical_reads_without_claiming_new_proof():
    _, service, owner, _, _, events, objects, _, _ = setup()
    legacy = f"{owner}/DEMO-historical-source.png"
    objects[legacy] = b"DEMO retained bytes"
    assert service.get(legacy) == b"DEMO retained bytes"
    assert events == ["get"]
    with pytest.raises(ValidationError):
        service.get(f"{uuid4()}/DEMO-historical-source.png")
    with pytest.raises(ValidationError):
        service.get(f"{owner}/%2e%2e/other.png")
