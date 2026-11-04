"""Explicit loopback DEMO fixed-clock reminder acceptance; never deploy."""

from datetime import UTC, datetime

from .assistant_enrollment_runtime import create_app as enrollment_app
from .conftest import FixedClock


def create_app():
    return enrollment_app(clock=FixedClock(datetime(2026, 10, 27, 12, 0, tzinfo=UTC)))
