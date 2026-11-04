"""DEMO_ONLY scoped native device actions; sender is a non-network recording port."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.application.push_test import PushTestService
from app.contracts.notifications import DeliveryResult
from app.contracts.push import PushSubscriptionInput
from app.transport.auth import AuthenticatedPrincipal

from .notification_device_support import SyntheticSubscriptions
from .test_reminder_delivery import subscription
from .test_workflow_records import clinical

IDS = ("notification.subscribe", "notification.unsubscribe", "notification.test")


def configured(h, *, allowed=False, authenticated=False):
    port = SyntheticSubscriptions()
    h.container.push_subscriptions, h.container.push_public_key = port, subscription()["keys"]["p256dh"]
    calls = []
    h.container.push_test = PushTestService(SimpleNamespace(send=lambda delivery: (
        calls.append(delivery), DeliveryResult(status="sent"))[1]), h.clock)
    h.container.assistant_notification_test_allowed = allowed
    if authenticated:
        h.container.auth = SimpleNamespace(resolve=lambda **kw: AuthenticatedPrincipal(
            patient_id=h.owner_ids["A"], subject="DEMO verified fixture", email=None,
            authenticated=True, mode="synthetic_test"))
    return port, calls


def native(h, task, capability=None, *, owner="A", confirmed=True, headers=None, values=None):
    capability = capability or task["capability_id"]
    path = {"notification.subscribe": "/api/reminders/push/subscriptions",
            "notification.unsubscribe": "/api/reminders/push/unsubscribe",
            "notification.test": "/api/reminders/push/test"}[capability]
    return h.client.post(path, params={"client_id": "DEMO-workflow-" + owner}, json=values or subscription(),
        headers={"X-Assistant-Task": task["task_id"], "X-Assistant-Revision": str(task["revision"]),
                 "X-Patient-Confirmed": str(confirmed).lower(), **(headers or {})})


@pytest.mark.parametrize("capability", IDS)
def test_device_preparation_has_no_browser_subscription_sender_or_clinical_effect(workflow, capability):
    h = workflow
    port, calls = configured(h)
    before = clinical(h)
    task = h.start(capability)
    assert task["result_ref"] is None and task["input_fields"] == {}
    assert task["actions"][0]["kind"] == "device"
    h.view(task["task_id"])
    assert clinical(h) == before and not port.rows and not calls
    assert "endpoint" not in str(h.snapshot()) and "p256dh" not in str(task)


def test_saved_device_tasks_use_actual_owned_native_subscription_operations(workflow):
    h = workflow
    port, calls = configured(h)
    before = clinical(h)
    task = h.start("notification.subscribe")
    result = native(h, task)
    assert result.status_code == 200, result.text
    assert port.current(h.owner_ids["A"], subscription()["endpoint"]).enabled is True
    task = h.start("notification.unsubscribe")
    result = native(h, task)
    assert result.status_code == 204, result.text
    assert port.current(h.owner_ids["A"], subscription()["endpoint"]).enabled is False
    assert clinical(h) == before and not calls
    assert "DEMO-not-a-real-device" not in str(h.snapshot())
    assert h.view(task["task_id"])["result_ref"] is None


@pytest.mark.parametrize("change", ["owner", "operation", "revision", "paused", "revoked", "no_save", "confirmation"])
def test_device_native_binding_rejects_invalid_task_authority(workflow, change):
    h = workflow
    port, calls = configured(h)
    task = h.start("notification.subscribe", save=change != "no_save")
    options = {}
    if change == "owner":
        options["owner"] = "B"
    if change == "operation":
        options["capability"] = "notification.unsubscribe"
    if change == "revision":
        task = {**task, "revision": task["revision"] + 1}
    if change == "paused":
        h.event(task["task_id"], "pause")
    if change == "revoked":
        h.event(task["task_id"], "cancel_save")
    if change == "confirmation":
        options["confirmed"] = False
    response = native(h, task, **options)
    assert response.status_code in {404, 409, 422}, response.text
    assert not port.rows and not calls


@pytest.mark.parametrize("field,value", [("endpoint", "DEMO endpoint"), ("keys", {"auth": "DEMO"}),
    ("subscription_id", str(uuid4())), ("request_id", str(uuid4())), ("patient_id", str(uuid4()))])
def test_device_workflow_drafts_never_accept_subscription_credentials_or_native_ids(workflow, field, value):
    h = workflow
    response = h.client.post("/api/agent/workflows/tasks", params={"client_id": "DEMO-workflow-A"}, json={
        "capability_id": "notification.subscribe", "workspace_id": h.workspace_id,
        "client_event_id": str(uuid4()), "save_mode": "allowed", "values": {field: value}})
    assert response.status_code == 422


def test_notification_test_needs_server_approval_in_addition_to_authentication(workflow):
    h = workflow
    port, calls = configured(h, authenticated=True)
    row = port.save(h.owner_ids["A"], PushSubscriptionInput.model_validate(subscription()))
    task = h.start("notification.test")
    result = native(h, task, values={"subscription_id": str(row.id), "request_id": str(uuid4())})
    assert result.status_code == 503 and not calls
    catalog = h._request("GET", "/api/agent/workflows/capabilities")["capabilities"]
    test = next(row for row in catalog if row["id"] == "notification.test")
    assert test["available"] is False and test["reason"] == "notification_send_not_authorized"


def test_synthetic_approved_test_is_one_shot_even_after_native_cooldown_expires(workflow):
    h = workflow
    port, calls = configured(h, allowed=True, authenticated=True)
    row = port.save(h.owner_ids["A"], PushSubscriptionInput.model_validate(subscription()))
    task = h.start("notification.test")
    values = {"subscription_id": str(row.id), "request_id": str(uuid4())}
    assert native(h, task, confirmed=False, values=values).status_code in {409, 422}
    assert not calls
    response = native(h, task, values=values)
    assert response.status_code == 200 and response.json()["status"] == "sent", response.text
    h.clock.advance(seconds=61)
    assert native(h, task, values=values).status_code == 409
    assert len(calls) == 1 and not h.container.store.events
    assert "subscription_id" not in str(h.snapshot()) and task["result_ref"] is None


def test_partial_task_headers_cannot_fall_back_to_native_subscribe(workflow):
    h = workflow
    port, _ = configured(h)
    response = h.client.post("/api/reminders/push/subscriptions", params={"client_id": "DEMO-workflow-A"},
        json=subscription(), headers={"X-Assistant-Task": str(uuid4()), "X-Patient-Confirmed": "true"})
    assert response.status_code == 422 and not port.rows


@pytest.mark.parametrize("allowed,authenticated", [(False, True), (True, False), (True, True)])
def test_bound_device_configuration_reports_the_actual_test_gate(workflow, allowed, authenticated):
    h = workflow
    configured(h, allowed=allowed, authenticated=authenticated)
    task = h.start("notification.test")
    response = h.client.get("/api/reminders/push/config", params={"client_id": "DEMO-workflow-A"}, headers={
        "X-Assistant-Task": task["task_id"], "X-Assistant-Revision": str(task["revision"])})
    assert response.status_code == 200
    assert response.json()["test_available"] is (allowed and authenticated)


@pytest.mark.parametrize("capability", IDS)
def test_notification_device_adapter_never_becomes_a_model_writer(workflow, capability):
    h = workflow
    task = h.start(capability)
    with pytest.raises(AssertionError, match="422"):
        h.event(task["task_id"], "prepare_confirmation")
    assert h.view(task["task_id"])["result_ref"] is None


def test_failed_synthetic_sender_is_never_retried_from_the_same_task(workflow):
    from app.domain.errors import ProviderUnavailableError

    h = workflow
    port, calls = configured(h, allowed=True, authenticated=True)
    row = port.save(h.owner_ids["A"], PushSubscriptionInput.model_validate(subscription()))

    def fail(delivery):
        calls.append(delivery)
        raise ProviderUnavailableError("DEMO uncertain provider boundary")

    h.container.push_test = PushTestService(SimpleNamespace(send=fail), h.clock)
    task = h.start("notification.test")
    values = {"subscription_id": str(row.id), "request_id": str(uuid4())}
    assert native(h, task, values=values).status_code == 503
    h.clock.advance(seconds=61)
    assert native(h, task, values=values).status_code == 409
    assert len(calls) == 1


def test_device_id_revocation_cannot_cross_owner_and_preserves_other_devices(workflow):
    h = workflow
    port, _ = configured(h)
    own = port.save(h.owner_ids["A"], PushSubscriptionInput.model_validate(subscription()))
    other = port.save(h.owner_ids["B"], PushSubscriptionInput.model_validate(subscription()))
    task = h.start("notification.unsubscribe")
    headers = {"X-Assistant-Task": task["task_id"], "X-Assistant-Revision": str(task["revision"]),
               "X-Patient-Confirmed": "true"}
    assert h.client.delete(f"/api/reminders/push/subscriptions/{other.id}", headers=headers,
        params={"client_id": "DEMO-workflow-A"}).status_code == 404
    assert h.client.delete(f"/api/reminders/push/subscriptions/{own.id}", headers=headers,
        params={"client_id": "DEMO-workflow-A"}).status_code == 204
    assert port.current(h.owner_ids["B"], subscription()["endpoint"]).enabled is True


@pytest.mark.parametrize("text,capability", [("enable device notifications", IDS[0]), ("开启设备通知", IDS[0]),
    ("disable device notifications", IDS[1]), ("关闭设备通知", IDS[1]),
    ("test device notifications", IDS[2]), ("测试设备通知", IDS[2])])
def test_bilingual_device_entries_open_the_actual_scoped_page(workflow, text, capability):
    task = workflow._request("POST", "/api/agent/workflows/messages", json={"text": text,
        "workspace_id": workflow.workspace_id, "client_turn_id": str(uuid4())})["workflow"]
    assert task["capability_id"] == capability and task["result_ref"] is None
