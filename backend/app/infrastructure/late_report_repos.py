"""Append-only patient report corrections; originals are never changed."""

from ..contracts.dto import DoseEventDTO
from ..contracts.enums import OccurrenceStatus
from ..contracts.late_reports import LateReportRecord
from ..domain.errors import ConfirmationRequiredError, ValidationError


def effective_memory_events(store, as_of=None):
    with store.late_report_lock:
        rows = {
            (event.patient_id, event.occurrence_id or event.id): event
            for event in store.events.values()
            if as_of is None or event.created_at <= as_of
        }
        for report in sorted(store.late_reports.values(), key=lambda row: row.version):
            if as_of and report.recorded_at > as_of:
                continue
            rows[report.patient_id, report.occurrence_id] = DoseEventDTO(
                id=report.id,
                patient_id=report.patient_id,
                occurrence_id=report.occurrence_id,
                regimen_id=report.regimen_id,
                event_time=report.recorded_at,
                created_at=report.recorded_at,
                intake_status=report.intake_status,
                idempotency_key=report.idempotency_key,
                reported_late=True,
                actual_administration_at=report.actual_administration_at,
            )
        return list(rows.values())


class MemoryLateReports:
    def histories(self, patient_id, occurrence_ids):
        selected = set(occurrence_ids)
        return sorted(
            [row for row in self.store.late_reports.values()
             if row.patient_id == patient_id and row.occurrence_id in selected],
            key=lambda row: row.version,
        )

    def __init__(self, store):
        self.store = store

    def original(self, patient_id, occurrence_id):
        return next(
            (
                row
                for row in self.store.events.values()
                if row.patient_id == patient_id and row.occurrence_id == occurrence_id
            ),
            None,
        )

    def history(self, patient_id, occurrence_id):
        return sorted(
            [
                row
                for row in self.store.late_reports.values()
                if row.patient_id == patient_id and row.occurrence_id == occurrence_id
            ],
            key=lambda row: row.version,
        )

    def save(self, patient_id, occurrence_id, values, challenge_id, now):
        with self.store.late_report_lock:
            existing = self.store.late_reports.get((patient_id, values.id))
            if existing:
                if existing.idempotency_key != values.binding_key(occurrence_id):
                    raise ValidationError("Report key reused")
                return existing
            occurrence = self.store.occurrences.get((patient_id, occurrence_id))
            if occurrence is None:
                raise ValidationError("Owned occurrence required")
            current = next(
                (
                    row
                    for row in effective_memory_events(self.store)
                    if row.patient_id == patient_id and row.occurrence_id == occurrence_id
                ),
                None,
            )
            if (current.id if current else None) != values.expected_report_id:
                raise ValidationError("Report changed; reload before correcting it")
            challenge = self.store.challenges.get((patient_id, challenge_id))
            session = self.store.sessions.get((patient_id, challenge.session_id)) if challenge else None
            if (
                not challenge
                or not session
                or session.state != "awaiting_confirmation"
                or session.expires_at <= now
                or session.state_version != challenge.session_state_version
                or not challenge.confirmed_at
                or challenge.consumed_at
                or challenge.expires_at <= now
                or challenge.idempotency_key != values.binding_key(occurrence_id)
            ):
                raise ConfirmationRequiredError("A current matching confirmation is required")
            history = self.history(patient_id, occurrence_id)
            if len(history) >= 100:
                raise ValidationError("Report correction history limit reached")
            row = LateReportRecord(
                **values.model_dump(),
                patient_id=patient_id,
                occurrence_id=occurrence_id,
                regimen_id=occurrence.regimen_id,
                recorded_at=now,
                version=len(history) + 1,
                idempotency_key=values.binding_key(occurrence_id),
            )
            self.store.late_reports[patient_id, row.id] = row
            self.store.challenges[patient_id, challenge_id] = challenge.model_copy(update={"consumed_at": now})
            self.store.occurrences[patient_id, occurrence_id] = occurrence.model_copy(
                update={"status": OccurrenceStatus.CLOSED}
            )
            return row


class SupabaseLateReports:
    def histories(self, patient_id, occurrence_ids):
        self.client.check_patient(patient_id)
        ids = list(dict.fromkeys(occurrence_ids))
        result = []
        for offset in range(0, len(ids), 20):
            selected = ",".join(str(value) for value in ids[offset:offset + 20])
            result.extend(
                LateReportRecord.model_validate(row) for row in self.client.all_rows(
                    "dose_report_entries", patient_id=f"eq.{patient_id}",
                    occurrence_id=f"in.({selected})", order="version.asc,id.asc",
                )
            )
        return sorted(result, key=lambda row: row.version)

    def __init__(self, client):
        self.client = client

    def original(self, patient_id, occurrence_id):
        self.client.check_patient(patient_id)
        rows = self.client.rows(
            "dose_events", patient_id=f"eq.{patient_id}", occurrence_id=f"eq.{occurrence_id}", limit="1"
        )
        return (
            DoseEventDTO.model_validate(
                {key: value for key, value in rows[0].items() if key in DoseEventDTO.model_fields}
            )
            if rows
            else None
        )

    def history(self, patient_id, occurrence_id):
        self.client.check_patient(patient_id)
        return [
            LateReportRecord.model_validate(row)
            for row in self.client.all_rows(
                "dose_report_entries",
                patient_id=f"eq.{patient_id}",
                occurrence_id=f"eq.{occurrence_id}",
                order="version.asc",
            )
        ]

    def save(self, patient_id, occurrence_id, values, challenge_id, now):
        self.client.check_patient(patient_id)
        row = self.client.request(
            "POST",
            "/rest/v1/rpc/record_late_dose_report",
            body={
                "p_occurrence_id": str(occurrence_id),
                "p_values": values.model_dump(mode="json"),
                "p_challenge_id": str(challenge_id),
            },
        )
        return LateReportRecord.model_validate(row)


class PostgresLateReports:
    def histories(self, patient_id, occurrence_ids):
        if not occurrence_ids:
            return []
        with self.session(patient_id) as conn:
            rows = conn.execute(
                "SELECT * FROM public.dose_report_entries WHERE patient_id=%s "
                "AND occurrence_id=ANY(%s) ORDER BY version,id",
                (patient_id, list(dict.fromkeys(occurrence_ids))),
            ).fetchall()
        return [LateReportRecord.model_validate(dict(row)) for row in rows]

    def __init__(self, session):
        self.session = session

    def original(self, patient_id, occurrence_id):
        with self.session(patient_id) as conn:
            row = conn.execute(
                "SELECT * FROM public.dose_events WHERE patient_id=%s AND occurrence_id=%s", (patient_id, occurrence_id)
            ).fetchone()
        return (
            DoseEventDTO.model_validate({key: value for key, value in row.items() if key in DoseEventDTO.model_fields})
            if row
            else None
        )

    def history(self, patient_id, occurrence_id):
        with self.session(patient_id) as conn:
            rows = conn.execute(
                "SELECT * FROM public.dose_report_entries WHERE patient_id=%s AND occurrence_id=%s ORDER BY version",
                (patient_id, occurrence_id),
            ).fetchall()
        return [LateReportRecord.model_validate(dict(row)) for row in rows]

    def save(self, patient_id, occurrence_id, values, challenge_id, now):
        from psycopg.types.json import Jsonb

        with self.session(patient_id) as conn:
            result = conn.execute(
                "SELECT public.record_late_dose_report(%s,%s,%s) AS result",
                (occurrence_id, Jsonb(values.model_dump(mode="json")), challenge_id),
            ).fetchone()
        return LateReportRecord.model_validate(result["result"])
