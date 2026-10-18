"""DEMO_ONLY real route/service tests; explicitly simulated memory persistence."""

import pytest
from fastapi.testclient import TestClient

from .records_browser_server import TOKEN, build_records_app, fixture_id


@pytest.fixture()
def records_client():
    with TestClient(build_records_app()) as client:
        yield client


def query(client, plan, days=7):
    return client.get(
        "/api/me/dose-history",
        params={"regimen_id": str(fixture_id(plan)), "days": days},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )


@pytest.mark.parametrize("plan,count", [(3, 21), (4, 1), (5, 0), (6, 5), (7, 6)])
def test_actual_history_api_counts_include_future_occurrence(records_client, plan, count):
    response = query(records_client, plan)
    assert response.status_code == 200
    assert response.json()["item_count"] == count
    assert len(response.json()["entries"]) == count


def test_existing_days_parameter_reaches_older_plans(records_client):
    assert query(records_client, 2, 7).json()["item_count"] == 0
    assert query(records_client, 2, 30).json()["item_count"] == 6
    assert query(records_client, 1, 30).json()["item_count"] == 0
    assert query(records_client, 1, 90).json()["item_count"] == 20
    assert query(records_client, 1, 91).status_code == 422


def test_times_and_report_states_remain_separate_in_public_dto(records_client):
    entries = query(records_client, 3).json()["entries"]
    assert {row["intake_status"] for row in entries} == {"reported_taken", "reported_not_taken", "unsure", None}
    reported = next(row for row in entries if row["reported"])
    assert reported["event_time"] != reported["due_at"]
    assert "created_at" not in reported  # Not available for reconstructing ingestion/submission audit.
    assert any(not row["reported"] and row["event_time"] is None for row in entries)


def test_history_requires_auth_and_valid_owned_plan(records_client):
    assert records_client.get("/api/me/dose-history", params={"regimen_id": str(fixture_id(3))}).status_code == 401
    assert query(records_client, 999).status_code == 404
