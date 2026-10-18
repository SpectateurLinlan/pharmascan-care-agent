"""Mock provider contract: bounded exact-count reads, never fake missing reports."""

from datetime import timedelta
from uuid import UUID

import httpx
import pytest
from app.domain.errors import ProviderUnavailableError
from app.infrastructure.record_history import SupabaseRecordHistory
from app.infrastructure.supabase_data import SupabaseDataClient

from .grouped_records_browser_server import build_grouped_records_app
from .records_browser_server import NOW, OWNER, fixture_id


def adapter(handler):
    return SupabaseRecordHistory(
        SupabaseDataClient(
            base_url="https://example.invalid",
            publishable_key="DEMO-publishable",
            access_token="DEMO-token",
            patient_id=OWNER,
            client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
        )
    )


def test_provider_page_cap_is_filled_and_filters_are_owned_bounded_and_keyset():
    store = build_grouped_records_app().state.container.store
    rows = [row.model_dump(mode="json") for row in store.occurrences.values() if row.regimen_id == fixture_id(3)][:2]
    calls = []

    def handler(request):
        assert request.method == "GET" and request.url.path == "/rest/v1/dose_occurrences"
        params = request.url.params
        assert params["patient_id"] == "eq." + str(OWNER)
        assert params["regimen_id"] == "in.(" + str(fixture_id(3)) + ")"
        assert "created_at.lte." in params["and"] and "due_at.gte." in params["and"]
        assert params["order"] == "due_at.desc,id.desc" and request.headers["Prefer"] == "count=exact"
        offset = int(params["offset"])
        calls.append(offset)
        return httpx.Response(200, json=rows[offset : offset + 1], headers={"Content-Range": f"{offset}-{offset}/2"})

    values = adapter(handler).scheduled(OWNER, [fixture_id(3)], NOW - timedelta(days=7), NOW, NOW, None, 6)
    assert len(values) == 2 and calls == [0, 1]


def test_scheduled_report_read_uses_occurrence_id_not_report_event_window():
    store = build_grouped_records_app().state.container.store
    event = next(row for row in store.events.values() if row.regimen_id == fixture_id(1))
    row = event.model_copy(update={"event_time": NOW - timedelta(seconds=1)}).model_dump(mode="json")

    def handler(request):
        assert request.method == "GET" and request.url.path == "/rest/v1/dose_events"
        assert request.url.params["occurrence_id"] == "in.(" + str(event.occurrence_id) + ")"
        assert "event_time" not in request.url.params and "and" not in request.url.params
        assert request.url.params["patient_id"] == "eq." + str(OWNER)
        return httpx.Response(200, json=[row], headers={"Content-Range": "0-0/1"})

    assert adapter(handler).reports(OWNER, [event.occurrence_id], NOW)[0].id == event.id


@pytest.mark.parametrize("failure", ["foreign", "missing_count", "truncated", "changed_count"])
def test_uncertain_provider_results_fail_closed_instead_of_returning_unrecorded(failure):
    store = build_grouped_records_app().state.container.store
    event = next(iter(store.events.values())).model_dump(mode="json")
    calls = []

    def handler(request):
        offset = int(request.url.params["offset"])
        calls.append(offset)
        row = {**event, "patient_id": str(UUID(int=99))} if failure == "foreign" else event
        if failure == "missing_count":
            return httpx.Response(200, json=[row])
        if failure == "truncated":
            return httpx.Response(200, json=[], headers={"Content-Range": "*/1"})
        if failure == "changed_count":
            return httpx.Response(
                200, json=[row], headers={"Content-Range": f"{offset}-{offset}/{2 if not offset else 3}"}
            )
        return httpx.Response(200, json=[row], headers={"Content-Range": "0-0/1"})

    with pytest.raises(ProviderUnavailableError):
        adapter(handler).reports(OWNER, [UUID(event["occurrence_id"]), UUID(int=888)], NOW)
