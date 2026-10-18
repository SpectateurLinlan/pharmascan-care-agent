"""Synthetic patient HTTP + explicit provider contract tests, not hosted proof."""

from uuid import UUID

import httpx
import pytest
from app.domain.errors import ProviderUnavailableError
from app.infrastructure.draft_deletion import SupabaseDraftDeletion
from app.infrastructure.evidence_repos import MemoryImageStore, SupabaseImageStore
from app.infrastructure.supabase_data import SupabaseDataClient
from fastapi.testclient import TestClient

from .grouped_records_browser_server import build_grouped_records_app
from .records_browser_server import OWNER, TOKEN, fixture_id


def test_http_confirm_cancel_owner_and_actual_memory_cleanup():
    app = build_grouped_records_app()
    headers = {"Authorization": "Bearer " + TOKEN}
    with TestClient(app) as c:
        created = c.post(
            "/api/medications/drafts",
            headers=headers,
            json={
                "medication_name": "DEMO deletable",
                "dose_amount": 1,
                "dose_unit": "tablet",
                "frequency_kind": "daily",
                "frequency_local_times": ["08:00"],
            },
        ).json()
        path = "/api/medications/unfinished/draft/" + created["regimen_id"]
        before = len(app.state.container.store.regimens)
        assert c.request("DELETE", path, headers=headers, json={"confirmed": False}).status_code == 422
        assert len(app.state.container.store.regimens) == before
        assert (
            c.request(
                "DELETE",
                path,
                headers={"Authorization": "Bearer DEMO.confirmation-session-token"},
                json={"confirmed": True},
            ).status_code
            == 404
        )
        c.post("/api/medications/drafts/" + created["source_id"] + "/review", headers=headers, json={})
        assert c.request("DELETE", path, headers=headers, json={"confirmed": True}).json() == {
            "deleted": True,
            "medication_deleted": True,
            "cleanup_pending": False,
        }
        store = app.state.container.store
        assert (OWNER, UUID(created["regimen_id"])) not in store.regimens
        assert (OWNER, UUID(created["medication_id"])) not in store.medications
        assert (OWNER, UUID(created["source_id"])) not in store.sources
        assert not any(row.source_id == UUID(created["source_id"]) for row in store.source_fields.values())
        assert c.request("DELETE", path, headers=headers, json={"confirmed": True}).status_code == 200
        assert (
            c.request(
                "DELETE",
                "/api/medications/unfinished/draft/" + str(fixture_id(3)),
                headers=headers,
                json={"confirmed": True},
            ).status_code
            == 422
        )


def test_storage_api_deletes_owned_object_and_handles_missing_idempotently():
    calls = []

    def handler(request):
        calls.append(request)
        assert (
            request.method == "DELETE" and request.url.path == f"/storage/v1/object/visual-references/{OWNER}/DEMO.png"
        )
        return httpx.Response(200, json={}) if len(calls) == 1 else httpx.Response(404, json={"error": "NotFound"})

    store = SupabaseImageStore(
        base_url="https://example.invalid",
        publishable_key="DEMO",
        access_token="DEMO",
        patient_id=OWNER,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    store.delete(f"{OWNER}/DEMO.png")
    store.delete(f"{OWNER}/DEMO.png")
    assert len(calls) == 2


def test_schema_contract_error_is_provider_unavailable_not_patient_input():
    from app.domain.errors import ProviderUnavailableError

    def handler(_request):
        return httpx.Response(400, json={"code": "42703", "message": "column does not exist"})

    client = SupabaseDataClient(
        base_url="https://example.invalid",
        publishable_key="DEMO",
        access_token="DEMO",
        patient_id=OWNER,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(ProviderUnavailableError, match="database service is not ready"):
        client.request(
            "POST",
            "/rest/v1/rpc/delete_unconfirmed_medication",
            body={"p_kind": "draft", "p_id": str(fixture_id(90)), "p_confirmed": True},
        )


def test_cleanup_failure_is_reported_and_retry_uses_same_receipt():
    path = f"{OWNER}/DEMO.png"
    remaining = [path]

    def handler(request):
        if request.url.path.endswith("/delete_unconfirmed_medication"):
            return httpx.Response(
                200, json={"deleted": True, "medication_deleted": True, "storage_paths": remaining[:]}
            )
        assert request.url.path.endswith("/ack_draft_image_cleanup")
        remaining.clear()
        return httpx.Response(204)

    client = SupabaseDataClient(
        base_url="https://example.invalid",
        publishable_key="DEMO",
        access_token="DEMO",
        patient_id=OWNER,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )

    class Storage(MemoryImageStore):
        fail = True

        def delete(self, path):
            if self.fail:
                raise ProviderUnavailableError("DEMO offline")
            super().delete(path)

    storage = Storage()
    adapter = SupabaseDraftDeletion(client, storage)
    assert adapter.delete(OWNER, "draft", fixture_id(99)).cleanup_pending
    storage.fail = False
    assert not adapter.delete(OWNER, "draft", fixture_id(99)).cleanup_pending and remaining == []


def test_patient_edit_marker_is_persisted_without_marking_unedited_initial_plan():
    app = build_grouped_records_app()
    headers = {"Authorization": "Bearer " + TOKEN}
    with TestClient(app) as client:
        for edited in (False, True):
            response = client.post(
                "/api/medications/drafts",
                headers=headers,
                json={
                    "medication_name": "DEMO edit marker " + str(edited),
                    "dose_amount": 1,
                    "dose_unit": "tablet",
                    "frequency_kind": "daily",
                    "frequency_local_times": ["08:00"],
                    "patient_edited": edited,
                },
            )
            assert response.status_code == 200
            identity = UUID(response.json()["regimen_id"])
            assert app.state.container.store.regimens[OWNER, identity].patient_edited is edited
