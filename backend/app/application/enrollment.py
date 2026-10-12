"""Medication enrollment & regimen activation use-case.

Flow: manual/synthetic draft (provenance fields) -> patient reviews source
fields -> explicit confirmation -> ACTIVE regimen version. Missing dose
instructions stay pending; nothing is ever inferred (BUILD_PLAN Gate 1).
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any
from uuid import UUID

from ..contracts.dto import (
    ActivationResultDTO,
    ConfirmationChallengeDTO,
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
from ..domain import policy
from ..domain.errors import NotFoundError, ValidationError
from .timezone import LOCAL_TZ_PROVIDER, LocalTzProvider

CONFIRMATION_TTL = timedelta(minutes=10)


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

    def enroll_draft(
        self,
        *,
        patient_id: UUID,
        draft: RegimenDraftInput,
        source_kind: SourceKind = SourceKind.USER_MANUAL,
    ) -> EnrollmentResultDTO:
        """Create medication + draft regimen + provenance fields.

        Fields the patient has not supplied are simply absent — the draft
        stays pending and will NOT auto-activate (no inferred dosing).
        """
        if not draft.medication_name.strip():
            raise ValidationError("medication_name is required")

        now = self._clock.now()
        source_id = self._ids.new_id()
        source = SourceDocumentDTO(
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

        medication = PatientMedicationDTO(
            id=self._ids.new_id(),
            patient_id=patient_id,
            display_name=draft.medication_name,
            product_id=None,
            source_id=source_id,
            identity_status=IdentityStatus.UNVERIFIED,
        )
        self._medications.add(medication)

        missing = policy.missing_required_instructions(provided, is_prn=draft.is_prn)
        state = RegimenState.PENDING_CLARIFICATION if missing else RegimenState.DRAFT

        regimen = RegimenVersionDTO(
            id=self._ids.new_id(),
            patient_id=patient_id,
            patient_medication_id=medication.id,
            source_id=source_id,
            version_no=self._regimens.next_version_no(patient_id, medication.id),
            state=state,
            dose_amount=draft.dose_amount,
            dose_unit=draft.dose_unit,
            frequency_rule=(
                draft.frequency_rule.model_dump() if draft.frequency_rule else None
            ),
            is_prn=draft.is_prn,
            route=draft.route,
            food_instruction=draft.food_instruction,
            effective_from=None,
            effective_to=None,
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

    def review_source_fields(
        self, *, patient_id: UUID, source_id: UUID, field_ids: list[UUID] | None = None
    ) -> int:
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
                field_dto.model_copy(
                    update={"review_status": SourceReviewStatus.USER_REVIEWED, "reviewed_at": now}
                )
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
                        medication.model_copy(
                            update={"identity_status": IdentityStatus.USER_REVIEWED_DOCUMENT}
                        )
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
            raise ValidationError(
                f"Regimen is {regimen.state.value}; only a draft can be activated"
            )
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
            idempotency_key=f"activate:{regimen_id}",
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
            self._regimens.update(
                active.model_copy(
                    update={"state": RegimenState.SUPERSEDED, "effective_to": now}
                )
            )
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
        self._challenges.update(
            challenge.model_copy(update={"consumed_at": now})
        )
        self._medications.update(
            medication.model_copy(update={"identity_status": IdentityStatus.USER_REVIEWED_DOCUMENT})
        )
        return ActivationResultDTO(
            regimen=self._require_regimen(patient_id, regimen_id),
            superseded_regimen_ids=superseded,
        )

    def _require_regimen(self, patient_id: UUID, regimen_id: UUID) -> RegimenVersionDTO:
        regimen = self._regimens.get(patient_id, regimen_id)
        if regimen is None:
            raise NotFoundError(f"Regimen {regimen_id} not found")
        return regimen
