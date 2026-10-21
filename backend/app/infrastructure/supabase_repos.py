"""User-token PostgREST implementations of the existing repository ports.

DTOs are normalized here; provider objects never reach the application.
The client belongs to one request, and cannot fall back to PostgreSQL.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel

from ..contracts.dto import (
    ActivationResultDTO,
    AgentSessionDTO,
    ConfirmationChallengeDTO,
    DoseEventDTO,
    DoseOccurrenceDTO,
    DoseRuleDTO,
    PatientMedicationDTO,
    RegimenVersionDTO,
    SourceDocumentDTO,
    SourceFieldDTO,
    ToolTraceDTO,
)
from ..domain.errors import ConfirmationRequiredError, NotFoundError, ProviderUnavailableError, ValidationError
from .supabase_data import SupabaseDataClient

T = TypeVar("T", bound=BaseModel)


class Repository(Generic[T]):
    def __init__(self, client: SupabaseDataClient, table: str, dto: type[T]) -> None:
        self.client, self.table, self.dto = client, table, dto

    def decode(self, row: dict) -> T:
        # Pydantic DTOs forbid extra fields. Explicitly select their public
        # fields rather than relaxing the DTO validation configuration.
        return self.dto.model_validate({k: v for k, v in row.items() if k in self.dto.model_fields})

    def list(self, patient_id: UUID, **filters: str) -> list[T]:
        self.client.check_patient(patient_id)
        return [
            self.decode(row)
            for row in self.client.rows(
                self.table,
                patient_id=f"eq.{patient_id}",
                **filters,
            )
        ]

    def get(self, patient_id: UUID, record_id: UUID) -> T | None:
        rows = self.list(patient_id, id=f"eq.{record_id}", limit="1")
        return rows[0] if rows else None

    def list_complete(self, patient_id: UUID, **filters: str) -> list[T]:
        self.client.check_patient(patient_id)
        return [self.decode(row) for row in self.client.all_rows(self.table, patient_id=f"eq.{patient_id}", **filters)]

    def insert(self, dto: T, extra: dict | None = None) -> None:
        body = dto.model_dump(mode="json")
        self.client.check_patient(UUID(body["patient_id"]))
        self.client.request("POST", f"/rest/v1/{self.table}", body={**body, **(extra or {})})

    def patch(self, dto: T, body: dict) -> None:
        data = dto.model_dump(mode="json")
        self.client.check_patient(UUID(data["patient_id"]))
        rows = self.client.request(
            "PATCH",
            f"/rest/v1/{self.table}",
            params={"patient_id": f"eq.{data['patient_id']}", "id": f"eq.{data['id']}"},
            body=body,
        )
        if not rows:
            raise NotFoundError("Owned record not found")


class Sources(Repository[SourceDocumentDTO]):
    def get_many(self, patient_id: UUID, source_ids: list[UUID]) -> list[SourceDocumentDTO]:
        self.client.check_patient(patient_id)
        ids = list(dict.fromkeys(source_ids))
        result = []
        for offset in range(0, len(ids), 100):
            selected = ",".join(str(value) for value in ids[offset:offset + 100])
            result.extend(self.list_complete(patient_id, id=f"in.({selected})"))
        return result

    def add(self, document: SourceDocumentDTO) -> None:
        material = f"pharmascan-synthetic-source::{document.patient_id}::{document.id}"
        self.insert(document, {"is_synthetic": True, "checksum": hashlib.sha256(material.encode()).hexdigest()})

    def update(self, document: SourceDocumentDTO) -> None:
        body = document.model_dump(mode="json", include={"review_status", "reviewed_at"})
        self.patch(document, body)


class Fields(Repository[SourceFieldDTO]):
    def list_for_source(self, patient_id: UUID, source_id: UUID) -> list[SourceFieldDTO]:
        return self.list(patient_id, source_id=f"eq.{source_id}", order="field_name")

    def add(self, field: SourceFieldDTO) -> None:
        source = self.client.rows("source_documents", id=f"eq.{field.source_id}")
        self.insert(
            field,
            {
                "evidence_locator": f"synthetic:field:{field.id}",
                "extraction_method": "manual"
                if source and source[0]["source_kind"] == "user_manual"
                else "synthetic_fixture",
            },
        )

    def update(self, field: SourceFieldDTO) -> None:
        self.patch(field, field.model_dump(mode="json", include={"review_status", "reviewed_at"}))


class Medications(Repository[PatientMedicationDTO]):
    def list_for_patient(self, patient_id: UUID) -> list[PatientMedicationDTO]:
        return self.list(patient_id, order="created_at,id")

    def add(self, medication: PatientMedicationDTO) -> None:
        self.insert(medication)

    def update(self, medication: PatientMedicationDTO) -> None:
        self.patch(medication, medication.model_dump(mode="json", exclude={"id", "patient_id", "demo_only"}))


class Regimens(Repository[RegimenVersionDTO]):
    def list_for_medications(
        self, patient_id: UUID, medication_ids: list[UUID], *, active_only: bool = False,
    ) -> list[RegimenVersionDTO]:
        self.client.check_patient(patient_id)
        ids = list(dict.fromkeys(medication_ids))
        result = []
        for offset in range(0, len(ids), 100):
            selected = ",".join(str(value) for value in ids[offset:offset + 100])
            result.extend(self.list_complete(
                patient_id, patient_medication_id=f"in.({selected})", order="version_no,id",
                **({"state": "eq.active"} if active_only else {})
            ))
        return result

    def list_for_medication(self, patient_id: UUID, medication_id: UUID) -> list[RegimenVersionDTO]:
        return self.list(patient_id, patient_medication_id=f"eq.{medication_id}", order="version_no")

    def find_active_for_medication(self, patient_id: UUID, medication_id: UUID) -> RegimenVersionDTO | None:
        rows = self.list(patient_id, patient_medication_id=f"eq.{medication_id}", state="eq.active")
        return rows[0] if rows else None

    def next_version_no(self, patient_id: UUID, medication_id: UUID) -> int:
        rows = self.list_for_medication(patient_id, medication_id)
        return max((row.version_no for row in rows), default=0) + 1

    def provenance(self, regimen: RegimenVersionDTO) -> dict:
        sources = self.client.rows("source_documents", id=f"eq.{regimen.source_id}")
        if not sources or sources[0]["review_status"] not in ("user_reviewed", "professional_verified"):
            raise ValidationError("Reviewed source required")
        fields = self.client.rows(
            "source_fields",
            source_id=f"eq.{regimen.source_id}",
            review_status="in.(user_reviewed,professional_verified)",
        )
        by_name = {row["field_name"]: row["id"] for row in fields}
        bindings = {
            "medication_name_field_id": "medication_name",
            "quantity_field_id": "dose_amount",
            "unit_field_id": "dose_unit",
            "prn_field_id" if regimen.is_prn else "frequency_field_id": "is_prn"
            if regimen.is_prn
            else "frequency_rule",
        }
        if any(name not in by_name for name in bindings.values()):
            raise ValidationError("Missing reviewed regimen evidence")
        return {
            **{column: by_name[name] for column, name in bindings.items()},
            "source_reviewed_at": sources[0]["reviewed_at"],
        }

    def add(self, regimen: RegimenVersionDTO) -> None:
        self.insert(regimen, self.provenance(regimen) if str(regimen.state) == "active" else {})

    def update(self, regimen: RegimenVersionDTO) -> None:
        current = self.get(regimen.patient_id, regimen.id)
        if current is None:
            raise NotFoundError("Regimen not found")
        if str(current.state) == "active":
            body = regimen.model_dump(mode="json", include={"state", "effective_to"})
        else:
            body = regimen.model_dump(mode="json", exclude={"id", "patient_id", "created_at", "demo_only"})
            if str(regimen.state) == "active":
                body.update(self.provenance(regimen))
        self.patch(regimen, body)

    def activate_version(
        self, *, patient_id: UUID, regimen_id: UUID, challenge_id: UUID, timezone: str
    ) -> ActivationResultDTO:
        """Atomically retire a predecessor, activate a version and replace its schedule."""
        self.client.check_patient(patient_id)
        result = self.client.request(
            "POST",
            "/rest/v1/rpc/activate_medication_regimen_version",
            body={
                "p_regimen_id": str(regimen_id),
                "p_challenge_id": str(challenge_id),
                "p_timezone": timezone,
            },
        )
        if not isinstance(result, dict) or not isinstance(result.get("regimen"), dict):
            raise ProviderUnavailableError("Supabase returned an invalid regimen activation result")
        regimen = self.decode(result["regimen"])
        superseded = result.get("superseded_regimen_ids")
        if not isinstance(superseded, list):
            raise ProviderUnavailableError("Supabase returned an invalid regimen transition result")
        try:
            return ActivationResultDTO(regimen=regimen, superseded_regimen_ids=superseded)
        except ValueError:
            raise ProviderUnavailableError("Supabase returned an invalid regimen transition result") from None


class Rules(Repository[DoseRuleDTO]):
    def decode(self, row: dict) -> DoseRuleDTO:
        return super().decode(
            {
                **row,
                "local_times": [row["local_time"][:5]] if row["local_time"] else [],
                "days_of_week": row["days_of_week"] or [],
            }
        )

    def list_for_regimen(self, patient_id: UUID, regimen_id: UUID) -> list[DoseRuleDTO]:
        return self.list(patient_id, regimen_id=f"eq.{regimen_id}", order="local_time,id")

    def add(self, rule: DoseRuleDTO) -> None:
        self.client.check_patient(rule.patient_id)
        if str(rule.rule_kind) == "prn" and (rule.local_times or rule.days_of_week):
            raise ValidationError("PRN rules must not carry a schedule")
        if str(rule.rule_kind) == "scheduled" and len(rule.local_times) != 1:
            raise ValidationError("A scheduled rule requires exactly one local time")
        body = rule.model_dump(mode="json", exclude={"local_times"})
        body.update(
            local_time=rule.local_times[0] if rule.local_times else None,
            days_of_week=rule.days_of_week if str(rule.rule_kind) == "scheduled" else None,
            demo_only=True,
        )
        self.client.request("POST", "/rest/v1/dose_rules", body=body)

    def update(self, rule: DoseRuleDTO) -> None:
        self.client.check_patient(rule.patient_id)
        if rule.enabled:
            raise ValidationError("An existing dose rule may only be disabled")
        self.patch(rule, {"enabled": False})


class Occurrences(Repository[DoseOccurrenceDTO]):
    def find_by_generation_key(self, patient_id: UUID, key: str) -> DoseOccurrenceDTO | None:
        rows = self.list(patient_id, generation_key=f"eq.{key}")
        return rows[0] if rows else None

    def list_for_regimen(
        self, patient_id: UUID, regimen_id: UUID, window_start: datetime, window_end: datetime
    ) -> list[DoseOccurrenceDTO]:
        return self.list_complete(
            patient_id,
            regimen_id=f"eq.{regimen_id}",
            and_=f"(due_at.gte.{window_start.isoformat()},due_at.lt.{window_end.isoformat()})",
        )

    def add(self, occurrence: DoseOccurrenceDTO) -> None:
        self.client.check_patient(occurrence.patient_id)
        self.client.request(
            "POST",
            "/rest/v1/dose_occurrences",
            params={"on_conflict": "patient_id,generation_key"},
            body={**occurrence.model_dump(mode="json"), "demo_only": True},
            prefer="resolution=ignore-duplicates,return=minimal",
        )

    def update(self, occurrence: DoseOccurrenceDTO) -> None:
        current = self.get(occurrence.patient_id, occurrence.id)
        if current is not None and current.status == occurrence.status:
            return  # atomic RPC already closed it; do not mutate frozen history
        self.patch(occurrence, {"status": str(occurrence.status)})


class Events(Repository[DoseEventDTO]):
    def list_for_occurrences(self, patient_id: UUID, occurrence_ids: list[UUID]) -> list[DoseEventDTO]:
        self.client.check_patient(patient_id)
        ids = list(dict.fromkeys(occurrence_ids))
        result = []
        # Bound URL size; complete pagination must never turn a missing page
        # into an apparently unreported dose. Use this adapter's effective view.
        for offset in range(0, len(ids), 100):
            selected = ",".join(str(value) for value in ids[offset:offset + 100])
            result.extend(self.list_complete(patient_id, occurrence_id=f"in.({selected})"))
        return result

    def find_by_idempotency_key(self, patient_id: UUID, key: str) -> DoseEventDTO | None:
        self.client.check_patient(patient_id)
        rows = [
            self.decode(row)
            for row in self.client.rows("dose_events", patient_id=f"eq.{patient_id}", idempotency_key=f"eq.{key}")
        ]
        return rows[0] if rows else None

    def find_by_occurrence(self, patient_id: UUID, occurrence_id: UUID) -> DoseEventDTO | None:
        rows = self.list(patient_id, occurrence_id=f"eq.{occurrence_id}")
        return rows[0] if rows else None

    def list_for_patient(self, patient_id: UUID, window_start: datetime, window_end: datetime) -> list[DoseEventDTO]:
        return self.list_complete(
            patient_id,
            and_=f"(event_time.gte.{window_start.isoformat()},event_time.lt.{window_end.isoformat()})",
            order="event_time,id",
        )

    def add(self, event: DoseEventDTO) -> DoseEventDTO:
        self.client.check_patient(event.patient_id)
        challenges = self.client.rows(
            "confirmation_challenges",
            idempotency_key=f"eq.{event.idempotency_key}",
            action="eq.record_self_report",
            confirmed_at="not.is.null",
        )
        if not challenges:
            raise ConfirmationRequiredError("Confirmed self-report challenge required")
        # BEFORE INSERT guard checks all bindings, locks and consumes the
        # challenge in the same transaction as the event write.
        body = event.model_dump(mode="json", exclude={"reported_late", "actual_administration_at"})
        body["confirmation_challenge_id"] = challenges[0]["id"]
        row = self.client.request("POST", "/rest/v1/rpc/record_confirmed_self_report", body={"p_event": body})
        return self.decode(row)


class Sessions(Repository[AgentSessionDTO]):
    def add(self, session: AgentSessionDTO) -> None:
        self.insert(session, {"prompt_version": "deterministic_router_v1", "demo_only": True})

    def update(self, session: AgentSessionDTO) -> None:
        self.patch(session, session.model_dump(mode="json", exclude={"id", "patient_id"}))


class Challenges(Repository[ConfirmationChallengeDTO]):
    def find_by_token_hash(self, patient_id: UUID, token_hash: str) -> ConfirmationChallengeDTO | None:
        rows = self.list(patient_id, token_hash=f"eq.{token_hash}")
        return rows[0] if rows else None

    def find_by_idempotency_key(self, patient_id: UUID, idempotency_key: str) -> ConfirmationChallengeDTO | None:
        rows = self.list(patient_id, idempotency_key=f"eq.{idempotency_key}")
        return rows[0] if rows else None

    def add(self, challenge: ConfirmationChallengeDTO) -> None:
        binding = {
            "patient_id": str(challenge.patient_id),
            "action": challenge.action,
            "regimen_id": str(challenge.regimen_id),
            "occurrence_id": str(challenge.occurrence_id) if challenge.occurrence_id else None,
            "intake_status": str(challenge.intended_intake_status) if challenge.intended_intake_status else None,
            "idempotency_key": challenge.idempotency_key,
        }
        request_hash = hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.insert(challenge, {"request_hash": request_hash, "demo_only": True})

    def update(self, challenge: ConfirmationChallengeDTO) -> None:
        current = self.get(challenge.patient_id, challenge.id)
        if current is None:
            raise NotFoundError("Challenge not found")
        # Consumption belongs exclusively to the guarded event/regimen write.
        if challenge.consumed_at is not None:
            if current.consumed_at is None:
                raise ConfirmationRequiredError("Challenge consumption requires a guarded write")
            return
        if challenge.confirmed_at is not None and current.confirmed_at is None:
            self.patch(challenge, {"confirmed_at": challenge.confirmed_at.isoformat()})


class Traces(Repository[ToolTraceDTO]):
    def add(self, trace: ToolTraceDTO) -> None:
        self.insert(trace, {"demo_only": True})

    def list_for_session(self, patient_id: UUID, session_id: UUID) -> list[ToolTraceDTO]:
        return self.list(patient_id, session_id=f"eq.{session_id}", order="called_at,id")


@dataclass(frozen=True)
class SupabaseRepositories:
    sources: Sources
    source_fields: Fields
    medications: Medications
    regimens: Regimens
    dose_rules: Rules
    occurrences: Occurrences
    events: Events
    sessions: Sessions
    challenges: Challenges
    traces: Traces


def build_supabase_repositories(
    client: SupabaseDataClient, *, include_late_reports: bool = False
) -> SupabaseRepositories:
    return SupabaseRepositories(
        Sources(client, "source_documents", SourceDocumentDTO),
        Fields(client, "source_fields", SourceFieldDTO),
        Medications(client, "patient_medications", PatientMedicationDTO),
        Regimens(client, "regimen_versions", RegimenVersionDTO),
        Rules(client, "dose_rules", DoseRuleDTO),
        Occurrences(client, "dose_occurrences", DoseOccurrenceDTO),
        Events(client, "effective_dose_events" if include_late_reports else "dose_events", DoseEventDTO),
        Sessions(client, "agent_sessions", AgentSessionDTO),
        Challenges(client, "confirmation_challenges", ConfirmationChallengeDTO),
        Traces(client, "agent_tool_calls", ToolTraceDTO),
    )
