"""Loopback DEMO repository/browser acceptance; sender only records synthetic calls."""

from dataclasses import replace
from types import SimpleNamespace

from app.application.push_test import PushTestService
from app.contracts.notifications import DeliveryResult

from .assistant_reminder_runtime import create_app as reminder_app
from .notification_device_support import SyntheticSubscriptions
from .test_reminder_delivery import subscription


def create_app():
    app = reminder_app()
    root = app.state.container
    root.push_subscriptions = SyntheticSubscriptions()
    root.push_public_key = subscription()["keys"]["p256dh"]
    root.assistant_notification_test_allowed = True  # Fixture only; no sender/network credentials exist.
    root.push_test = PushTestService(SimpleNamespace(send=lambda delivery: DeliveryResult(status="sent")), root.clock)
    original = root.auth.resolve

    def resolve(**kwargs):
        principal = original(**kwargs)
        return replace(principal, authenticated=True, mode="synthetic_test_only")

    root.auth = SimpleNamespace(resolve=resolve, mode=root.auth.mode)
    return app
