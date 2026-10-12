"""Timezone handling: UTC storage, patient IANA timezone display.

Dose rule local times are interpreted in the patient timezone; every
timestamp persisted by services is timezone-aware UTC (AGENTS.md rule 10).
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo

DEFAULT_PATIENT_TZ = "Asia/Singapore"


class LocalTzProvider(Protocol):
    def local_tz(self, patient_id: object) -> ZoneInfo: ...


class FixedTzProvider:
    """Single-timezone provider for the P0 slice (all demo patients share SG)."""

    def __init__(self, tz_name: str = DEFAULT_PATIENT_TZ) -> None:
        self._tz = ZoneInfo(tz_name)

    def local_tz(self, patient_id: object) -> ZoneInfo:
        return self._tz


LOCAL_TZ_PROVIDER: LocalTzProvider = FixedTzProvider()


def to_utc(moment: datetime) -> datetime:
    """Return the same instant as timezone-aware UTC."""
    if moment.tzinfo is None:
        raise ValueError("naive datetime is not allowed; use timezone-aware values")
    return moment.astimezone(ZoneInfo("UTC"))


def local_date_of(utc_moment: datetime, tz: ZoneInfo) -> str:
    return utc_moment.astimezone(tz).date().isoformat()
