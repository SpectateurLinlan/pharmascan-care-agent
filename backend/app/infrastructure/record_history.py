"""Bounded same-user PostgREST reads and an explicitly synthetic memory adapter."""

from pydantic import ValidationError as SchemaError

from ..contracts.dto import DoseEventDTO, DoseOccurrenceDTO, PatientMedicationDTO, RegimenVersionDTO
from ..domain.errors import ProviderUnavailableError


class MemoryRecordHistory:
    def __init__(self, store):
        self._store = store

    def medications(self, owner):
        return [row for (patient, _), row in self._store.medications.items() if patient == owner]

    def plans(self, owner):
        return [row for (patient, _), row in self._store.regimens.items() if patient == owner]

    def scheduled(self, owner, plans, start, end, as_of, before, limit):
        rows = [
            row
            for (patient, _), row in self._store.occurrences.items()
            if patient == owner
            and (plans is None or row.regimen_id in plans)
            and (start is None or row.due_at >= start)
            and row.due_at < end
            and row.due_at <= as_of
            and (before is None or (row.due_at, row.id) < (before.time, before.id))
        ]
        return sorted(rows, key=lambda row: (row.due_at, row.id), reverse=True)[:limit]

    def unscheduled(self, owner, plans, start, end, as_of, before, limit):
        rows = [
            row
            for (patient, _), row in self._store.events.items()
            if patient == owner
            and row.occurrence_id is None
            and row.created_at <= as_of
            and (plans is None or row.regimen_id in plans)
            and (start is None or row.event_time >= start)
            and row.event_time < end
            and row.event_time <= as_of
            and (before is None or (row.event_time, row.id) < (before.time, before.id))
        ]
        return sorted(rows, key=lambda row: (row.event_time, row.id), reverse=True)[:limit]

    def reports(self, owner, occurrences, as_of):
        return [
            row
            for (patient, _), row in self._store.events.items()
            if patient == owner and row.occurrence_id in occurrences and row.created_at <= as_of
        ]


class SupabaseRecordHistory:
    def __init__(self, client):
        self._client = client

    def _decode(self, owner, dto, rows):
        try:
            # PostgREST physical rows include provenance/creation columns that
            # are not HTTP DTO fields. Normalize at this adapter boundary.
            values = [
                dto.model_validate({key: value for key, value in row.items() if key in dto.model_fields})
                for row in rows
            ]
        except SchemaError as error:
            raise ProviderUnavailableError("Invalid medication history response.") from error
        if any(row.patient_id != owner for row in values):
            raise ProviderUnavailableError("Record ownership could not be verified.")
        return values

    def _batch(self, table, filters, limit):
        filters = dict(filters)
        if "and_" in filters:
            filters["and"] = filters.pop("and_")
        result, expected = [], None
        for _ in range(limit):
            batch, total = self._client.request(
                "GET",
                "/rest/v1/" + table,
                params={**filters, "offset": str(len(result)), "limit": str(limit - len(result))},
                prefer="count=exact",
                include_total=True,
            )
            if expected is not None and expected != total:
                raise ProviderUnavailableError("Records changed during loading. Please retry.")
            expected = total
            if not isinstance(batch, list) or not all(isinstance(row, dict) for row in batch):
                raise ProviderUnavailableError("Invalid medication history response.")
            if not isinstance(total, int) or total < 0 or not all(isinstance(row.get("id"), str) for row in batch):
                raise ProviderUnavailableError("Invalid medication history response.")
            result.extend(batch)
            if len(result) > min(limit, total) or len({row.get("id") for row in result}) != len(result):
                raise ProviderUnavailableError("Complete records could not be verified. Please retry.")
            if len(result) == min(limit, total):
                return result
            if not batch:
                break
        raise ProviderUnavailableError("Complete records could not be verified. Please retry.")

    def medications(self, owner):
        self._client.check_patient(owner)
        return self._decode(
            owner,
            PatientMedicationDTO,
            self._client.all_rows("patient_medications", patient_id=f"eq.{owner}", select="*"),
        )

    def plans(self, owner):
        self._client.check_patient(owner)
        # Optional DTO fields may belong to a later schema (patient_edited in
        # 027). Read existing physical columns, preserving newer flags when
        # present, instead of demanding uninstalled columns in SELECT.
        return self._decode(
            owner, RegimenVersionDTO, self._client.all_rows("regimen_versions", patient_id=f"eq.{owner}", select="*")
        )

    def _page(self, owner, table, dto, time, plans, start, end, as_of, before, limit, **extra):
        self._client.check_patient(owner)
        clauses = [
            f"{time}.lt.{end.isoformat()}",
            f"{time}.lte.{as_of.isoformat()}",
            f"created_at.lte.{as_of.isoformat()}",
        ]
        if start:
            clauses.append(f"{time}.gte.{start.isoformat()}")
        filters = dict(
            patient_id=f"eq.{owner}",
            select=",".join(dto.model_fields),
            and_="(" + ",".join(clauses) + ")",
            order=f"{time}.desc,id.desc",
            limit=str(limit),
            **extra,
        )
        if plans is not None:
            if not plans:
                return []
            filters["regimen_id"] = "in.(" + ",".join(map(str, plans)) + ")"
        if before:
            stamp = before.time.isoformat()
            filters["or"] = f"({time}.lt.{stamp},and({time}.eq.{stamp},id.lt.{before.id}))"
        return self._decode(owner, dto, self._batch(table, filters, limit))

    def scheduled(self, owner, plans, start, end, as_of, before, limit):
        return self._page(
            owner, "dose_occurrences", DoseOccurrenceDTO, "due_at", plans, start, end, as_of, before, limit
        )

    def unscheduled(self, owner, plans, start, end, as_of, before, limit):
        return self._page(
            owner,
            "dose_events",
            DoseEventDTO,
            "event_time",
            plans,
            start,
            end,
            as_of,
            before,
            limit,
            occurrence_id="is.null",
        )

    def reports(self, owner, occurrences, as_of):
        self._client.check_patient(owner)
        if not occurrences:
            return []
        filters = dict(
            patient_id=f"eq.{owner}",
            occurrence_id="in.(" + ",".join(map(str, occurrences)) + ")",
            created_at=f"lte.{as_of.isoformat()}",
            select=",".join(DoseEventDTO.model_fields),
            order="id.asc",
        )
        rows = self._batch("dose_events", filters, len(occurrences) + 1)
        if len(rows) > len(occurrences):
            raise ProviderUnavailableError("Record relationships could not be verified.")
        return self._decode(owner, DoseEventDTO, rows)
