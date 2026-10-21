"""Synthetic local performance/correctness guards; no production benchmarks."""

from unittest.mock import patch

import pytest
from app.domain.errors import ProviderUnavailableError
from app.infrastructure.supabase_data import SupabaseDataClient
from app.timing import RequestTiming, current_timing

from .correctness02_support import OWNER, TOKEN, build_harness
from .test_patient_app_repairs import PATIENT, activate, services


def test_materialization_batches_existing_slots_and_preserves_closed_history(wired):
    from app.contracts.enums import OccurrenceStatus

    plan = activate(wired, 0)
    first = wired.schedule.materialize(patient_id=PATIENT, regimen_id=plan, days=7)
    assert len(first) == 7
    closed = first[0].model_copy(update={"status": OccurrenceStatus.CLOSED})
    wired.occurrences.update(closed)
    with (
        patch.object(wired.occurrences, "list_for_regimen", wraps=wired.occurrences.list_for_regimen) as windows,
        patch.object(
            wired.occurrences, "find_by_generation_key", wraps=wired.occurrences.find_by_generation_key
        ) as keys,
        patch.object(wired.occurrences, "add", wraps=wired.occurrences.add) as writes,
    ):
        repeated = wired.schedule.materialize(patient_id=PATIENT, regimen_id=plan, days=7)
    assert windows.call_count == 1 and keys.call_count == writes.call_count == 0
    assert [row.id for row in repeated] == [row.id for row in first]
    assert repeated[0] == closed


def test_materialization_fails_closed_when_owned_window_read_fails(wired):
    plan = activate(wired, 0)
    with (
        patch.object(wired.occurrences, "list_for_regimen", side_effect=ProviderUnavailableError("unavailable")),
        patch.object(wired.occurrences, "add", wraps=wired.occurrences.add) as writes,
        pytest.raises(ProviderUnavailableError),
    ):
        wired.schedule.materialize(patient_id=PATIENT, regimen_id=plan, days=2)
    assert writes.call_count == 0


def test_current_snooze_checks_original_deadline_once(wired):
    plan = activate(wired, 0)
    occurrence = wired.schedule.materialize(patient_id=PATIENT, regimen_id=plan, days=1)[0]
    reminders, _ = services(wired)
    saved = reminders.snooze(patient_id=PATIENT, occurrence_id=occurrence.id, minutes=15)
    with patch.object(reminders, "deadline", wraps=reminders.deadline) as deadlines:
        result = reminders.list_current(PATIENT)
    assert len(result) == 1 and result[0].remind_at == saved.remind_at
    assert deadlines.call_count == 1


def test_supabase_composition_shares_only_verified_tls_and_closes_failed_request_clients():
    import ssl

    import httpx
    from app.transport.auth import AuthenticatedPrincipal
    from app.transport.container import build_supabase_container

    from .test_render_deployment import deployment_settings

    root = build_supabase_container(settings=deployment_settings())
    clients = []
    contexts = []
    real_client = httpx.Client

    def make_client(**kwargs):
        contexts.append(kwargs["verify"])
        client = real_client(**kwargs)
        clients.append(client)
        return client

    with (
        patch("httpx.Client", side_effect=make_client),
        patch("app.transport.container.SupabasePreferences.get", side_effect=ProviderUnavailableError("unavailable")),
    ):
        for owner in (OWNER, PATIENT):
            principal = AuthenticatedPrincipal(owner, str(owner), None, True, "supabase", "DEMO_ONLY_TOKEN")
            with pytest.raises(ProviderUnavailableError):
                root.patient_factory(principal)
    assert len(clients) == 4 and len({id(client) for client in clients}) == 4
    assert all(client.is_closed for client in clients)
    assert all(context is contexts[0] for context in contexts)
    assert contexts[0].check_hostname and contexts[0].verify_mode == ssl.CERT_REQUIRED


def test_followup_list_reuses_owned_context_but_confirmation_reads_fresh():
    h = build_harness()
    service = h.root.late_reports
    with (
        patch.object(service.enrollment, "get_regimen", wraps=service.enrollment.get_regimen) as plans,
        patch.object(service.enrollment, "get_medication", wraps=service.enrollment.get_medication) as medicines,
        patch.object(service.schedule, "get_occurrence", wraps=service.schedule.get_occurrence) as occurrences,
        patch.object(service.events, "find_by_occurrence", wraps=service.events.find_by_occurrence) as event_reads,
        patch.object(
            service.events, "list_for_occurrences", wraps=service.events.list_for_occurrences
        ) as event_batches,
    ):
        result = service.recent(OWNER, include_reported=True)
        assert result["items"]
        assert plans.call_count == medicines.call_count == occurrences.call_count == 0
        assert event_reads.call_count == 0 and event_batches.call_count > 0
        for item in result["items"]:
            if item.can_report:
                assert service.occurrence(OWNER, item.occurrence_id) == item
        assert plans.call_count > 0 and occurrences.call_count > 0
        assert event_reads.call_count > 0


def test_supabase_event_batch_is_owned_chunked_complete_and_uses_effective_view():
    from uuid import UUID

    import httpx
    from app.contracts.dto import DoseEventDTO
    from app.domain.errors import AuthenticationRequiredError
    from app.infrastructure.supabase_repos import Events

    h = build_harness()
    event = next(iter(h.root.store.events.values()))
    selected = [event.occurrence_id, *[UUID(int=9000 + index) for index in range(204)]]
    requests = []
    incomplete = False

    def handle(request):
        requests.append(request)
        assert request.method == "GET" and request.url.path == "/rest/v1/effective_dose_events"
        assert request.url.params["patient_id"] == f"eq.{OWNER}"
        assert "event_time" not in request.url.params
        assert request.headers["authorization"] == "Bearer DEMO_PRIVATE"
        if incomplete:
            return httpx.Response(200, json=[], headers={"content-range": "*/1"})
        matches = str(event.occurrence_id) in request.url.params["occurrence_id"]
        rows = [event.model_dump(mode="json")] if matches else []
        return httpx.Response(200, json=rows, headers={"content-range": f"*/{len(rows)}"})

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        client = SupabaseDataClient(
            base_url="https://synthetic.invalid", publishable_key="sb_publishable_DEMO",
            access_token="DEMO_PRIVATE", patient_id=OWNER, client=http,
        )
        repository = Events(client, "effective_dose_events", DoseEventDTO)
        assert repository.list_for_occurrences(OWNER, []) == [] and not requests
        assert repository.list_for_occurrences(OWNER, [*selected, selected[0]]) == [event]
        assert len(requests) == 3
        with pytest.raises(AuthenticationRequiredError):
            repository.list_for_occurrences(PATIENT, selected)
        assert len(requests) == 3
        incomplete = True
        with pytest.raises(ProviderUnavailableError):
            repository.list_for_occurrences(OWNER, selected)


def test_followup_batch_failure_is_not_an_empty_success():
    h = build_harness()
    with (
        patch.object(
            h.root.late_reports.events, "list_for_occurrences", side_effect=ProviderUnavailableError("unavailable")
        ),
        pytest.raises(ProviderUnavailableError),
    ):
        h.root.late_reports.recent(OWNER)


def test_timings_are_aggregate_and_isolated_including_denied_requests():
    h = build_harness()
    first = h.client.get("/api/me/dose-follow-ups", headers={"Authorization": f"Bearer {TOKEN}"})
    assert first.status_code == 200
    header = first.headers["server-timing"]
    assert "business;dur=" in header and "auth;dur=" in header and "app;dur=" in header
    assert str(OWNER) not in header and TOKEN not in header and "data_calls;desc=\"0\"" in header
    denied = h.client.get("/api/me/dose-follow-ups", headers={"Authorization": "Bearer DEMO.invalid"})
    assert denied.status_code == 401
    assert "business" not in denied.headers["server-timing"]
    assert current_timing.get() is None


def test_data_timing_counts_failure_without_recording_private_values():
    import httpx

    timing = RequestTiming()
    marker = current_timing.set(timing)
    try:
        with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))) as http:
            client = SupabaseDataClient(
                base_url="https://synthetic.invalid", publishable_key="sb_publishable_DEMO",
                access_token="DEMO.private", patient_id=OWNER, client=http,
            )
            assert client.rows("dose_events", patient_id=f"eq.{OWNER}") == []
        assert timing.data_requests == 1 and timing.milliseconds["data"] >= 0
        with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503, json={}))) as http:
            client = SupabaseDataClient(
                base_url="https://synthetic.invalid", publishable_key="sb_publishable_DEMO",
                access_token="DEMO.private", patient_id=OWNER, client=http,
            )
            with pytest.raises(ProviderUnavailableError):
                client.rows("dose_events", patient_id=f"eq.{OWNER}")
        assert timing.data_requests == 2
        assert "DEMO" not in timing.header() and str(OWNER) not in timing.header()
    finally:
        current_timing.reset(marker)


def test_private_storage_timing_preserves_owner_checks_and_hides_object_paths():
    import httpx
    from app.domain.errors import ValidationError
    from app.infrastructure.evidence_repos import SupabaseImageStore

    calls = []

    def handle(request):
        calls.append(request.method)
        return httpx.Response(200, content=b"DEMO_ONLY_PRIVATE_IMAGE_BYTES")

    store = SupabaseImageStore(
        base_url="https://synthetic.invalid", publishable_key="sb_publishable_DEMO",
        access_token="DEMO_PRIVATE_TOKEN", patient_id=OWNER,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handle)),
    )
    timing = RequestTiming()
    marker = current_timing.set(timing)
    try:
        assert store.get(f"{OWNER}/DEMO_PRIVATE_OBJECT.png") == b"DEMO_ONLY_PRIVATE_IMAGE_BYTES"
        assert timing.storage_requests == 1 and timing.milliseconds["storage"] >= 0
        with pytest.raises(ValidationError):
            store.get("foreign/private.png")
        assert calls == ["GET"] and timing.storage_requests == 1
        header = timing.header()
        assert 'storage_calls;desc="1"' in header
        assert "PRIVATE" not in header and str(OWNER) not in header
    finally:
        current_timing.reset(marker)
