"""Offline owner-JWT transport checks; these do not prove deployed Storage policy."""

import base64
import hashlib
import json
from uuid import uuid4

import httpx
import pytest
from app.domain.errors import AuthenticationRequiredError, ProviderUnavailableError, ValidationError
from app.infrastructure.workflow_objects import SupabaseWorkflowObjects, WorkflowObjectAccess


def token(owner, role="authenticated"):
    body = base64.urlsafe_b64encode(json.dumps({"sub": str(owner), "role": role}).encode()).decode().rstrip("=")
    return f"DEMO.{body}.DEMO"


def store(handler, *, owner=None, access=None, bucket="medication-sources"):
    owner = owner or uuid4()
    return SupabaseWorkflowObjects(
        owner=owner,
        base_url="https://demo-test.supabase.co",
        bucket=bucket,
        publishable_key="sb_publishable_DEMO",
        access_token=token(owner),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        access=access or WorkflowObjectAccess(lambda *args: True),
    ), owner


def test_upload_keeps_exact_bytes_and_verifies_immutable_duplicate_without_overwrite():
    requests, saved = [], {}

    def remote(request):
        requests.append(request)
        if request.method == "POST":
            if request.url.path in saved:
                return httpx.Response(409, json={"error": "Duplicate"})
            saved[request.url.path] = request.content
            return httpx.Response(200, json={"Key": "DEMO"})
        if request.method == "DELETE":
            saved.pop(request.url.path, None)
            return httpx.Response(200)
        return httpx.Response(200, content=saved[request.url.path])

    objects, owner = store(remote)
    task, attachment, upload = uuid4(), uuid4(), uuid4()
    key = f"{owner}/workflow-originals/{task}/{attachment}"
    raw = b"DEMO original metadata and bytes"
    first = objects.put_original(owner, task, upload, raw, "image/png", object_ref=key)
    replay = objects.put_original(owner, task, upload, raw, "image/png", object_ref=key)
    assert first == replay and first.checksum == hashlib.sha256(raw).hexdigest()
    assert objects.read(owner, key) == raw
    assert all(request.headers["x-upsert"] == "false" for request in requests if request.method == "POST")
    assert requests[0].content == raw and requests[0].headers["Authorization"] == "Bearer " + token(owner)
    assert objects.delete(owner, key).state == "deleted"
    assert saved == {}


@pytest.mark.parametrize(
    "change",
    [
        {"ASSISTANT_TEST_SUPABASE_URL": "https://DEMO-other.supabase.co"},
        {"ASSISTANT_NORMAL_SUPABASE_URL": "https://demoisolated.supabase.co"},
        {"ASSISTANT_TEST_SUPABASE_URL": "https://demoisolated.supabase.co?host=other"},
        {"ASSISTANT_TEST_PUBLISHABLE_KEY": "sb_secret_DEMO"},
        {"ASSISTANT_TEST_SUPABASE_DATABASE_URL": "postgresql://postgres@db.other.supabase.co/postgres"},
    ],
)
def test_storage_target_requires_a_separate_exact_explicit_project(change):
    from .workflow_live_support import storage_target

    values = {
        "ASSISTANT_TEST_PROJECT_REF": "demoisolated",
        "ASSISTANT_TEST_SUPABASE_URL": "https://demoisolated.supabase.co",
        "ASSISTANT_NORMAL_SUPABASE_URL": "https://demonormal.supabase.co",
        "ASSISTANT_TEST_SUPABASE_DATABASE_URL": "postgresql://postgres@db.demoisolated.supabase.co/postgres",
        "ASSISTANT_TEST_PUBLISHABLE_KEY": "sb_publishable_DEMO",
    }
    assert storage_target(values)
    values.update(change)
    with pytest.raises(ValueError):
        storage_target(values)


@pytest.mark.parametrize("suffix", ["../DEMO", "DEMO?query", "DEMO%2fother", "DEMO/extra"])
def test_untrusted_object_keys_and_cross_owner_are_rejected_before_network(suffix):
    requests = []
    objects, owner = store(lambda request: requests.append(request))
    with pytest.raises((ValidationError, AuthenticationRequiredError)):
        objects.read(owner, f"{owner}/workflow-originals/{uuid4()}/{suffix}")
    with pytest.raises(AuthenticationRequiredError):
        objects.read(uuid4(), f"{owner}/workflow-originals/{uuid4()}/{uuid4()}")
    assert requests == []


def test_task_revocation_and_cleanup_authority_are_checked_before_each_object_operation():
    seen, requests = [], []

    def permit(owner, task, attachment, operation):
        seen.append(operation)
        return operation == "delete"

    objects, owner = store(
        lambda request: requests.append(request) or httpx.Response(404), access=WorkflowObjectAccess(permit)
    )
    task, attachment = uuid4(), uuid4()
    key = f"{owner}/workflow-originals/{task}/{attachment}"
    with pytest.raises(ValidationError):
        objects.read(owner, key)
    with pytest.raises(ValidationError):
        objects.put_original(owner, task, uuid4(), b"DEMO", "image/png", object_ref=key)
    assert objects.delete(owner, key).state == "deleted"
    assert seen == ["read", "put", "delete"] and len(requests) == 1


def test_lost_upload_acknowledgement_is_never_automatically_replayed():
    requests = []

    def disconnected(request):
        requests.append(request)
        raise httpx.ReadTimeout("DEMO dropped acknowledgement")

    objects, owner = store(disconnected)
    task = uuid4()
    with pytest.raises(ProviderUnavailableError):
        objects.put_original(
            owner, task, uuid4(), b"DEMO", "image/png", object_ref=f"{owner}/workflow-originals/{task}/{uuid4()}"
        )
    assert len(requests) == 1


def test_existing_different_bytes_are_not_reported_as_a_successful_upload():
    objects, owner = store(
        lambda request: (
            httpx.Response(409, json={"error": "Duplicate"})
            if request.method == "POST"
            else httpx.Response(200, content=b"DEMO other")
        )
    )
    task = uuid4()
    with pytest.raises(ProviderUnavailableError):
        objects.put_original(
            owner,
            task,
            uuid4(),
            b"DEMO original",
            "image/png",
            object_ref=f"{owner}/workflow-originals/{task}/{uuid4()}",
        )


@pytest.mark.parametrize("role", ["service_role", "anon"])
def test_non_patient_tokens_are_rejected_before_network(role):
    owner = uuid4()
    with pytest.raises(AuthenticationRequiredError):
        SupabaseWorkflowObjects(
            owner=owner,
            base_url="https://demo-test.supabase.co",
            bucket="medication-sources",
            publishable_key="sb_publishable_DEMO",
            access_token=token(owner, role),
            client=httpx.Client(transport=httpx.MockTransport(lambda request: None)),
            access=WorkflowObjectAccess(lambda *args: True),
        )
