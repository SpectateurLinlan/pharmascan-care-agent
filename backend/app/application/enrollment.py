"""Medication enrollment & regimen activation use-case.

Flow: manual/synthetic draft (provenance fields) -> patient reviews source
fields -> explicit confirmation -> ACTIVE regimen version. Missing dose
instructions stay pending; nothing is ever inferred (BUILD_PLAN Gate 1).
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any
from uuid import UUID

from ..contracts.dto import (
    ActivationResultDTO,
    ConfirmationChallengeDTO,
    DoseRuleDTO,
    EnrollmentResultDTO,
    MissingInstruction,
    PatientMedicationDTO,
    RegimenDraftInput,
    RegimenVersionDTO,
    SourceDocumentDTO,
    SourceFieldDTO,
)
from ..contracts.enums import (
    FieldName,
    IdentityStatus,
    RegimenState,
    RuleKind,
    SourceKind,
    SourceReviewStatus,
)
from ..contracts.ports import (
    Clock,
    ConfirmationChallengeRepository,
    DoseRuleRepository,
    IdGenerator,
    PatientMedicationRepository,
    RegimenVersionRepository,
    SourceDocumentRepository,
    SourceFieldRepository,
)
from ..contracts.source_extraction import MedicationSourceExtractionDTO
from ..domain import policy
from ..domain.errors import NotFoundError, ValidationError
from .timezone import LOCAL_TZ_PROVIDER, LocalTzProvider

CONFIRMATION_TTL = timedelta(minutes=10)


def _normalise_local_time(value: str) -> str:
    """Return a canonical ``HH:MM`` string, rejecting malformed input.

    Normalising means "8:00" and "08:00" collapse to one slot instead of
    creating two rules for the same instant.
    """
    text = str(value).strip()
    parts = text.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValidationError(f"invalid local time {value!r}; expected HH:MM")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValidationError(f"local time {value!r} is out of range")
    return f"{hour:02d}:{minute:02d}"


class MedicationEnrollmentService:
    """Draft -> reviewed -> active regimen with version history."""

    def __init__(
        self,
        *,
        medications: PatientMedicationRepository,
        regimens: RegimenVersionRepository,
        sources: SourceDocumentRepository,
        source_fields: SourceFieldRepository,
        dose_rules: DoseRuleRepository,
        challenges: ConfirmationChallengeRepository,
        clock: Clock,
        ids: IdGenerator,
        tz_provider: LocalTzProvider | None = None,
    ) -> None:
        self._medications = medications
        self._regimens = regimens
        self._sources = sources
        self._source_fields = source_fields
        self._dose_rules = dose_rules
        self._challenges = challenges
        self._clock = clock
        self._ids = ids
        self._tz = tz_provider or LOCAL_TZ_PROVIDER

    # -- enrollment ----------------------------------------------------------

    def list_medications(self, patient_id: UUID) -> list[PatientMedicationDTO]:
        return self._medications.list_for_patient(patient_id)

    def get_source(self, patient_id: UUID, source_id: UUID) -> SourceDocumentDTO | None:
        return self._sources.get(patient_id, source_id)

    def get_medication(self, patient_id: UUID, medication_id: UUID) -> PatientMedicationDTO | None:
        return self._medications.get(patient_id, medication_id)

    def get_regimen(self, patient_id: UUID, regimen_id: UUID) -> RegimenVersionDTO | None:
        return self._regimens.get(patient_id, regimen_id)

    def find_active_regimen(self, patient_id: UUID, medication_id: UUID) -> RegimenVersionDTO | None:
        return self._regimens.find_active_for_medication(patient_id, medication_id)

    def list_regimens(self, patient_id: UUID, medication_id: UUID) -> list[RegimenVersionDTO]:
        return self._regimens.list_for_medication(patient_id, medication_id)

    def resume_draft(self, patient_id: UUID, regimen_id: UUID) -> EnrollmentResultDTO:
        regimen = self._regimens.get(patient_id, regimen_id)
        if regimen is None:
            raise NotFoundError("Draft not found")
        if regimen.state not in {RegimenState.DRAFT, RegimenState.PENDING_CLARIFICATION}:
            raise ValidationError("Only an unfinished regimen can be resumed")
        medication = self._medications.get(patient_id, regimen.patient_medication_id)
        if medication is None or regimen.source_id is None:
            raise NotFoundError("Draft source not found")
        fields = self._source_fields.list_for_source(patient_id, regimen.source_id)
        provided = {field.field_name.value: field.field_value for field in fields}
        missing = policy.missing_required_instructions(provided, is_prn=regimen.is_prn)
        return EnrollmentResultDTO(
            medication=medication,
            regimen=regimen,
            source_fields=fields,
            missing_instructions=[MissingInstruction(field=field) for field in missing],
        )

    def enroll_draft(
        self,
        *,
        patient_id: UUID,
        draft: RegimenDraftInput,
        source_kind: SourceKind = SourceKind.USER_MANUAL,
        extraction_evidence: MedicationSourceExtractionDTO | None = None,
        existing_medication_id: UUID | None = None,
        evidence_task_id: UUID | None = None,
    ) -> EnrollmentResultDTO:
        """Create medication + draft regimen + provenance fields.

        Fields the patient has not supplied are simply absent — the draft
        stays pending and will NOT auto-activate (no inferred dosing).
        """
        if not draft.medication_name.strip():
            raise ValidationError("medication_name is required")
        if evidence_task_id and existing_medication_id:
            prior = next(
                (
                    row
                    for row in self._regimens.list_for_medication(patient_id, existing_medication_id)
                    if row.evidence_task_id == evidence_task_id
                ),
                None,
            )
            if prior:
                expected = (
                    draft.dose_amount,
                    draft.dose_unit,
                    draft.frequency_rule.model_dump() if draft.frequency_rule else None,
                    draft.is_prn,
                    draft.route,
                    draft.food_instruction,
                    draft.course_start_date,
                    draft.course_end_date,
                )
                actual = (
                    prior.dose_amount,
                    prior.dose_unit,
                    prior.frequency_rule,
                    prior.is_prn,
                    prior.route,
                    prior.food_instruction,
                    prior.course_start_date,
                    prior.course_end_date,
                )
                if actual != expected:
                    raise ValidationError("A draft already exists for this task. Resume its reviewed details.")
                return self.resume_draft(patient_id, prior.id)

        if (
            extraction_evidence is not None
            and len(json.dumps(extraction_evidence.model_dump(mode="json")).encode()) > 65536
        ):
            raise ValidationError("Extraction evidence is too large")
        now = self._clock.now()
        source_id = self._ids.new_id()
        source = SourceDocumentDTO(
            extraction_evidence=extraction_evidence,
            id=source_id,
            patient_id=patient_id,
            source_kind=source_kind,
            review_status=SourceReviewStatus.EXTRACTED,
            reviewed_at=None,
        )
        self._sources.add(source)

        provided: dict[str, Any] = {FieldName.MEDICATION_NAME.value: draft.medication_name}
        if draft.dose_amount is not None:
            if draft.dose_amount <= 0:
                raise ValidationError("dose_amount must be > 0")
            provided[FieldName.DOSE_AMOUNT.value] = draft.dose_amount
        if draft.dose_unit is not None:
            provided[FieldName.DOSE_UNIT.value] = draft.dose_unit
        if draft.frequency_rule is not None:
            policy.validate_frequency_rule(draft.frequency_rule, is_prn=draft.is_prn)
            provided[FieldName.FREQUENCY_RULE.value] = draft.frequency_rule.model_dump()
        if draft.is_prn:
            provided[FieldName.IS_PRN.value] = True
        if draft.route is not None:
            provided[FieldName.ROUTE.value] = draft.route
        if draft.food_instruction is not None:
            provided[policy.PRN_GUIDANCE_KEY] = draft.food_instruction
        if draft.course_start_date is not None:
            provided[FieldName.COURSE_START_DATE.value] = draft.course_start_date.isoformat()
        if draft.course_end_date is not None:
            provided[FieldName.COURSE_END_DATE.value] = draft.course_end_date.isoformat()

        field_dtos: list[SourceFieldDTO] = []
        # Source was just created as EXTRACTED; appending is allowed.
        for name, value in provided.items():
            field_dto = SourceFieldDTO(
                id=self._ids.new_id(),
                patient_id=patient_id,
                source_id=source_id,
                field_name=FieldName(name),
                field_value=value,
                review_status=SourceReviewStatus.EXTRACTED,
                reviewed_at=None,
            )
            self._source_fields.add(field_dto)
            field_dtos.append(field_dto)

        medication = self._medications.get(patient_id, existing_medication_id) if existing_medication_id else None
        if existing_medication_id and medication is None:
            raise NotFoundError("Owned medication not found")
        if medication and medication.display_name.casefold() != draft.medication_name.casefold():
            raise ValidationError("Product name conflict requires review")
        medication = medication or PatientMedicationDTO(
            id=self._ids.new_id(),
            patient_id=patient_id,
            display_name=draft.medication_name,
            product_id=None,
            source_id=source_id,
            identity_status=IdentityStatus.UNVERIFIED,
        )
        if not existing_medication_id:
            self._medications.add(medication)

        missing = policy.missing_required_instructions(provided, is_prn=draft.is_prn)
        state = RegimenState.PENDING_CLARIFICATION if missing else RegimenState.DRAFT

        regimen = RegimenVersionDTO(
            evidence_task_id=evidence_task_id,
            id=self._ids.new_id(),
            patient_id=patient_id,
            patient_medication_id=medication.id,
            source_id=source_id,
            version_no=self._regimens.next_version_no(patient_id, medication.id),
            state=state,
            dose_amount=draft.dose_amount,
            dose_unit=draft.dose_unit,
            frequency_rule=(draft.frequency_rule.model_dump() if draft.frequency_rule else None),
            is_prn=draft.is_prn,
            route=draft.route,
            food_instruction=draft.food_instruction,
            effective_from=None,
            effective_to=None,
            course_start_date=draft.course_start_date,
            course_end_date=draft.course_end_date,
            supersedes_id=None,
            confirmation_challenge_id=None,
            created_at=now,
        )
        self._regimens.add(regimen)

        return EnrollmentResultDTO(
            medication=medication,
            regimen=regimen,
            missing_instructions=[MissingInstruction(field=m) for m in missing],
            source_fields=field_dtos,
        )

    # -- review --------------------------------------------------------------

    def review_source_fields(self, *, patient_id: UUID, source_id: UUID, field_ids: list[UUID] | None = None) -> int:
        """Patient confirms extracted fields; marks them user_reviewed.

        Reviewing the medication-identity evidence is what promotes the
        medication from `unverified` to `user_reviewed_document` — the
        medication never claims a verified identity without it.
        """
        source = self._sources.get(patient_id, source_id)
        if source is None:
            raise NotFoundError(f"Source document {source_id} not found")
        if source.review_status in (SourceReviewStatus.USER_REVIEWED, SourceReviewStatus.PROFESSIONAL_VERIFIED):
            raise ValidationError("Reviewed source is immutable")

        now = self._clock.now()
        reviewed = 0
        reviewed_names: set[FieldName] = set()
        for field_dto in self._source_fields.list_for_source(patient_id, source_id):
            if field_ids is not None and field_dto.id not in field_ids:
                continue
            self._source_fields.update(
                field_dto.model_copy(update={"review_status": SourceReviewStatus.USER_REVIEWED, "reviewed_at": now})
            )
            reviewed_names.add(field_dto.field_name)
            reviewed += 1
        self._sources.update(
            source.model_copy(update={"review_status": SourceReviewStatus.USER_REVIEWED, "reviewed_at": now})
        )

        # Promote medication identity only once its name evidence is reviewed.
        if FieldName.MEDICATION_NAME in reviewed_names:
            for medication in self._medications.list_for_patient(patient_id):
                if medication.source_id == source_id and medication.identity_status == IdentityStatus.UNVERIFIED:
                    self._medications.update(
                        medication.model_copy(update={"identity_status": IdentityStatus.USER_REVIEWED_DOCUMENT})
                    )
        return reviewed

    # -- confirmation & activation -------------------------------------------

    def request_activation_challenge(
        self,
        *,
        patient_id: UUID,
        regimen_id: UUID,
        session_id: UUID,
        session_state_version: int,
    ) -> tuple[ConfirmationChallengeDTO, str]:
        """Issue an unconfirmed challenge; returns (challenge, token-once)."""
        regimen = self._require_regimen(patient_id, regimen_id)
        if regimen.state not in (RegimenState.DRAFT, RegimenState.PENDING_CLARIFICATION):
            raise ValidationError(f"Regimen is {regimen.state.value}; only a draft can be activated")
        now = self._clock.now()
        token = self._ids.new_id().hex + self._ids.new_id().hex  # demo token
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        challenge = ConfirmationChallengeDTO(
            id=self._ids.new_id(),
            patient_id=patient_id,
            session_id=session_id,
            session_state_version=session_state_version,
            action="activate_regimen",
            regimen_id=regimen_id,
            occurrence_id=None,
            intended_intake_status=None,
            # The database enforces UNIQUE (patient_id, idempotency_key), so the
            # key must fingerprint this specific confirmation request — the
            # regimen, the session and the version of the summary the patient is
            # being asked to approve. A fixed per-regimen key would make a second
            # request (a refresh, or a retry after an expired challenge) collide
            # with the first and be rejected by the real insert.
            idempotency_key=(f"activate:{regimen_id}:{session_id}:{session_state_version}"),
            token_hash=token_hash,
            issued_at=now,
            expires_at=now + CONFIRMATION_TTL,
        )
        self._challenges.add(challenge)
        return challenge, token

    def confirm_challenge(self, *, patient_id: UUID, challenge_id: UUID) -> None:
        """Explicit user confirmation of a previously displayed summary."""
        challenge = self._challenges.get(patient_id, challenge_id)
        if challenge is None:
            raise NotFoundError(f"Challenge {challenge_id} not found")
        now = self._clock.now()
        if now >= challenge.expires_at:
            from ..domain.errors import ConfirmationExpiredError

            raise ConfirmationExpiredError("Challenge expired before confirmation")
        self._challenges.update(challenge.model_copy(update={"confirmed_at": now}))

    def activate_regimen(
        self,
        *,
        patient_id: UUID,
        regimen_id: UUID,
        challenge_id: UUID,
        session_state: str,
        session_state_version: int,
    ) -> ActivationResultDTO:
        """Consume the confirmed challenge and activate the draft."""
        regimen = self._require_regimen(patient_id, regimen_id)
        medication = self._medications.get(patient_id, regimen.patient_medication_id)
        if medication is None:
            raise NotFoundError("Medication not found")
        source = self._sources.get(patient_id, regimen.source_id) if regimen.source_id else None
        fields = self._source_fields.list_for_source(patient_id, regimen.source_id) if regimen.source_id else []

        provided = {f.field_name.value: f.field_value for f in fields}
        missing = policy.missing_required_instructions(provided, is_prn=regimen.is_prn)

        policy.check_activation_preconditions(
            medication=medication,
            source=source,
            source_fields=fields,
            missing_instructions=missing,
            now=self._clock.now(),
        )

        challenge = self._challenges.get(patient_id, challenge_id)
        policy.check_confirmation(
            challenge=challenge,
            expected_action="activate_regimen",
            expected_regimen_id=regimen_id,
            expected_occurrence_id=None,
            expected_intake_status=None,
            expected_idempotency_key=None,
            session_state=session_state,
            session_state_version=session_state_version,
            now=self._clock.now(),
        )

        now = self._clock.now()
        superseded: list[UUID] = []
        active = self._regimens.find_active_for_medication(patient_id, medication.id)
        if active is not None and active.id != regimen_id:
            decision = policy.check_regimen_state_transition(active.state, RegimenState.SUPERSEDED)
            if not decision.allowed:
                raise ValidationError(decision.reason)
            self._regimens.update(active.model_copy(update={"state": RegimenState.SUPERSEDED, "effective_to": now}))
            superseded.append(active.id)

        self._regimens.update(
            regimen.model_copy(
                update={
                    "state": RegimenState.ACTIVE,
                    "effective_from": now,
                    "confirmation_challenge_id": challenge_id,
                }
            )
        )
        assert challenge is not None
        self._challenges.update(challenge.model_copy(update={"consumed_at": now}))
        self._medications.update(
            medication.model_copy(update={"identity_status": IdentityStatus.USER_REVIEWED_DOCUMENT})
        )
        # Persist the schedule rule now that the regimen is active. Without
        # this an activated regimen would have no rule and could never produce
        # a due dose (the patient would have a medication with no schedule).
        self._persist_dose_rules(patient_id=patient_id, regimen=regimen)
        return ActivationResultDTO(
            regimen=self._require_regimen(patient_id, regimen_id),
            superseded_regimen_ids=superseded,
        )

    def _persist_dose_rules(self, *, patient_id: UUID, regimen: RegimenVersionDTO) -> None:
        """Create the schedule rule(s) implied by an activated regimen.

        One regimen may carry **several** explicit dose times (e.g. 08:00 and
        20:00). Multiple times are expressed as multiple ``dose_rules`` rows —
        the existing schedule model — rather than by packing several times into
        one string, so the SQL ``dose_rules.local_time time`` column stays a
        single time per row and every rule remains independently addressable
        (its own ``rule_id`` on each generated occurrence).

        Rows are emitted to satisfy ``dose_rules_schedule_ck``:
        - ``scheduled`` requires a non-null ``local_time`` **and** a non-empty
          ``days_of_week``; a "daily" instruction is therefore stored as all
          seven ISO weekdays, not as an empty array;
        - ``prn`` requires both to be null / empty.

        Idempotent: re-activating the same regimen does not duplicate rules.
        """
        if self._dose_rules.list_for_regimen(patient_id, regimen.id):
            return

        timezone = str(self._tz.local_tz(patient_id))
        if regimen.is_prn:
            self._dose_rules.add(
                DoseRuleDTO(
                    id=self._ids.new_id(),
                    patient_id=patient_id,
                    regimen_id=regimen.id,
                    rule_kind=RuleKind.PRN,
                    local_times=[],
                    days_of_week=[],
                    timezone=timezone,
                    enabled=True,
                )
            )
            return

        frequency = regimen.frequency_rule or {}
        kind = str(frequency.get("kind") or "daily")
        local_times = [str(t) for t in (frequency.get("local_times") or [])]
        days_of_week = [int(d) for d in (frequency.get("days_of_week") or [])]

        if kind == "weekly":
            # A weekly instruction has explicit days; one row per time.
            days = days_of_week or list(range(1, 8))
        else:
            # 'daily' and 'interval' carry no explicit days: every day applies.
            days = list(range(1, 8))

        # Two identical times (e.g. "08:00" entered twice) describe ONE dose
        # slot. Emitting two rules would show the patient the same dose twice
        # and would violate dose_rules_no_duplicate_slot_uk on a real database,
        # so duplicates are collapsed here while preserving input order.
        unique_times: list[str] = []
        for local_time in local_times or ["08:00"]:
            normalised = _normalise_local_time(local_time)
            if normalised not in unique_times:
                unique_times.append(normalised)

        for local_time in unique_times:
            self._dose_rules.add(
                DoseRuleDTO(
                    id=self._ids.new_id(),
                    patient_id=patient_id,
                    regimen_id=regimen.id,
                    rule_kind=RuleKind.SCHEDULED,
                    local_times=[local_time],
                    days_of_week=list(days),
                    timezone=timezone,
                    enabled=True,
                )
            )

    def _require_regimen(self, patient_id: UUID, regimen_id: UUID) -> RegimenVersionDTO:
        regimen = self._regimens.get(patient_id, regimen_id)
        if regimen is None:
            raise NotFoundError(f"Regimen {regimen_id} not found")
        return regimen
