"""Memory and same-user JWT health-note adapters."""

from datetime import datetime
from uuid import UUID

from ..contracts.observations import Observation
from .supabase_data import SupabaseDataClient


class MemoryObservations:
    def __init__(self):
        self._rows: dict[tuple[UUID, UUID], Observation] = {}

    def get(self, patient_id: UUID, observation_id: UUID) -> Observation | None:
        return self._rows.get((patient_id, observation_id))

    def list(self, patient_id: UUID, start: datetime, end: datetime) -> list[Observation]:
        return sorted(
            [row for (owner, _), row in self._rows.items() if owner == patient_id and start <= row.occurred_at < end],
            key=lambda row: row.occurred_at,
            reverse=True,
        )[:500]

    def save(self, record: Observation) -> Observation:
        self._rows[record.patient_id, record.id] = record
        return record

    def delete(self, patient_id: UUID, observation_id: UUID) -> None:
        self._rows.pop((patient_id, observation_id), None)


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
