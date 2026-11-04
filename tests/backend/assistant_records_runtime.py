"""Explicit loopback DEMO clock: one current scheduled dose without any backfill."""

from datetime import UTC, datetime

from .assistant_enrollment_runtime import create_app as enrollment_app
from .conftest import FixedClock


def create_app():
    # The parent enforces MEDITHREAD_LOCAL_ACCEPTANCE=1, never a production entry.
    return enrollment_app(clock=FixedClock(datetime(2026, 10, 27, 12, 0, tzinfo=UTC)))
