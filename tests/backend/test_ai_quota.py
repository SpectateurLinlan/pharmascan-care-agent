"""Atomic concurrent allowance and Singapore date boundary, no provider calls."""

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from app.domain.errors import ValidationError
from app.infrastructure.memory_quota import MemoryQuota


def test_concurrent_reservations_success_failure_and_foreign_capability(clock):
    quota = MemoryQuota(clock=clock, nonce_factory=lambda: "SIMULATED-capability")
    a, b = UUID(int=100), UUID(int=200)
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(lambda i: quota.reserve(a, str(i)), range(30)))
    assert sum(row.state == "reserved" for row in rows) == 20
    for row in rows:
        if row.state == "reserved":
            quota.model_request(a, row)
            quota.finish(a, row, True)
    assert quota.usage(a).llm_user_turns == 20 and quota.reserve(a, "next").state == "exhausted"
    assert quota.usage(b).llm_user_turns == 0
    first = quota.reserve(b, "retry")
    quota.model_request(b, first)
    quota.finish(b, first, False)
    assert quota.usage(b).llm_user_turns == 0 and quota.usage(b).model_requests == 1
    again = quota.reserve(b, "retry")
    quota.finish(b, again, True)
    with pytest.raises(ValidationError):
        quota.finish(b, again, False)
    with pytest.raises(ValidationError):
        quota.model_request(a, again)


def test_midnight_singapore_resets_new_turns_but_inflight_finishes_on_original_day(clock):
    clock.advance(hours=40, minutes=59, seconds=59)
    quota = MemoryQuota(clock=clock, nonce_factory=lambda: "SIMULATED")
    patient = UUID(int=100)
    reservation = quota.reserve(patient, "before-midnight")
    assert reservation.usage.next_reset_at.isoformat().startswith("2026-10-15T00:00:00")
    clock.advance(seconds=2)
    quota.finish(patient, reservation, True)
    assert quota.usage(patient).usage_date.isoformat() == "2026-10-15"
    assert quota.usage(patient).llm_user_turns == 0
