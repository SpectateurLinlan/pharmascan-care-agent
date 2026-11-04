"""Memory and same-user JWT health-note adapters."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from threading import RLock
from uuid import UUID

from ..contracts.observations import Observation
from .supabase_data import SupabaseDataClient


class MemoryObservations:
    def __init__(self):
        self._rows: dict[tuple[UUID, UUID], Observation] = {}
        self._revisions: dict[UUID,int] = {}
        self._lock=RLock()

    def revision(self,owner):
        with self._lock:
            return self._revisions.get(owner,0)

    @contextmanager
    def local_transaction(self):
        with self._lock:
            rows,revisions=deepcopy(self._rows),dict(self._revisions)
            try:
                yield
            except BaseException:
                self._rows.clear()
                self._rows.update(rows)
                self._revisions.clear()
                self._revisions.update(revisions)
                raise

    def get(self, patient_id: UUID, observation_id: UUID) -> Observation | None:
        with self._lock:
            return self._rows.get((patient_id, observation_id))

    def list(self, patient_id: UUID, start: datetime, end: datetime) -> list[Observation]:
        with self._lock:
            return sorted(
                [row for (owner, _), row in self._rows.items()
                 if owner == patient_id and start <= row.occurred_at < end],
                key=lambda row: row.occurred_at, reverse=True,
            )[:500]

    def save(self, record: Observation) -> Observation:
        with self._lock:
            self._rows[record.patient_id, record.id] = record
            self._revisions[record.patient_id]=self._revisions.get(record.patient_id,0)+1
            return record

    def delete(self, patient_id: UUID, observation_id: UUID) -> None:
        with self._lock:
            if self._rows.pop((patient_id, observation_id), None) is not None:
                self._revisions[patient_id]=self._revisions.get(patient_id,0)+1


class SupabaseObservations:
    def __init__(self, client: SupabaseDataClient):
        self._client = client

    def get(self, patient_id: UUID, observation_id: UUID) -> Observation | None:
        self._client.check_patient(patient_id)
        rows = self._client.rows("health_observations", id=f"eq.{observation_id}")
        return Observation.model_validate(rows[0]) if rows else None

    def list(self, patient_id: UUID, start: datetime, end: datetime) -> list[Observation]:
        self._client.check_patient(patient_id)
        rows = self._client.rows(
            "health_observations",
            and_=f"(occurred_at.gte.{start.isoformat()},occurred_at.lt.{end.isoformat()})",
            order="occurred_at.desc",
            limit="500",
        )
        return [Observation.model_validate(row) for row in rows]

    def save(self, record: Observation) -> Observation:
        self._client.check_patient(record.patient_id)
        rows = self._client.request(
            "POST",
            "/rest/v1/health_observations",
            params={"on_conflict": "patient_id,id"},
            body=record.model_dump(mode="json"),
            prefer="resolution=merge-duplicates,return=representation",
        )
        return Observation.model_validate(rows[0])

    def delete(self, patient_id: UUID, observation_id: UUID) -> None:
        self._client.check_patient(patient_id)
        self._client.request("DELETE", "/rest/v1/health_observations", params={"id": f"eq.{observation_id}"})
