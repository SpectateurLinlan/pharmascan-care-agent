"""Hosted Storage absence is distinct from permission and service failures."""

import base64
import json
from uuid import uuid4

import httpx
import pytest

from app.domain.errors import NotFoundError, ProviderUnavailableError
from app.infrastructure.evidence_repos import SupabaseImageStore
from app.infrastructure.workflow_objects import SupabaseWorkflowObjects, WorkflowObjectAccess
from app.infrastructure.storage_responses import object_is_absent


@pytest.mark.parametrize("payload", [[], None, {}, {"statusCode": "404"},
                                     {"statusCode": "404", "code": "NoSuchBucket"},
                                     {"statusCode": "403", "code": "NoSuchKey"}])
def test_unknown_or_permission_errors_do_not_prove_absence(payload):
    assert object_is_absent(httpx.Response(400, json=payload)) is False
    assert object_is_absent(httpx.Response(403, json={"statusCode": "404", "code": "NoSuchKey"})) is False


def test_non_json_errors_do_not_prove_absence():
    assert object_is_absent(httpx.Response(400, text="upstream unavailable")) is False


@pytest.mark.parametrize("adapter", ["original", "native"])
def test_absence_observation_bypasses_cached_object_bytes(adapter):
    owner, task, attachment = uuid4(), uuid4(), uuid4()
    claims = base64.urlsafe_b64encode(json.dumps({"sub": str(owner), "role": "authenticated"}).encode()).decode().rstrip("=")
    token = f"DEMO.{claims}.DEMO"
    nonces = []

    def respond(request):
        nonce = request.url.params.get("cacheNonce")
        if nonce:
            nonces.append(nonce)
            return httpx.Response(400, json={"statusCode": "404", "code": "NoSuchKey"})
        return httpx.Response(200, content=b"cached bytes before deletion")

    transport = httpx.MockTransport(respond)
    key = f"{owner}/workflow-originals/{task}/{attachment}"
    if adapter == "native":
        store = SupabaseImageStore(base_url="https://example.invalid", publishable_key="sb_publishable_DEMO", access_token=token, patient_id=owner, client_factory=lambda: httpx.Client(transport=transport))
        assert store.observe(key) is None
        assert store.observe(key) is None
    else:
        store = SupabaseWorkflowObjects(owner=owner, base_url="https://example.invalid", bucket="medication-sources", publishable_key="sb_publishable_DEMO", access_token=token, client=httpx.Client(transport=transport), access=WorkflowObjectAccess(lambda *args: True))
        for _ in range(2):
            with pytest.raises(NotFoundError):
                store.read(owner, key)
    assert len(nonces) == 2 and nonces[0] != nonces[1]


@pytest.mark.parametrize("adapter", ["original", "native"])
@pytest.mark.parametrize("operation", ["read", "delete"])
@pytest.mark.parametrize("absent", [True, False])
def test_storage_wrapped_absence_preserves_denial(adapter, operation, absent):
    owner, task, attachment = uuid4(), uuid4(), uuid4()
    claims = base64.urlsafe_b64encode(
        json.dumps({"sub": str(owner), "role": "authenticated"}).encode()
    ).decode().rstrip("=")
    token = f"DEMO.{claims}.DEMO"
    payload = ({"statusCode": "404", "error": "not_found", "code": "NoSuchKey"}
               if absent else {"statusCode": "403", "error": "AccessDenied", "code": "AccessDenied"})
    transport = httpx.MockTransport(lambda _: httpx.Response(400, json=payload))
    client = httpx.Client(transport=transport)
    key = f"{owner}/workflow-originals/{task}/{attachment}"
    if adapter == "original":
        store = SupabaseWorkflowObjects(
            owner=owner, base_url="https://example.invalid", bucket="medication-sources",
            publishable_key="sb_publishable_DEMO", access_token=token, client=client,
            access=WorkflowObjectAccess(lambda *args: True),
        )
        call = lambda: getattr(store, operation)(owner, key)
        if operation == "read" and absent:
            with pytest.raises(NotFoundError):
                call()
            return
    else:
        store = SupabaseImageStore(
            base_url="https://example.invalid", publishable_key="sb_publishable_DEMO",
            access_token=token, patient_id=owner, client_factory=lambda: client,
        )
        call = lambda: store.observe(key) if operation == "read" else store.delete(key)
    if absent:
        result = call()
        assert result is None or result.state == "deleted"
    else:
        with pytest.raises(ProviderUnavailableError):
            call()
