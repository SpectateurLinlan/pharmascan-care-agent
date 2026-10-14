"""Deterministic in-memory accounting, with the same reservation semantics."""

from collections.abc import Callable
from datetime import datetime, time, timedelta
from threading import RLock
from uuid import UUID
from zoneinfo import ZoneInfo

from ..contracts.ports import Clock
from ..contracts.quota import Reservation, Usage
from ..domain.errors import ValidationError


class MemoryQuota:
    def __init__(self, *, clock: Clock, nonce_factory: Callable[[], str], limit: int = 20):
        self._clock, self._nonce, self._limit = clock, nonce_factory, limit
        self._usage = {}
        self._turns = {}
        self._lock = RLock()

    def usage(self, patient_id: UUID) -> Usage:
        with self._lock:
            zone = ZoneInfo("Asia/Singapore")
            day = self._clock.now().astimezone(zone).date()
            key = (patient_id, day)
            if key not in self._usage:
                self._usage[key] = Usage(
                    patient_id=patient_id,
                    usage_date=day,
                    llm_user_turns=0,
                    model_requests=0,
                    limit=self._limit,
                    next_reset_at=datetime.combine(day + timedelta(days=1), time(), zone),
                )
            return self._usage[key]

    def reserve(self, patient_id: UUID, turn_key: str) -> Reservation:
        with self._lock:
            usage = self.usage(patient_id)
            key = (patient_id, usage.usage_date, turn_key)
            nonce = self._nonce()
            now = self._clock.now()
            for k, row in list(self._turns.items()):
                if row[0] == "pending" and row[2] < now - timedelta(minutes=10):
                    self._turns[k] = ("failed", row[1], now)
            old = self._turns.get(key)
            state = "reserved"
            if old and old[0] in ["pending", "succeeded"]:
                state = "pending" if old[0] == "pending" else "completed"
            elif usage.llm_user_turns >= self._limit:
                state = "exhausted"
            elif (
                usage.llm_user_turns + sum(k[:2] == key[:2] and row[0] == "pending" for k, row in self._turns.items())
                >= self._limit
            ):
                state = "busy"
            if state == "reserved":
                self._turns[key] = ("pending", nonce, now)
            return Reservation(state=state, usage=usage, turn_key=turn_key, nonce=nonce)

    def _check(self, patient_id: UUID, reservation: Reservation):
        key = (patient_id, reservation.usage.usage_date, reservation.turn_key)
        row = self._turns.get(key)
        if not row or row[0] != "pending" or row[1] != reservation.nonce:
            raise ValidationError("Invalid reservation")
        return key

    def model_request(self, patient_id: UUID, reservation: Reservation) -> None:
        with self._lock:
            key = self._check(patient_id, reservation)
            self._turns[key] = ("pending", reservation.nonce, self._clock.now())
            u = self._usage[key[:2]]
            self._usage[key[:2]] = u.model_copy(update={"model_requests": u.model_requests + 1})

    def finish(self, patient_id: UUID, reservation: Reservation, success: bool) -> Usage:
        with self._lock:
            key = self._check(patient_id, reservation)
            self._turns[key] = ("succeeded" if success else "failed", reservation.nonce, self._clock.now())
            u = self._usage[key[:2]]
            self._usage[key[:2]] = u.model_copy(update={"llm_user_turns": u.llm_user_turns + int(success)})
            return self.usage(patient_id)
