"""VERIFIED LOCAL application/HTTP boundaries with deterministic memory persistence."""

from uuid import uuid4

import pytest
from app.agent.model_tools import model_tool_schemas
from app.transport.app_factory import create_app
from app.transport.container import build_container
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    return TestClient(create_app(build_container()))


def contact():
    return {
        "id": str(uuid4()),
        "name": "DEMO Caregiver",
        "relationship": "DEMO relative",
        "contact_type": "email",
        "contact_value": "DEMO.Caregiver@example.invalid",
        "storage_consent": True,
    }


def test_contact_create_retry_edit_reload_and_explicit_delete(client):
    url = "/api/me/caregivers?client_id=DEMO-care-A"
    details = contact()
    saved = client.post(url, json=details)
    assert saved.status_code == 200
    row = saved.json()
    assert row["contact_value"] == "demo.caregiver@example.invalid"
    assert row["verification_status"] == "pending" and not row["notifications_enabled"] and not row["sharing_enabled"]
    assert client.post(url, json=details).json() == row
    assert client.get(url).json() == [row]
    assert client.post(url, json={**details, "name": "DEMO Different retry"}).status_code == 422
    assert client.post(url, json={**details, "id": str(uuid4())}).status_code == 422
    update = {key: value for key, value in details.items() if key != "id"}
    changed = client.put(
        f"/api/me/caregivers/{row['id']}?client_id=DEMO-care-A", json={**update, "name": "DEMO Updated"}
    )
    assert changed.status_code == 200 and changed.json()["name"] == "DEMO Updated"
    assert client.get(url).json()[0]["name"] == "DEMO Updated"
    assert client.delete(f"/api/me/caregivers/{row['id']}?client_id=DEMO-care-A").status_code == 200
    assert client.get(url).json() == []


def test_contacts_are_owned_and_cannot_grant_authority_or_modify_medication(client):
    details = contact()
    a = "/api/me/caregivers?client_id=DEMO-care-A"
    row = client.post(a, json=details).json()
    b = f"/api/me/caregivers/{row['id']}?client_id=DEMO-care-B"
    assert client.get("/api/me/caregivers?client_id=DEMO-care-B").json() == []
    assert client.put(b, json={k: v for k, v in details.items() if k != "id"}).status_code == 404
    assert client.delete(b).status_code == 404
    for key, value in [
        ("patient_id", row["patient_id"]),
        ("verification_status", "verified"),
        ("sharing_enabled", True),
        ("notifications_enabled", True),
    ]:
        assert client.post(a, json={**details, key: value}).status_code == 422
    assert client.get(a).json() == [row]
    wired = client.app.state.container
    assert not wired.store.events and not wired.store.regimens
    assert all("caregiver" not in schema["name"] for schema in model_tool_schemas())


@pytest.mark.parametrize("value", [None, False, 1, "true"])
def test_permission_to_store_is_explicit(client, value):
    details = contact()
    assert (
        client.post("/api/me/caregivers?client_id=DEMO-care-A", json={**details, "storage_consent": value}).status_code
        == 422
    )


def test_phone_country_code_and_email_validation(client):
    url = "/api/me/caregivers?client_id=DEMO-care-A"
    details = contact()
    for value in ["bad-email", "one@example.invalid\nother@example.invalid"]:
        assert client.post(url, json={**details, "contact_value": value}).status_code == 422
    assert client.post(url, json={**details, "contact_type": "phone", "contact_value": "12345"}).status_code == 422
    valid = client.post(url, json={**details, "contact_type": "phone", "contact_value": "+1 (202) 555-0123"})
    assert valid.status_code == 200 and valid.json()["contact_value"] == "+12025550123"
