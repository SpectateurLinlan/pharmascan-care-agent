"""Offline owner-JWT adapter contract. No real SQL execution evidence."""

import json
from uuid import uuid4

import httpx
import pytest
from app.domain.errors import AuthenticationRequiredError, ProviderUnavailableError, StaleVersionError
from app.infrastructure.enrollment_operations import SupabaseEnrollmentWritePort
from app.infrastructure.supabase_data import SupabaseDataClient

from .test_workflow_enrollment_operations import values


def port(owner, remote):
    return SupabaseEnrollmentWritePort(
        SupabaseDataClient(
            base_url="https://demo-test.supabase.co",
            publishable_key="sb_publishable_DEMO",
            access_token="DEMO-owner-token",
            patient_id=owner,
            client=httpx.Client(transport=httpx.MockTransport(remote)),
        )
    )


def prepared(h):
    owner = h.owner_ids["A"]
    return h.container.enrollment.prepare_draft(patient_id=owner, draft=values().fields.draft).model_copy(
        update={"workflow_task_id": uuid4(), "workflow_revision": 1}
    )


def test_one_closed_rpc_uses_owner_jwt_and_binds_the_task_and_generation(workflow):
    h = workflow
    owner = h.owner_ids["A"]
    draft = prepared(h)
    calls = []
    key = uuid4()
    result = {
        "regimen_id": str(draft.result.regimen.id),
        "medication_id": str(draft.result.medication.id),
        "source_id": str(draft.source.id),
        "workflow_task_id": str(draft.workflow_task_id),
        "version_no": 1,
        "binding_digest": "0" * 64,
    }

    def remote(request):
        calls.append(request)
        return httpx.Response(200, json={"result": result})

    receipt = port(owner, remote).create_once(owner, key, "0" * 64, draft, expected_revision=7)
    assert receipt.regimen_id == draft.result.regimen.id and len(calls) == 1
    request = calls[0]
    body = json.loads(request.content)
    assert request.url.path == "/rest/v1/rpc/assistant_enrollment_prepare_once"
    assert request.headers["Authorization"] == "Bearer DEMO-owner-token"
    assert body["p_task_id"] == str(draft.workflow_task_id) and body["p_expected_clinical_revision"] == 7
    assert body["p_expected_task_revision"] == 1 and "owner" not in body and "patient_id" not in body


def test_cross_owner_calls_are_denied_before_any_http_request(workflow):
    h = workflow
    calls = []

    def remote(request):
        calls.append(request)
        return httpx.Response(200, json=[])

    with pytest.raises(AuthenticationRequiredError):
        port(h.owner_ids["A"], remote).revision(h.owner_ids["B"])
    assert not calls


def test_unready_photo_or_unbound_preparation_cannot_reach_the_draft_rpc(workflow):
    h = workflow
    calls = []
    draft = prepared(h)

    def remote(request):
        calls.append(request)
        return httpx.Response(200, json=[])

    writer = port(h.owner_ids["A"], remote)
    for candidate in (
        draft.model_copy(update={"workflow_task_id": None}),
        draft.model_copy(update={"attachment_ids": (uuid4(),)}),
    ):
        with pytest.raises(ProviderUnavailableError):
            writer.create_once(h.owner_ids["A"], uuid4(), "0" * 64, candidate, expected_revision=0)
    assert not calls


def test_wrong_task_response_and_malformed_error_are_not_treated_as_success(workflow):
    h = workflow
    draft = prepared(h)
    for body in (
        {"error": {}},
        {
            "result": {
                "regimen_id": str(draft.result.regimen.id),
                "medication_id": str(draft.result.medication.id),
                "source_id": str(draft.source.id),
                "workflow_task_id": str(uuid4()),
                "binding_digest": "0" * 64,
            }
        },
    ):
        with pytest.raises(ProviderUnavailableError):
            port(h.owner_ids["A"], lambda request, body=body: httpx.Response(200, json=body)).create_once(
                h.owner_ids["A"], uuid4(), "0" * 64, draft, expected_revision=0
            )


def test_stale_generation_is_a_typed_conflict(workflow):
    h = workflow
    with pytest.raises(StaleVersionError):
        port(h.owner_ids["A"], lambda request: httpx.Response(200, json={"error": "stale"})).create_once(
            h.owner_ids["A"], uuid4(), "0" * 64, prepared(h), expected_revision=0
        )
