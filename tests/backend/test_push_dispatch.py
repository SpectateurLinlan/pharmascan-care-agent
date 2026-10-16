"""LOCAL/MOCK: actual HTTP/application/provider adapters, synthetic I/O only."""

import hashlib
import hmac
import subprocess
import time
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from app.application.notification_dispatch import NotificationDispatchService
from app.application.notification_worker import NotificationWorker
from app.application.push_test import PushTestLimited, PushTestService
from app.contracts.notifications import Delivery, DeliveryResult, DispatchResult
from app.contracts.push import PushSubscriptionInput, PushSubscriptionRecord
from app.domain.errors import AuthenticationRequiredError, NotFoundError
from app.infrastructure.dispatch_process import DispatchTimeout, DispatchUnavailable, ProcessDispatchRunner
from app.infrastructure.web_push import validate_vapid
from app.transport.app_factory import create_app
from app.transport.auth import AuthenticatedPrincipal
from app.transport.container import build_container
from app.transport.dispatcher import create_dispatcher_app
from fastapi.testclient import TestClient

from tests.backend.conftest import FixedClock
from tests.backend.test_reminder_delivery import subscription

TOKEN = "DEMO-not-a-real-dispatch-key-" + "x" * 32
OWNER = UUID(int=101)
OTHER = UUID(int=102)


def dispatch_headers(stamp=None):
    stamp = str(int(time.time())) if stamp is None else str(stamp)
    message = f"POST\n/internal/notifications/dispatch\n{stamp}".encode()
    return {
        "X-Dispatch-Timestamp": stamp,
        "X-Dispatch-Signature": hmac.new(TOKEN.encode(), message, hashlib.sha256).hexdigest(),
    }


class Sender:
    def __init__(self, status="sent"):
        self.calls = []
        self.status = status

    def send(self, delivery):
        self.calls.append(delivery)
        return DeliveryResult(status=self.status)


class Subscriptions:
    def __init__(self):
        self.id = uuid4()
        self.enabled = True

    def credentials(self, owner, sid):
        return PushSubscriptionInput(**subscription()) if owner == OWNER and sid == self.id and self.enabled else None

    def revoke(self, owner, sid):
        assert owner == OWNER and sid == self.id
        self.enabled = False

    def current(self, owner, endpoint):
        if owner == OWNER and endpoint == subscription()["endpoint"]:
            return PushSubscriptionRecord(id=self.id, enabled=self.enabled)
        return None


def test_synthetic_single_send_uses_application_worker_and_limits():
    sender = Sender()
    deliveries = [
        Delivery(id=uuid4(), subscription_id=uuid4(), subscription=subscription(), attempts=1) for _ in range(8)
    ]
    completed = []
    repository = SimpleNamespace(
        claim=lambda now: deliveries.pop() if deliveries else None,
        finish=lambda delivery, result, now: completed.append((delivery.id, result.status)),
    )

    @contextmanager
    def lease():
        yield True

    service = NotificationDispatchService(
        worker=NotificationWorker(repository, sender, FixedClock()),
        project=lambda available: 1,
        lease=lease,
        monotonic=lambda: 0,
    )
    # Actual protected HTTP -> public application pass -> existing Worker ->
    # mock sender/repository. Only the subprocess boundary is injected locally.
    client = TestClient(
        create_dispatcher_app(
            runner=SimpleNamespace(run=lambda: service.run(limit=1)),
            token=TOKEN,
        )
    )
    result = client.post("/internal/notifications/dispatch", headers=dispatch_headers())
    assert result.json()["processed"] == 1 and len(sender.calls) == 1 and completed[0][1] == "sent"
    assert len(deliveries) == 7
    with pytest.raises(ValueError):
        service.run(limit=51)


def test_overlap_and_expired_budget_do_not_send():
    sender = Sender()

    @contextmanager
    def busy():
        yield False

    worker = NotificationWorker(SimpleNamespace(), sender, FixedClock())
    service = NotificationDispatchService(
        worker=worker, project=lambda available: pytest.fail("no projection"), lease=busy, monotonic=lambda: 0
    )
    assert service.run().status == "busy"

    @contextmanager
    def acquired():
        yield True

    values = iter([0, 30, 30])
    service = NotificationDispatchService(
        worker=worker, project=lambda available: 0, lease=acquired, monotonic=lambda: next(values)
    )
    assert service.run().status == "budget_exhausted" and not sender.calls


def test_dispatcher_auth_and_separation(caplog):
    calls = []
    runner = SimpleNamespace(run=lambda: calls.append(True) or DispatchResult(status="completed", processed=1))
    app = TestClient(create_dispatcher_app(runner=runner, token=TOKEN))
    health = app.get("/health")
    assert health.status_code == 200 and health.json() == {"status": "ok"}
    assert health.headers["Cache-Control"] == "no-store" and not calls
    assert app.post("/internal/notifications/dispatch").status_code == 401
    assert (
        app.post("/internal/notifications/dispatch", headers={"Authorization": "Bearer patient-jwt"}).status_code == 401
    )
    headers = dispatch_headers()
    assert (
        app.post("/internal/notifications/dispatch", headers={**headers, "Origin": "https://app.invalid"}).status_code
        == 400
    )
    assert app.post("/internal/notifications/dispatch?limit=500", headers=headers).status_code == 400
    assert (
        app.post("/internal/notifications/dispatch", headers=headers, json={"patient_id": str(OTHER)}).status_code
        == 400
    )
    assert not calls
    assert (
        app.post("/internal/notifications/dispatch", headers=dispatch_headers(int(time.time()) - 120)).status_code
        == 401
    )
    assert (
        app.post("/internal/notifications/dispatch", headers={**headers, "X-Dispatch-Signature": "0" * 64}).status_code
        == 401
    )
    response = app.post("/internal/notifications/dispatch", headers=headers)
    assert response.status_code == 200 and response.json()["processed"] == 1
    assert response.headers["cache-control"] == "no-store" and len(calls) == 1
    assert app.post("/internal/notifications/dispatch", headers=headers, content=b"{}").status_code == 200
    assert TOKEN not in caplog.text and str(OTHER) not in caplog.text
    patient_app = TestClient(create_app(container=build_container()))
    assert patient_app.post("/internal/notifications/dispatch", headers=headers).status_code == 404


@pytest.mark.parametrize("error,code", [(DispatchTimeout, 504), (DispatchUnavailable, 503)])
def test_dispatcher_safe_failure(error, code):
    def fail():
        raise error("DO-NOT-LEAK")

    client = TestClient(create_dispatcher_app(runner=SimpleNamespace(run=fail), token=TOKEN))
    result = client.post("/internal/notifications/dispatch", headers=dispatch_headers())
    assert result.status_code == code and "DO-NOT-LEAK" not in result.text


def test_subprocess_has_hard_timeout_and_fixed_batch():
    from pathlib import Path

    def execute(command, **kwargs):
        assert command[-4:] == ["--limit", "5", "--budget", "20"]
        assert kwargs["timeout"] == 25 and kwargs["capture_output"]
        assert kwargs["cwd"] == Path("/worker-project")
        assert command[1] == str(Path("/worker-project") / "scripts/run_reminders.py")
        return SimpleNamespace(returncode=0, stdout='{"status":"completed","processed":1}')

    assert ProcessDispatchRunner(execute=execute, root=Path("/worker-project")).run().processed == 1

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("DEMO", 25)

    with pytest.raises(DispatchTimeout):
        ProcessDispatchRunner(execute=timeout).run()
    with pytest.raises(DispatchUnavailable):
        ProcessDispatchRunner(execute=lambda *a, **kw: SimpleNamespace(returncode=1)).run()


def test_test_push_is_owned_private_replay_safe_and_nonclinical():
    sender, subscriptions, clock = Sender(), Subscriptions(), FixedClock()
    service = PushTestService(sender, clock)
    key = uuid4()
    with pytest.raises(NotFoundError):
        service.send(OTHER, subscriptions.id, key, subscriptions)
    first = service.send(OWNER, subscriptions.id, key, subscriptions, "zh")
    assert first.status == "sent" and len(sender.calls) == 1
    assert sender.calls[0].purpose == "test" and sender.calls[0].language == "zh"
    assert service.send(OWNER, subscriptions.id, key, subscriptions) == first and len(sender.calls) == 1
    with pytest.raises(PushTestLimited):
        service.send(OWNER, subscriptions.id, uuid4(), subscriptions)
    clock.advance(seconds=61)
    sender.status = "expired_subscription"
    assert service.send(OWNER, subscriptions.id, uuid4(), subscriptions).status == "expired_subscription"
    assert not subscriptions.enabled


def test_patient_api_cannot_choose_owner_or_return_credentials():
    subscriptions, sender = Subscriptions(), Sender()
    container = build_container()
    container.push_subscriptions = subscriptions
    container.push_test = PushTestService(sender, container.clock)
    principal = AuthenticatedPrincipal(
        patient_id=OWNER, subject=str(OWNER), email=None, authenticated=True, mode="supabase"
    )
    container.auth = SimpleNamespace(resolve=lambda **kwargs: principal)
    client = TestClient(create_app(container=container))
    current = client.post("/api/reminders/push/current", json=subscription())
    assert current.json() == {"id": str(subscriptions.id), "enabled": True}
    assert "keys" not in current.text and "endpoint" not in current.text
    payload = {"subscription_id": str(subscriptions.id), "request_id": str(uuid4())}
    assert client.post("/api/reminders/push/test", json={**payload, "patient_id": str(OTHER)}).status_code == 422
    assert client.post("/api/reminders/push/test", json={**payload, "subscription_id": str(uuid4())}).status_code == 404
    assert client.post("/api/reminders/push/test", json=payload).json()["status"] == "sent"
    assert len(sender.calls) == 1


def test_patient_subscription_routes_require_owner_but_no_sender_credentials():
    class OwnedSubscriptions:
        def __init__(self):
            self.rows = {}

        def save(self, owner, value):
            row = PushSubscriptionRecord(id=uuid4(), enabled=True)
            self.rows[(owner, value.endpoint)] = row
            return row

        def list_for_patient(self, owner):
            return [row for (patient, _), row in self.rows.items() if patient == owner]

        def revoke(self, owner, sid):
            for key, row in list(self.rows.items()):
                if key[0] == owner and row.id == sid:
                    self.rows[key] = row.model_copy(update={"enabled": False})

    subscriptions = OwnedSubscriptions()
    container = build_container()
    container.push_subscriptions = subscriptions
    container.push_public_key = "synthetic-public-key"
    container.push_test = None

    def resolve(**kwargs):
        token = kwargs.get("authorization")
        if token not in {"Bearer owner", "Bearer other"}:
            raise AuthenticationRequiredError()
        owner = OWNER if token == "Bearer owner" else OTHER
        return AuthenticatedPrincipal(
            patient_id=owner,
            subject=str(owner),
            email=None,
            authenticated=True,
            mode="supabase",
        )

    container.auth = SimpleNamespace(resolve=resolve)
    client = TestClient(create_app(container=container))
    headers = {"Authorization": "Bearer owner"}
    assert client.get("/api/reminders/push/config").status_code == 401
    assert client.post("/api/reminders/push/subscriptions", json=subscription()).status_code == 401
    assert client.get("/api/reminders/push/config", headers=headers).json() == {
        "available": True,
        "public_key": "synthetic-public-key",
        "test_available": False,
    }
    saved = client.post("/api/reminders/push/subscriptions", json=subscription(), headers=headers)
    assert saved.status_code == 200
    assert set(saved.json()) == {"id", "enabled"}
    assert len(client.get("/api/reminders/push/subscriptions", headers=headers).json()) == 1
    assert client.get("/api/reminders/push/subscriptions", headers={"Authorization": "Bearer other"}).json() == []
    assert (
        client.post(
            "/api/reminders/push/test",
            json={"subscription_id": saved.json()["id"], "request_id": str(uuid4())},
            headers=headers,
        ).status_code
        == 503
    )
    assert (
        client.delete(
            f"/api/reminders/push/subscriptions/{saved.json()['id']}",
            headers={"Authorization": "Bearer other"},
        ).status_code
        == 204
    )
    assert client.get("/api/reminders/push/subscriptions", headers=headers).json()[0]["enabled"] is True
    assert client.delete(f"/api/reminders/push/subscriptions/{saved.json()['id']}", headers=headers).status_code == 204
    assert client.get("/api/reminders/push/subscriptions", headers=headers).json()[0]["enabled"] is False


def test_invalid_vapid_and_dispatch_secret_fail_closed():
    with pytest.raises(ValueError, match="VAPID"):
        validate_vapid("DEMO", "DEMO", "https://contact.invalid")
    with pytest.raises(ValueError, match="PUSH_DISPATCH_TOKEN"):
        create_dispatcher_app(token="short")


def test_valid_synthetic_vapid_pair_and_mismatch():
    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    # Publicly known scalar; fixture only, never a deployed notification identity.
    key = ec.derive_private_key(1, ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)

    def encode(value):
        return base64.urlsafe_b64encode(value).decode().rstrip("=")

    validate_vapid(encode(public), encode((1).to_bytes(32, "big")), "mailto:demo@example.invalid")
    with pytest.raises(ValueError):
        validate_vapid(encode(public), encode((2).to_bytes(32, "big")), "mailto:demo@example.invalid")


def test_worker_rejects_transaction_pool_before_connecting(monkeypatch):
    from app.transport import worker_container

    monkeypatch.setattr(worker_container, "validate_vapid", lambda *args: None)
    config = SimpleNamespace(
        enable_web_push=True,
        vapid_public_key="DEMO",
        vapid_private_key="DEMO",
        vapid_subject="mailto:demo@example.invalid",
        require_database_url=lambda: "postgresql://demo:DEMO@pooler.invalid:6543/demo",
    )
    with pytest.raises(ValueError, match="transaction pool6543"):
        worker_container.build_worker_dispatch(config)
