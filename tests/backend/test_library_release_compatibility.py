"""Synthetic HTTP/provider tests for a database deliberately limited to migration030."""

from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest
from app.config import Settings
from app.domain.errors import ProviderUnavailableError
from app.infrastructure.record_history import SupabaseRecordHistory
from app.infrastructure.supabase_data import SupabaseDataClient
from app.infrastructure.supabase_repos import build_supabase_repositories
from app.transport.error_mapping import error_payload, status_for
from fastapi.testclient import TestClient

from .grouped_records_browser_server import build_grouped_records_app
from .records_browser_server import OWNER, fixture_id


def client(handler):
    return SupabaseDataClient(
        base_url="https://example.invalid",
        publishable_key="DEMO-publishable",
        access_token="DEMO-token",
        patient_id=OWNER,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )


@pytest.mark.parametrize("code", ["PGRST205", "PGRST204", "PGRST202", "42P01", "42703", "42883"])
def test_missing_database_contract_is_503_with_scrubbed_structured_diagnostics(code, caplog):
    data = client(lambda _: httpx.Response(404, json={"code": code, "message": "private data DEMO-token"}))
    with pytest.raises(ProviderUnavailableError) as error:
        data.rows("effective_dose_events", patient_id=f"eq.{OWNER}")
    assert status_for(error.value) == 503
    payload = error_payload(error.value)
    assert payload["code"] == "PROVIDER_UNAVAILABLE"
    assert "private" not in payload["message"] and "DEMO-token" not in caplog.text
    record = caplog.records[-1]
    assert record.resource == "effective_dose_events" and record.provider_code == code
    assert str(OWNER) not in str(record.__dict__)


@pytest.mark.parametrize("enabled,table", [(False, "dose_events"), (True, "effective_dose_events")])
def test_event_read_contract_is_explicit_and_has_no_automatic_fallback(enabled, table):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=[])

    repos = build_supabase_repositories(client(handler), include_late_reports=enabled)
    assert repos.events.find_by_occurrence(OWNER, UUID(int=5)) is None
    assert calls == ["/rest/v1/" + table]


@pytest.mark.parametrize("target", ["202610190032", "202610190033"])
def test_chronological_runner_rejects_skipping_pending_031_without_any_write(monkeypatch, target, capsys):
    from argparse import Namespace
    from contextlib import nullcontext

    from scripts import db as runner

    class NoWrites:
        def connect(self, **_kwargs):
            return nullcontext(object())

    recorded = {m.version: m.sha256 for m in runner.discover_migrations() if m.version <= "202610190030"}
    monkeypatch.setattr(runner, "_settings", lambda: object())
    monkeypatch.setattr(runner, "_database", lambda _: NoWrites())
    monkeypatch.setattr(runner, "applied_migrations", lambda _: recorded)
    monkeypatch.setattr(runner, "apply_recorded_migration", lambda *_: pytest.fail("No DDL is permitted"))
    monkeypatch.setattr(runner, "record_migration", lambda *_: pytest.fail("No ledger write is permitted"))
    assert runner.cmd_migrate(Namespace(only=target)) == 3
    assert "previous migration missing" in capsys.readouterr().out


@pytest.mark.parametrize("enabled", [False, True])
def test_history_queries_amendments_only_after_explicit_033_enablement(enabled):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=[], headers={"Content-Range": "*/0"})

    repository = SupabaseRecordHistory(client(handler), include_late_reports=enabled)
    assert repository.reports(OWNER, [UUID(int=10)], datetime.now(UTC)) == []
    assert calls == ["/rest/v1/dose_events"] + (["/rest/v1/dose_report_entries"] if enabled else [])


def test_unreleased_database_switches_default_off_without_loading_local_secrets(tmp_path, monkeypatch):
    monkeypatch.delenv("ENABLE_MEDICATION_LIBRARY_FILES", raising=False)
    monkeypatch.delenv("ENABLE_LATE_DOSE_REPORTS", raising=False)
    settings = Settings.from_env(env_file=tmp_path / "missing.env")
    assert not settings.enable_medication_library_files and not settings.enable_late_dose_reports
    monkeypatch.setenv("ENABLE_MEDICATION_LIBRARY_FILES", "true")
    monkeypatch.setenv("ENABLE_LATE_DOSE_REPORTS", "true")
    settings = Settings.from_env(env_file=tmp_path / "missing.env")
    assert settings.enable_medication_library_files and settings.enable_late_dose_reports


@pytest.mark.parametrize("enabled", [False, True])
def test_health_reports_the_injected_release_configuration_without_patient_access(tmp_path, enabled):
    from dataclasses import replace

    from app.transport.app_factory import create_app

    root = build_grouped_records_app().state.container
    root.persistence = "supabase"
    settings = replace(
        Settings.from_env(env_file=tmp_path / "missing.env"),
        enable_medication_library_files=enabled,
        enable_late_dose_reports=enabled,
    )
    with TestClient(create_app(container=root, settings=settings)) as http:
        response = http.get("/api/health")
        assert response.status_code == 200
        assert response.json()["medication_library_files_enabled"] is enabled
        assert response.json()["late_dose_reports_enabled"] is enabled


def test_030_compatible_gallery_medications_regimens_history_and_disabled_file_routes():
    app = build_grouped_records_app()
    app.state.container.library_files = None
    headers = {"Authorization": "Bearer DEMO.synthetic-session-token"}
    with TestClient(app) as http:
        for path in [
            "/api/evidence/gallery",
            "/api/me/medications",
            "/api/me/regimens",
            "/api/me/medication-history?range_kind=7",
        ]:
            assert http.get(path, headers=headers).status_code == 200, path
        files = http.get(f"/api/evidence/gallery/{fixture_id(101)}/files", headers=headers)
        assert files.status_code == 200 and files.json()["file_management_available"] is False
        assert http.get(f"/api/evidence/library-files/{UUID(int=12)}", headers=headers).status_code == 503
        assert (
            http.post(
                f"/api/evidence/gallery/{fixture_id(101)}/pdfs?filename=DEMO.pdf", headers=headers, content=b"DEMO"
            ).status_code
            == 503
        )


def test_enabled_pdf_http_lifecycle_is_private_and_preserves_medication_records():
    app = build_grouped_records_app()
    headers = {"Authorization": "Bearer DEMO.synthetic-session-token", "Content-Type": "application/pdf"}
    payload = b"%PDF-1.7\nDEMO synthetic original\n%%EOF\n"
    before = len(app.state.container.store.regimens)
    with TestClient(app) as http:
        response = http.post(
            f"/api/evidence/gallery/{fixture_id(101)}/pdfs?filename=DEMO.pdf", headers=headers, content=payload
        )
        assert response.status_code == 200
        identifier = response.json()["file"]["id"]
        path = f"/api/evidence/library-files/{identifier}"
        preview = http.get(path, headers=headers)
        assert preview.status_code == 200 and preview.content == payload
        assert preview.headers["cache-control"] == "no-store" and preview.headers["x-content-type-options"] == "nosniff"
        assert preview.headers["content-security-policy"].startswith("sandbox;")
        assert http.get(path).status_code == 401
        other = {"Authorization": "Bearer DEMO.confirmation-session-token"}
        assert http.get(path, headers=other).status_code == 404
        download = http.get(path + "?disposition=attachment", headers=headers)
        assert download.headers["content-disposition"].startswith("attachment;")
        updated = http.patch(
            path,
            headers={"Authorization": headers["Authorization"]},
            json={"expected_version": 1, "title": "DEMO reviewed title", "category": "other", "description": "DEMO"},
        )
        assert updated.status_code == 200 and updated.json()["version"] == 2
        assert http.delete(path, headers=headers).status_code == 422
        assert http.delete(path + "?confirmed=true", headers=headers).status_code == 200
        assert http.get(path, headers=headers).status_code == 404
    assert len(app.state.container.store.regimens) == before
