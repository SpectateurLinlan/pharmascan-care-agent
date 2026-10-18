"""Actual HTTP/application semantic checks with explicit DEMO memory persistence."""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from app.contracts.dto import DoseEventDTO
from app.transport.auth import AuthBoundary, StaticTokenVerifier
from fastapi.testclient import TestClient

from .grouped_records_browser_server import build_grouped_records_app
from .records_browser_server import NOW, OWNER, TOKEN, fixture_id


@pytest.fixture()
def wired():
    app = build_grouped_records_app()
    app.state.container.auth = AuthBoundary(
        mode="supabase",
        verifier=StaticTokenVerifier(
            {
                TOKEN: {"sub": str(OWNER)},
                "DEMO-B": {"sub": str(UUID(int=42))},
            }
        ),
    )
    with TestClient(app) as client:
        yield app.state.container, client


def read(client, token=TOKEN, **params):
    return client.get("/api/me/medication-history", params=params, headers={"Authorization": "Bearer " + token})


def complete(client, **params):
    entries = []
    cursor = None
    while True:
        response = read(client, **params, **({"cursor": cursor} if cursor else {}))
        assert response.status_code == 200, response.text
        data = response.json()
        entries.extend(data["entries"])
        cursor = data["next_cursor"]
        if not cursor:
            break
        assert len(entries) < 500
    assert len({row["id"] for row in entries}) == len(entries)
    assert [row["sort_time"] for row in entries] == sorted([row["sort_time"] for row in entries], reverse=True)
    return entries


@pytest.mark.parametrize("medicine,count", [(103, 0), (102, 1), (104, 5), (105, 6), (101, 20)])
def test_real_counts_pagination_and_no_materialisation(wired, medicine, count):
    container, client = wired
    before = repr(container.store.occurrences), repr(container.store.events), repr(container.store.regimens)
    response = read(client, medication_id=fixture_id(medicine), range_kind="7").json()
    assert len(response["entries"]) == min(count, 5)
    assert bool(response["next_cursor"]) is (count > 5)
    assert len(complete(client, medication_id=fixture_id(medicine), range_kind="7")) == count
    assert before == (repr(container.store.occurrences), repr(container.store.events), repr(container.store.regimens))


def test_catalogue_preserves_independent_registrations_and_actual_supersedes(wired):
    _, client = wired
    data = client.get("/api/me/medication-history/catalogue", headers={"Authorization": "Bearer " + TOKEN}).json()
    assert len(data["medications"]) == 5 and len(data["plans"]) == 7
    assert [row["id"] for row in data["plans"] if row["medication_id"] == str(fixture_id(101))] == [
        str(fixture_id(3)),
        str(fixture_id(2)),
        str(fixture_id(1)),
    ]
    assert {row["strength_text"] for row in data["plans"] if row["medication_id"] == str(fixture_id(102))} == {"10 mg"}
    assert next(row for row in data["plans"] if row["id"] == str(fixture_id(3)))["supersedes_id"] == str(fixture_id(2))
    assert all(
        row["supersedes_id"] is None
        for row in data["plans"]
        if row["medication_id"] in [str(fixture_id(103)), str(fixture_id(104))]
    )


def test_all_medicines_custom_local_dates_and_plan_effective_period(wired):
    _, client = wired
    assert len(complete(client)) == 38
    assert len(complete(client, range_kind="all")) == 58
    assert len(complete(client, medication_id=fixture_id(101))) == 26
    assert len(complete(client, regimen_id=fixture_id(1), range_kind="plan")) == 20
    rows = complete(client, regimen_id=fixture_id(3), range_kind="custom", start="2026-10-17", end="2026-10-17")
    assert len(rows) == 19 and rows[-1]["sort_time"].startswith("2026-10-16T16:00:")
    assert all(row["due_at"] <= NOW.isoformat().replace("+00:00", "Z") for row in rows)


def test_late_submission_uses_occurrence_ownership_and_never_created_at_sort(wired):
    container, client = wired
    key = next(key for key, event in container.store.events.items() if event.regimen_id == fixture_id(1))
    event = container.store.events[key]
    container.store.events[key] = event.model_copy(
        update={"event_time": NOW - timedelta(minutes=2), "created_at": NOW - timedelta(seconds=1)}
    )
    old = complete(client, regimen_id=fixture_id(1), range_kind="plan")
    row = next(row for row in old if row["event_id"] == str(event.id))
    assert row["reported"] and row["submitted_at"] != row["sort_time"] and row["event_time"] != row["sort_time"]
    assert row["regimen_id"] == str(fixture_id(1))
    assert not read(client, range_kind="7").json()["entries"][0]["regimen_id"] == str(fixture_id(1))


def test_mixed_unscheduled_and_scheduled_ties_have_no_skips_or_duplicates(wired):
    container, client = wired
    original = container.store.regimens[(OWNER, fixture_id(3))]
    prn_id = fixture_id(909)
    container.store.regimens[(OWNER, prn_id)] = original.model_copy(update={"id": prn_id, "is_prn": True})
    for index in range(9):
        identity = uuid4()
        container.store.events[(OWNER, identity)] = DoseEventDTO(
            id=identity,
            patient_id=OWNER,
            regimen_id=prn_id,
            occurrence_id=None,
            event_time=NOW - timedelta(hours=1, minutes=index % 3),
            created_at=NOW - timedelta(seconds=index),
            intake_status="unsure",
            idempotency_key="DEMO:" + str(identity),
        )
    rows = complete(client, range_kind="7")
    assert len(rows) == 41 and len([row for row in rows if row["kind"] == "unscheduled"]) == 9
    assert all(row["event_time"] is not None for row in rows if row["kind"] == "unscheduled")
    assert any(not row["reported"] and row["intake_status"] is None for row in rows)


def test_owned_filters_cursor_binding_and_invalid_ranges(wired):
    _, client = wired
    assert read(client, token="DEMO-B").json()["entries"] == []
    assert read(client, token="DEMO-B", medication_id=fixture_id(101)).status_code == 404
    assert read(client, token="DEMO-B", regimen_id=fixture_id(3)).status_code == 404
    assert read(client, medication_id=fixture_id(102), regimen_id=fixture_id(3)).status_code == 422
    cursor = read(client).json()["next_cursor"]
    assert read(client, cursor=cursor, regimen_id=fixture_id(3)).status_code == 422
    assert read(client, token="DEMO-B", cursor=cursor).status_code == 422
    assert read(client, range_kind="plan").status_code == 422
    assert read(client, range_kind="custom", start="2026-10-20", end="2026-10-17").status_code == 422
    assert read(client, cursor="not base64").status_code == 422
    assert client.get("/api/me/medication-history").status_code == 401


def test_service_dependency_is_read_only_not_old_history_materializer(wired, monkeypatch):
    container, client = wired

    def forbidden(**kwargs):
        raise AssertionError("Read-only history must not write or use legacy history window")

    monkeypatch.setattr(container.schedule, "materialize", forbidden)
    monkeypatch.setattr(container.self_report, "history", forbidden)
    assert read(client).status_code == 200


def test_custom_local_date_observes_dst_boundary(wired):
    _, client = wired
    response = client.put(
        "/api/me/preferences", headers={"Authorization": "Bearer " + TOKEN}, json={"timezone": "America/New_York"}
    )
    assert response.status_code == 200
    data = read(client, range_kind="custom", start="2026-03-08", end="2026-03-08").json()
    assert data["window_start"] == "2026-03-08T05:00:00Z"
    assert data["window_end"] == "2026-03-09T04:00:00Z"


def test_catalogue_exposes_real_frequency_form_and_end_without_inventing_identity(wired):
    container, client = wired
    key = (OWNER, fixture_id(3))
    container.store.regimens[key] = container.store.regimens[key].model_copy(
        update={
            "frequency_rule": {
                "kind": "daily",
                "local_times": ["08:00", "20:00"],
                "days_of_week": [],
                "every_hours": None,
            }
        }
    )
    data = client.get("/api/me/medication-history/catalogue", headers={"Authorization": "Bearer " + TOKEN}).json()
    plan = next(row for row in data["plans"] if row["id"] == str(fixture_id(3)))
    assert plan["dosage_form"] == "tablet" and plan["strength_text"] == "5 mg"
    assert plan["frequency"]["local_times"] == ["08:00", "20:00"] and plan["effective_to"] is None
    assert len([row for row in data["medications"] if row["display_name"] == "DEMO Amlodipine"]) == 2


def test_name_filter_aggregates_independent_registrations_without_merging(wired):
    container, client = wired
    before = (dict(container.store.medications), dict(container.store.regimens), dict(container.store.events))
    rows = complete(client, medication_name="  demo   AMLODIPINE ")
    assert len(rows) == 27 and {row["medication_id"] for row in rows} == {str(fixture_id(101)), str(fixture_id(102))}
    assert len(complete(client, medication_name="DEMO Amlodipine", regimen_id=fixture_id(3))) == 20
    assert read(client, medication_name="DEMO Amlodipine", regimen_id=fixture_id(5)).status_code == 422
    assert read(client, medication_name="DEMO Amlodipine", token="DEMO-B").status_code == 404
    cursor = read(client, medication_name="DEMO Amlodipine").json()["next_cursor"]
    assert read(client, medication_name="DEMO Metformin", cursor=cursor).status_code == 422
    assert before == (dict(container.store.medications), dict(container.store.regimens), dict(container.store.events))


@pytest.mark.parametrize("pending_state", ["draft", "pending_clarification"])
def test_unconfirmed_registrations_and_plan_versions_never_enter_history(wired, pending_state):
    container, client = wired
    store = container.store
    original = store.regimens[(OWNER, fixture_id(3))]
    pending_med = fixture_id(701)
    store.medications[(OWNER, pending_med)] = store.medications[(OWNER, fixture_id(101))].model_copy(
        update={"id": pending_med, "identity_status": "user_reviewed_document"}
    )
    for number, med in [(801, pending_med), (802, fixture_id(101))]:
        store.regimens[(OWNER, fixture_id(number))] = original.model_copy(
            update={"id": fixture_id(number), "patient_medication_id": med, "state": pending_state}
        )
        occurrence = next(iter(store.occurrences.values()))
        store.occurrences[(OWNER, fixture_id(9000 + number))] = occurrence.model_copy(
            update={
                "id": fixture_id(9000 + number),
                "regimen_id": fixture_id(number),
                "due_at": NOW - timedelta(hours=1),
            }
        )
    catalogue = client.get("/api/me/medication-history/catalogue", headers={"Authorization": "Bearer " + TOKEN}).json()
    assert str(pending_med) not in {row["id"] for row in catalogue["medications"]}
    assert not {str(fixture_id(801)), str(fixture_id(802))}.intersection(row["id"] for row in catalogue["plans"])
    assert len(complete(client)) == 38
    assert len(complete(client, medication_name="DEMO Amlodipine")) == 27
    assert read(client, regimen_id=fixture_id(801)).status_code == 404
    assert read(client, regimen_id=fixture_id(802)).status_code == 404
    assert read(client, medication_id=pending_med).status_code == 404
    assert {row["state"] for row in catalogue["plans"]} == {"active", "ended"}


def test_only_sources_or_drafts_produce_empty_history_catalogue_and_results(wired):
    container, client = wired
    store = container.store
    for key, row in list(store.regimens.items()):
        store.regimens[key] = row.model_copy(update={"state": "draft"})
    data = client.get("/api/me/medication-history/catalogue", headers={"Authorization": "Bearer " + TOKEN}).json()
    assert data == {"medications": [], "plans": []}
    assert complete(client, range_kind="all") == []


def test_confirmed_superseded_history_remains_available(wired):
    container, client = wired
    key = (OWNER, fixture_id(1))
    container.store.regimens[key] = container.store.regimens[key].model_copy(update={"state": "superseded"})
    catalogue = client.get("/api/me/medication-history/catalogue", headers={"Authorization": "Bearer " + TOKEN}).json()
    assert next(row for row in catalogue["plans"] if row["id"] == str(fixture_id(1)))["state"] == "superseded"
    assert len(complete(client, regimen_id=fixture_id(1), range_kind="plan")) == 20
