"""Dose schedule generation, due-dose lookup and self-report recording.

Critical invariants (AGENTS.md rules 10, 22-23):
- a self report NEVER proves ingestion (`ingestion_proven` stays false);
- visual_status stays `not_checked` in the P0 slice (no photo path);
- `not_reported` is distinct from "missed" — absence of a report is not a miss;
- repeated writes are idempotent through the idempotency key;
- patient ownership is enforced by scoping every repository call by patient_id.

Self-report confirmation lifecycle (Session 3D, resolves B14)
------------------------------------------------------------
The database requires every ``dose_events`` row to cite a **confirmed,
unconsumed** ``record_self_report`` confirmation challenge
(``dose_events.confirmation_challenge_id NOT NULL`` + ``core_guard_dose_event``
-> ``core_consume_confirmation``). The application therefore completes the same
lifecycle the regimen-activation flow already uses:

1. resolve the occurrence and validate the write is otherwise legal;
2. issue an unconfirmed, unconsumed ``record_self_report`` challenge bound to
   the regimen, occurrence, intended intake status and idempotency key;
3. show the patient a human-readable summary of exactly what will be recorded;
4. take an explicit confirmation;
5. verify the challenge (owner, action, bindings, unexpired, unconsumed);
6. record the dose event citing that challenge;
7. let the database consume the challenge atomically with the write.

Step 7 is deliberately *not* re-implemented here: ``core_consume_confirmation``
performs the authoritative one-time consumption inside the same transaction as
the insert, so a crash between the two can never leave a reusable challenge.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from ..contracts.dto import (
    ConfirmationChallengeDTO,
    DoseEventDTO,
    DoseEventInput,
    DoseHistoryEntryDTO,
    DoseOccurrenceDTO,
    DoseRuleDTO,
    DueDoseResultDTO,
    RegimenVersionDTO,
    ReportSummaryDTO,
    SelfReportChallengeResultDTO,
    SelfReportResultDTO,
)
from ..contracts.enums import (
    IntakeStatus,
    OccurrenceStatus,
    RegimenState,
    RuleKind,
    VisualStatus,
)
from ..contracts.ports import (
    AgentSessionRepository,
    Clock,
    ConfirmationChallengeRepository,
    DoseEventRepository,
    DoseOccurrenceRepository,
    DoseRuleRepository,
    IdGenerator,
    PatientMedicationRepository,
    RegimenVersionRepository,
)
from ..domain import policy
from ..domain.errors import (
    ConfirmationExpiredError,
    ConfirmationRequiredError,
    DuplicateEventError,
    NotFoundError,
    ValidationError,
)
from .timezone import LOCAL_TZ_PROVIDER, LocalTzProvider, to_utc

#: A self-report challenge is short-lived for the same reason an activation
#: challenge is: the confirmation must be of the summary the patient just saw.
#: The database independently caps it at ten minutes
#: (``confirmation_challenges_time_ck``).
REPORT_CONFIRMATION_TTL = timedelta(minutes=10)

#: Action string for the self-report challenge; must match the CHECK constraint
#: on ``confirmation_challenges.action``.
RECORD_SELF_REPORT_ACTION = "record_self_report"


class DoseScheduleService:
    """Materialise dose occurrences deterministically from a regimen rule."""

    #: How far back an unreported occurrence may still be surfaced as "due".
    DUE_LOOKBACK = timedelta(days=1)

    def __init__(
        self,
        *,
        regimens: RegimenVersionRepository,
        rules: DoseRuleRepository,
        occurrences: DoseOccurrenceRepository,
        clock: Clock,
        ids: IdGenerator,
        tz_provider: LocalTzProvider | None = None,
    ) -> None:
        self._regimens = regimens
        self._rules = rules
        self._occurrences = occurrences
        self._clock = clock
        self._ids = ids
        self._tz = tz_provider or LOCAL_TZ_PROVIDER

    def add_rule(self, *, patient_id: UUID, regimen_id: UUID, rule: DoseRuleDTO) -> DoseRuleDTO:
        regimen = self._require_regimen(patient_id, regimen_id)
        if regimen.state != RegimenState.ACTIVE:
            raise ValidationError("Dose rules can only be added to an active regimen")
        if (rule.rule_kind == RuleKind.PRN) != regimen.is_prn:
            raise ValidationError("rule kind must match the regimen: PRN regimen takes a PRN rule")
        self._rules.add(rule)
        return rule

    def materialize(self, *, patient_id: UUID, regimen_id: UUID, days: int = 7) -> list[DoseOccurrenceDTO]:
        """Generate occurrences for the next `days` local days.

        The window starts at **local midnight of today**, not at "now": a dose
        scheduled earlier today must still exist as an occurrence so the patient
        can report it (otherwise today's dose could never be recorded).

        PRN regimens generate NO scheduled occurrence — a PRN dose only exists
        when the patient reports taking it (no inferred occurrence).
        """
        regimen = self._require_regimen(patient_id, regimen_id)
        if regimen.state != RegimenState.ACTIVE:
            raise ValidationError("Occurrences are generated only for an active regimen")
        if regimen.is_prn:
            return []

        tz = self._tz.local_tz(patient_id)
        now = self._clock.now()
        local_today = now.astimezone(tz).date()
        window_start = datetime(local_today.year, local_today.month, local_today.day, tzinfo=tz).astimezone(UTC)
        horizon_end = window_start + timedelta(days=days)
        generated: list[DoseOccurrenceDTO] = []

        for rule in self._rules.list_for_regimen(patient_id, regimen_id):
            if rule.rule_kind != RuleKind.SCHEDULED or not rule.enabled:
                continue
            for due_at in self._expand(rule, window_start, horizon_end, tz):
                course_day = due_at.astimezone(tz).date()
                if regimen.course_start_date and course_day < regimen.course_start_date:
                    continue
                if regimen.course_end_date and course_day > regimen.course_end_date:
                    continue
                if due_at < (regimen.effective_from or window_start):
                    continue
                key = f"{regimen_id}:{rule.id}:{due_at.astimezone(UTC).isoformat()}"
                existing = self._occurrences.find_by_generation_key(patient_id, key)
                if existing is not None:
                    generated.append(existing)
                    continue
                occurrence = DoseOccurrenceDTO(
                    id=self._ids.new_id(),
                    patient_id=patient_id,
                    regimen_id=regimen_id,
                    rule_id=rule.id,
                    due_at=due_at,
                    status=OccurrenceStatus.SCHEDULED,
                    generation_key=key,
                )
                self._occurrences.add(occurrence)
                # Concurrent Today/history/reminder reads may materialise the
                # same key. Return the canonical stored ID, never the losing
                # request's speculative UUID. Do not overwrite closed history.
                persisted = self._occurrences.find_by_generation_key(patient_id, key)
                if persisted is None or (persisted.regimen_id, persisted.rule_id, persisted.due_at) != (
                    occurrence.regimen_id,
                    occurrence.rule_id,
                    occurrence.due_at,
                ):
                    raise ValidationError("Could not verify the scheduled occurrence. Please retry.")
                generated.append(persisted)
        return sorted(generated, key=lambda o: o.due_at)

    @staticmethod
    def _expand(rule: DoseRuleDTO, start: datetime, end: datetime, tz: ZoneInfo) -> list[datetime]:
        """Expand a rule into absolute UTC instants within [start, end).

        Supports the same three kinds the SQL CHECK allows: daily / weekly /
        interval. DST is handled by constructing local wall-clock times in the
        patient timezone and converting to UTC.
        """
        moments: list[datetime] = []
        start_local = start.astimezone(tz)
        end_local = end.astimezone(tz)

        def _at(local_day, hh: int, mm: int) -> datetime:
            return datetime(local_day.year, local_day.month, local_day.day, hh, mm, tzinfo=tz).astimezone(UTC)

        if rule.rule_kind == RuleKind.SCHEDULED:
            times = [tuple(int(p) for p in t.split(":")) for t in rule.local_times]
            day = start_local.date()
            while day <= end_local.date():
                if rule.days_of_week and day.isoweekday() not in rule.days_of_week:
                    day = day + timedelta(days=1)
                    continue
                for hh, mm in times:
                    moment = _at(day, hh, mm)
                    if start <= moment < end:
                        moments.append(moment)
                day = day + timedelta(days=1)
        return sorted(moments)

    def tonight_window(self, patient_id: UUID) -> tuple[datetime, datetime]:
        local = self._clock.now().astimezone(self._tz.local_tz(patient_id))
        start = local.replace(hour=18, minute=0, second=0, microsecond=0)
        return start.astimezone(UTC), (start.replace(hour=0) + timedelta(days=1)).astimezone(UTC)

    def local_timezone(self, patient_id: UUID) -> str:
        return self._tz.local_tz(patient_id).key

    def today_window(self, patient_id: UUID) -> tuple[datetime, datetime]:
        start = (
            self._clock.now()
            .astimezone(self._tz.local_tz(patient_id))
            .replace(hour=0, minute=0, second=0, microsecond=0)
        )
        return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)

    def scheduled_today(self, *, patient_id: UUID, regimen_id: UUID) -> list[DoseOccurrenceDTO]:
        regimen = self._require_regimen(patient_id, regimen_id)
        if regimen.is_prn:
            return []
        self.materialize(patient_id=patient_id, regimen_id=regimen_id, days=2)
        start, end = self.today_window(patient_id)
        return self._occurrences.list_for_regimen(patient_id, regimen_id, start, end)

    def scheduled_tonight(self, *, patient_id: UUID, regimen_id: UUID) -> list[DoseOccurrenceDTO]:
        regimen = self._require_regimen(patient_id, regimen_id)
        if regimen.is_prn:
            return []
        self.materialize(patient_id=patient_id, regimen_id=regimen_id, days=2)
        start, end = self.tonight_window(patient_id)
        return self._occurrences.list_for_regimen(patient_id, regimen_id, start, end)

    def get_occurrence(self, patient_id: UUID, occurrence_id: UUID) -> DoseOccurrenceDTO | None:
        return self._occurrences.get(patient_id, occurrence_id)

    def find_due(self, *, patient_id: UUID, regimen_id: UUID, at: datetime | None = None) -> DueDoseResultDTO:
        """Return the earliest occurrence that has come due and has no report.

        An occurrence is *due* when its ``due_at`` is at or before ``at`` (an
        upcoming future dose is not yet actionable). The look-back window is
        bounded so a long-untouched regimen does not resurface ancient doses.
        """
        regimen = self._require_regimen(patient_id, regimen_id)
        moment = at or self._clock.now()
        if (
            regimen.course_end_date
            and moment.astimezone(self._tz.local_tz(patient_id)).date() > regimen.course_end_date
        ):
            return DueDoseResultDTO(occurrence=None, medication_display_name="", is_prn=regimen.is_prn)
        if regimen.is_prn:
            return DueDoseResultDTO(
                occurrence=None,
                medication_display_name="",
                is_prn=True,
            )
        window = self._occurrences.list_for_regimen(
            patient_id, regimen_id, moment - self.DUE_LOOKBACK, moment + timedelta(seconds=1)
        )
        for occurrence in window:
            if occurrence.status == OccurrenceStatus.CLOSED:
                continue
            if occurrence.due_at > moment:
                continue  # not actionable yet
            return DueDoseResultDTO(
                occurrence=occurrence,
                medication_display_name="",
                is_prn=False,
            )
        upcoming = self._occurrences.list_for_regimen(patient_id, regimen_id, moment, moment + timedelta(days=2))
        next_due = next(
            (row for row in upcoming if row.status != OccurrenceStatus.CLOSED and row.due_at > moment), None
        )
        return DueDoseResultDTO(
            occurrence=None, medication_display_name="", is_prn=False, next_due_at=next_due.due_at if next_due else None
        )

    def _require_regimen(self, patient_id: UUID, regimen_id: UUID) -> RegimenVersionDTO:
        regimen = self._regimens.get(patient_id, regimen_id)
        if regimen is None:
            raise NotFoundError(f"Regimen {regimen_id} not found for this patient")
        return regimen


class SelfReportService:
    """Record the patient's own report of taking / not taking a dose.

    The write is gated by the real ``record_self_report`` confirmation
    lifecycle (see the module docstring): the caller must first obtain a
    challenge, the patient must confirm it, and only then is the dose event
    written citing that challenge.
    """

    def __init__(
        self,
        *,
        regimens: RegimenVersionRepository,
        medications: PatientMedicationRepository,
        occurrences: DoseOccurrenceRepository,
        events: DoseEventRepository,
        challenges: ConfirmationChallengeRepository,
        sessions: AgentSessionRepository,
        clock: Clock,
        ids: IdGenerator,
        tz_provider: LocalTzProvider | None = None,
    ) -> None:
        self._regimens = regimens
        self._medications = medications
        self._occurrences = occurrences
        self._events = events
        self._challenges = challenges
        self._sessions = sessions
        self._clock = clock
        self._ids = ids
        self._tz = tz_provider or LOCAL_TZ_PROVIDER

    # -- step 1-3: resolve, validate, summarise and issue the challenge -------

    def confirmation_summary(
        self,
        *,
        patient_id: UUID,
        regimen_id: UUID,
        occurrence_id: UUID | None,
        intake_status: IntakeStatus,
    ) -> ReportSummaryDTO:
        """Human-readable statement of exactly what will be recorded.

        Reads only the patient's own records. Nothing is inferred and nothing
        is written.
        """
        regimen = self._require_regimen(patient_id, regimen_id)
        medication = self._medications.get(patient_id, regimen.patient_medication_id)
        occurrence = self._occurrences.get(patient_id, occurrence_id) if occurrence_id is not None else None
        tz = self._tz.local_tz(patient_id)
        due_at = occurrence.due_at if occurrence is not None else None
        return ReportSummaryDTO(
            medication_display_name=(medication.display_name if medication is not None else "Unknown medication"),
            dose_amount=regimen.dose_amount,
            dose_unit=regimen.dose_unit,
            regimen_version_no=regimen.version_no,
            occurrence_due_at=due_at,
            local_due_time=due_at.astimezone(tz).strftime("%Y-%m-%d %H:%M") if due_at else None,
            local_timezone=str(tz),
            intake_status=intake_status,
            intake_status_label=policy.intake_status_label(intake_status),
            safety_notice=policy.summarize_safety_notice(intake_status),
        )

    def find_existing_report(self, *, patient_id: UUID, idempotency_key: str) -> DoseEventDTO | None:
        """Return the already-recorded event for an idempotency key, if any.

        Used by the transport so a replayed report is answered with the
        existing event instead of asking the patient to confirm a second time.
        """
        return self._events.find_by_idempotency_key(patient_id, idempotency_key)

    def find_confirmation(self, *, patient_id: UUID, idempotency_key: str) -> ConfirmationChallengeDTO | None:
        return self._find_challenge_by_key(patient_id, idempotency_key)

    def request_confirmation(
        self,
        *,
        patient_id: UUID,
        regimen_id: UUID,
        occurrence_id: UUID | None,
        intake_status: IntakeStatus,
        idempotency_key: str,
        session_id: UUID,
        session_state_version: int,
    ) -> SelfReportChallengeResultDTO:
        """Issue (or reuse) an unconfirmed ``record_self_report`` challenge.

        Reuse matters: the schema has ``UNIQUE (patient_id, idempotency_key)``
        on ``confirmation_challenges``, so a double-tap must not attempt a
        second insert. An existing challenge for the same key is returned
        unchanged when it is still unexpired and unconsumed — never silently
        re-bound to a different occurrence or intake status.

        A challenge is never created for a report that is already recorded or
        that the policy would reject, so the patient is not asked to confirm
        something that cannot be saved.
        """
        regimen = self._require_regimen(patient_id, regimen_id)
        medication = self._medications.get(patient_id, regimen.patient_medication_id)
        occurrence = self._occurrences.get(patient_id, occurrence_id) if occurrence_id is not None else None
        occurrence_has_event = (
            occurrence is not None and self._events.find_by_occurrence(patient_id, occurrence.id) is not None
        )
        now = self._clock.now()
        policy.check_dose_write_preconditions(
            regimen=regimen,
            medication=medication,
            occurrence=occurrence,
            occurrence_has_event=occurrence_has_event,
            intake_status=intake_status,
            event_time=now,
        )
        policy.self_report_is_not_ingestion(intake_status, VisualStatus.NOT_CHECKED)
        self._check_course(patient_id, regimen, occurrence, now)

        summary = self.confirmation_summary(
            patient_id=patient_id,
            regimen_id=regimen_id,
            occurrence_id=occurrence.id if occurrence is not None else None,
            intake_status=intake_status,
        )

        existing = self._find_challenge_by_key(patient_id, idempotency_key)
        if existing is not None:
            self._assert_reusable(existing, regimen_id, occurrence, intake_status, now)
            return SelfReportChallengeResultDTO(challenge=existing, token="", created=False, summary=summary)

        token = self._ids.new_id().hex + self._ids.new_id().hex
        challenge = ConfirmationChallengeDTO(
            id=self._ids.new_id(),
            patient_id=patient_id,
            session_id=session_id,
            session_state_version=session_state_version,
            action=RECORD_SELF_REPORT_ACTION,
            regimen_id=regimen_id,
            occurrence_id=occurrence.id if occurrence is not None else None,
            intended_intake_status=intake_status,
            idempotency_key=idempotency_key,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            issued_at=now,
            expires_at=now + REPORT_CONFIRMATION_TTL,
        )
        self._challenges.add(challenge)
        return SelfReportChallengeResultDTO(challenge=challenge, token=token, created=True, summary=summary)

    # -- step 4-5: explicit confirmation and verification ---------------------

    def confirm_report(
        self, *, patient_id: UUID, payload: DoseEventInput, challenge_id: UUID
    ) -> ConfirmationChallengeDTO:
        """Check the displayed summary's exact bindings before arming consent."""
        challenge = self._require_challenge(patient_id, challenge_id)
        if challenge.consumed_at is not None or self._clock.now() >= challenge.expires_at:
            raise ConfirmationExpiredError("Confirmation is expired or already consumed")
        if (
            challenge.action != RECORD_SELF_REPORT_ACTION
            or challenge.regimen_id != payload.regimen_id
            or challenge.occurrence_id != payload.occurrence_id
            or challenge.intended_intake_status != payload.intake_status
            or challenge.idempotency_key != payload.idempotency_key
        ):
            raise ConfirmationRequiredError("Confirmation does not match this dose report")
        return self.confirm_challenge(patient_id=patient_id, challenge_id=challenge_id)

    def confirm_challenge(self, *, patient_id: UUID, challenge_id: UUID) -> ConfirmationChallengeDTO:
        """Record the patient's explicit confirmation of a displayed summary.

        Idempotent for an already-confirmed, unconsumed challenge (a repeated
        click does not move the timestamp), and refused once consumed or
        expired — a consumed challenge must never be re-armed.
        """
        challenge = self._require_challenge(patient_id, challenge_id)
        if challenge.action != RECORD_SELF_REPORT_ACTION:
            raise ConfirmationRequiredError("This confirmation is not a dose self-report confirmation")
        now = self._clock.now()
        if challenge.consumed_at is not None:
            raise ConfirmationExpiredError("Confirmation already consumed")
        if now >= challenge.expires_at:
            raise ConfirmationExpiredError("Challenge expired before confirmation")
        if challenge.confirmed_at is not None:
            return challenge
        confirmed = challenge.model_copy(update={"confirmed_at": now})
        self._challenges.update(confirmed)
        return confirmed

    # -- step 6-7: record, citing the confirmed challenge ---------------------

    def report(
        self,
        *,
        patient_id: UUID,
        payload: DoseEventInput,
        challenge_id: UUID | None = None,
    ) -> SelfReportResultDTO:
        """Idempotent self report, gated by a confirmed challenge.

        Replaying the same idempotency key returns the existing event instead
        of creating a second one (repeat writes must be idempotent) — and does
        so *before* any challenge is required, so a retry of an already-saved
        report never fails for want of a fresh confirmation.

        ``challenge_id`` is optional only for the agent tool path, which
        resolves the challenge the patient already confirmed. When it is absent
        a confirmed, unconsumed challenge matching the report's bindings must
        already exist; otherwise ``CONFIRMATION_REQUIRED`` is raised and the
        caller must complete the lifecycle.
        """
        regimen = self._require_regimen(patient_id, payload.regimen_id)

        existing = self._events.find_by_idempotency_key(patient_id, payload.idempotency_key)
        if existing is not None:
            if (
                existing.regimen_id != payload.regimen_id
                or existing.occurrence_id != payload.occurrence_id
                or existing.intake_status != payload.intake_status
            ):
                raise DuplicateEventError("Idempotency key belongs to a different report")
            return SelfReportResultDTO(event=None, existing_event_id=existing.id, already_recorded=True)

        medication = self._medications.get(patient_id, regimen.patient_medication_id)
        occurrence = (
            self._occurrences.get(patient_id, payload.occurrence_id) if payload.occurrence_id is not None else None
        )
        occurrence_has_event = (
            occurrence is not None and self._events.find_by_occurrence(patient_id, occurrence.id) is not None
        )
        event_time = to_utc(payload.event_time)

        policy.check_dose_write_preconditions(
            regimen=regimen,
            medication=medication,
            occurrence=occurrence,
            occurrence_has_event=occurrence_has_event,
            intake_status=payload.intake_status,
            event_time=event_time,
        )
        policy.self_report_is_not_ingestion(payload.intake_status, VisualStatus.NOT_CHECKED)
        self._check_course(patient_id, regimen, occurrence, event_time)

        challenge = self._resolve_challenge(
            patient_id=patient_id,
            challenge_id=challenge_id,
            regimen_id=regimen.id,
            occurrence_id=occurrence.id if occurrence is not None else None,
            intake_status=payload.intake_status,
            idempotency_key=payload.idempotency_key,
        )
        session = self._sessions.get(patient_id, challenge.session_id)
        policy.check_confirmation(
            challenge=challenge,
            expected_action=RECORD_SELF_REPORT_ACTION,
            expected_regimen_id=regimen.id,
            expected_occurrence_id=occurrence.id if occurrence is not None else None,
            expected_intake_status=payload.intake_status,
            expected_idempotency_key=payload.idempotency_key,
            session_state=session.state if session is not None else "",
            session_state_version=(session.state_version if session is not None else challenge.session_state_version),
            now=self._clock.now(),
        )

        event = DoseEventDTO(
            id=self._ids.new_id(),
            patient_id=patient_id,
            regimen_id=regimen.id,
            occurrence_id=occurrence.id if occurrence is not None else None,
            event_time=event_time,
            intake_status=payload.intake_status,
            visual_status=VisualStatus.NOT_CHECKED,
            ingestion_proven=False,
            idempotency_key=payload.idempotency_key,
            created_at=self._clock.now(),
        )
        # The write cites the confirmed challenge; the database consumes it
        # atomically in the same transaction (core_guard_dose_event ->
        # core_consume_confirmation). Consumption is never simulated here.
        saved = self._events.add(event)
        if saved is not None and saved.id != event.id:
            return SelfReportResultDTO(event=None, existing_event_id=saved.id, already_recorded=True)

        # Record the consumption in the application too. On PostgreSQL the
        # trigger has already consumed the row inside the insert's transaction,
        # so the repository's write is a no-op (it only sets a NULL column);
        # in-memory it is what makes the one-time semantics real. Either way the
        # challenge can never be used for a second report.
        self._challenges.update(challenge.model_copy(update={"consumed_at": self._clock.now()}))

        if occurrence is not None:
            self._occurrences.update(occurrence.model_copy(update={"status": OccurrenceStatus.CLOSED}))
        return SelfReportResultDTO(event=event, already_recorded=False)

    # -- helpers -------------------------------------------------------------

    def _check_course(self, patient_id, regimen, occurrence, event_time) -> None:
        # A late scheduled report belongs to the occurrence's calendar date.
        moment = occurrence.due_at if occurrence is not None else event_time
        day = moment.astimezone(self._tz.local_tz(patient_id)).date()
        if (regimen.course_start_date and day < regimen.course_start_date) or (
            regimen.course_end_date and day > regimen.course_end_date
        ):
            raise ValidationError("This dose is outside the reviewed course dates")

    def _resolve_challenge(
        self,
        *,
        patient_id: UUID,
        challenge_id: UUID | None,
        regimen_id: UUID,
        occurrence_id: UUID | None,
        intake_status: IntakeStatus,
        idempotency_key: str,
    ) -> ConfirmationChallengeDTO:
        """Return the challenge this report is allowed to cite, or refuse."""
        if challenge_id is not None:
            return self._require_challenge(patient_id, challenge_id)

        challenge = self._find_challenge_by_key(patient_id, idempotency_key)
        if challenge is None:
            raise ConfirmationRequiredError(
                "Recording a dose event requires a confirmed 'record_self_report' "
                "confirmation challenge; request one, confirm it, then retry"
            )
        if (
            challenge.action != RECORD_SELF_REPORT_ACTION
            or challenge.regimen_id != regimen_id
            or challenge.occurrence_id != occurrence_id
            or challenge.intended_intake_status != intake_status
        ):
            raise ConfirmationRequiredError("The existing confirmation challenge is bound to a different report")
        return challenge

    def _require_challenge(self, patient_id: UUID, challenge_id: UUID) -> ConfirmationChallengeDTO:
        challenge = self._challenges.get(patient_id, challenge_id)
        if challenge is None:
            # Patient-scoped read: another patient's challenge is simply absent.
            raise ConfirmationRequiredError("No confirmation challenge found for this patient")
        return challenge

    def _find_challenge_by_key(self, patient_id: UUID, idempotency_key: str) -> ConfirmationChallengeDTO | None:
        """Look up this patient's challenge for an idempotency key.

        The repository is patient-scoped, so a key belonging to another patient
        can never match here.
        """
        return self._challenges.find_by_idempotency_key(patient_id, idempotency_key)

    @staticmethod
    def _assert_reusable(
        challenge: ConfirmationChallengeDTO,
        regimen_id: UUID,
        occurrence: DoseOccurrenceDTO | None,
        intake_status: IntakeStatus,
        now: datetime,
    ) -> None:
        occurrence_id = occurrence.id if occurrence is not None else None
        if (
            challenge.action != RECORD_SELF_REPORT_ACTION
            or challenge.regimen_id != regimen_id
            or challenge.occurrence_id != occurrence_id
            or challenge.intended_intake_status != intake_status
        ):
            raise ConfirmationRequiredError(
                "An existing confirmation for this idempotency key is bound to a "
                "different report; use a new idempotency key"
            )
        if challenge.consumed_at is not None:
            raise ConfirmationExpiredError("This report was already recorded with this idempotency key")
        if now >= challenge.expires_at:
            raise ConfirmationExpiredError(
                "The previous confirmation for this idempotency key expired; "
                "request a new one with a fresh idempotency key"
            )

    def _require_regimen(self, patient_id: UUID, regimen_id: UUID) -> RegimenVersionDTO:
        regimen = self._regimens.get(patient_id, regimen_id)
        if regimen is None:
            raise NotFoundError(f"Regimen {regimen_id} not found for this patient")
        return regimen

    def history(
        self,
        *,
        patient_id: UUID,
        regimen_id: UUID,
        window_start: datetime,
        window_end: datetime,
    ) -> list[DoseHistoryEntryDTO]:
        """State-aware history: not_reported is NOT missed."""
        regimen = self._regimens.get(patient_id, regimen_id)
        if regimen is None:
            raise NotFoundError(f"Regimen {regimen_id} not found for this patient")
        medication = self._medications.get(patient_id, regimen.patient_medication_id)
        name = medication.display_name if medication else ""

        all_events = self._events.list_for_patient(patient_id, window_start, window_end)
        events = {e.occurrence_id: e for e in all_events if e.occurrence_id is not None}
        occurrences = self._occurrences.list_for_regimen(patient_id, regimen_id, window_start, window_end)

        entries: list[DoseHistoryEntryDTO] = []
        for occurrence in occurrences:
            entries.append(
                DoseHistoryEntryDTO(
                    event=events.get(occurrence.id),
                    occurrence=occurrence,
                    regimen_id=regimen_id,
                    medication_display_name=name,
                )
            )
        if regimen.is_prn:
            entries.extend(
                DoseHistoryEntryDTO(event=event, occurrence=None, regimen_id=regimen_id, medication_display_name=name)
                for event in all_events
                if event.regimen_id == regimen_id and event.occurrence_id is None
            )
        return entries


def patient_local_now(clock: Clock, tz: ZoneInfo | None = None) -> datetime:
    """Local wall-clock now for display only; storage always uses UTC."""
    zone = tz or ZoneInfo("Asia/Singapore")
    return clock.now().astimezone(zone)
