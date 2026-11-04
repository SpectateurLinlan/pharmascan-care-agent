"""Explicit local native report transaction; no persistent callback fallback."""

import hashlib
import json
from contextlib import contextmanager
from copy import deepcopy

from ..contracts.assistant_workflows import BusinessRef, WorkflowContext, WorkflowUpdate, validate_workflow_values
from ..contracts.dto import DoseEventDTO, SelfReportChallengeResultDTO, SelfReportResultDTO
from ..contracts.enums import IntakeStatus
from ..contracts.late_reports import LateReportChallenge
from ..contracts.workflow_persistence import BusinessWriteReceipt, NativeWriteResult
from ..contracts.workflow_record_writes import (
    RECORD_PREPARATION_COMMAND,
    RECORD_WRITE_COMMAND,
    RecordNativeResult,
    RecordPreparationNativeResult,
)
from ..domain.errors import (
    DuplicateEventError,
    NotFoundError,
    ProviderUnavailableError,
    StaleVersionError,
    ValidationError,
)


def record_command_digest(command):
    value = command.model_dump(mode="json")
    if command.kind in {"self_report", "prn_report"}:
        # Native report HTTP uses server confirmation time. Client retries must
        # not change identity merely because that non-authoritative time moved.
        value["values"].pop("event_time")
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class MemoryRecordWorkflowWrites:
    def __init__(self, *, state, store, clock, tasks, controls, actions, reports, late_reports, enrollment, schedule):
        self._state, self._store, self._clock = state, store, clock
        self._tasks, self._controls, self._actions = tasks, controls, actions
        self._reports, self._late, self._enrollment, self._schedule = reports, late_reports, enrollment, schedule

    def revision(self, owner):
        with self._store.clinical.lock:
            return self._store.clinical.revisions.get(owner, 0)

    def lookup(self, owner, action_key):
        with self._state.lock:
            return self._state.business_receipts.get((owner, action_key))

    @contextmanager
    def _transaction(self):
        mappings = [
            self._state.tasks,
            self._state.controls,
            self._state.events,
            self._state.actions,
            self._state.business_receipts,
            self._state.record_commands,
            self._state.record_preparations,
            self._store.events,
            self._store.late_reports,
            self._store.sessions,
            self._store.clinical.revisions,
        ]
        backups = [deepcopy(value) for value in mappings]
        tables = [self._store.challenges, self._store.occurrences]
        rows = [deepcopy(table.rows) for table in tables]
        used = set(self._state.used)
        try:
            yield
        except BaseException:
            for current, old in zip(mappings, backups, strict=True):
                current.clear()
                current.update(old)
            for table, old in zip(tables, rows, strict=True):
                table.rows = old
            self._state.used.clear()
            self._state.used.update(used)
            raise

    def _read_native(self, owner, command, receipt):
        if command.kind in {"self_report", "prn_report"}:
            event = self._reports.find_existing_report(patient_id=owner, idempotency_key=command.values.idempotency_key)
            if event is None or event.id != receipt.business_ref.id:
                raise StaleVersionError("Applied report is unavailable; retain its receipt")
            return NativeWriteResult(
                receipt=receipt,
                result=SelfReportResultDTO(event=event, existing_event_id=event.id, already_recorded=True),
            )
        report = next(
            (
                row
                for row in self._late.audit(owner, command.occurrence_id).corrections
                if row.id == receipt.business_ref.id
            ),
            None,
        )
        if report is None:
            raise StaleVersionError("Applied historical report is unavailable; retain its receipt")
        return NativeWriteResult(receipt=receipt, result=report)

    def _read_preparation(self, owner, command, receipt):
        retained = self._state.record_preparations.get((owner, command.binding.action_key))
        if command.kind == "prepare_review":
            if retained is None or retained[1] is not None:
                raise StaleVersionError("Actual target selection receipt unavailable")
            return NativeWriteResult(receipt=receipt, result=None)
        if command.kind == "prepare_late_report":
            occurrence_id = command.binding.prepared_ref.id
            challenge = self._late.find_confirmation(owner, command.values.binding_key(occurrence_id))
            if (
                retained is None
                or challenge is None
                or retained[1] != challenge.id
                or challenge.consumed_at is not None
            ):
                raise StaleVersionError("Native historical confirmation unavailable; retain its receipt")
            return NativeWriteResult(
                receipt=receipt,
                result=LateReportChallenge(
                    challenge_id=challenge.id,
                    session_id=challenge.session_id,
                    expires_at=challenge.expires_at,
                    occurrence=self._late.occurrence(owner, occurrence_id),
                    proposed=command.values,
                    timezone=self._schedule.local_timezone(owner),
                ),
            )
        challenge = self._reports.find_confirmation(
            patient_id=owner, idempotency_key="report-" + str(command.operation_key)
        )
        if retained is None or challenge is None or retained[1] != challenge.id:
            raise StaleVersionError("Native confirmation unavailable; retain its preparation receipt")
        summary = self._reports.confirmation_summary(
            patient_id=owner,
            regimen_id=challenge.regimen_id,
            occurrence_id=challenge.occurrence_id,
            intake_status=challenge.intended_intake_status,
        )
        return NativeWriteResult(
            receipt=receipt,
            result=SelfReportChallengeResultDTO(challenge=challenge, token="", created=False, summary=summary),
        )

    def prepare(self, owner, command):
        command = RECORD_PREPARATION_COMMAND.validate_python(command.model_dump())
        if command.kind == "prepare_review":
            return self._prepare_review(owner, command)
        b = command.binding
        key = (owner, b.action_key)
        digest = hashlib.sha256(
            json.dumps(command.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        with self._state.lock, self._store.clinical.lock, self._store.late_report_lock, self._store.session_lock:
            prior = self.lookup(owner, b.action_key)
            if prior is not None:
                retained = self._state.record_preparations.get(key)
                if retained is None or retained[0] != digest:
                    raise DuplicateEventError("Preparation action already belongs to different inputs")
                return self._read_preparation(owner, command, prior)
            task, control = self._tasks.get(owner, b.task_id), self._controls.get(owner, b.task_id)
            historical = command.kind == "prepare_late_report"
            capabilities = (
                {"dose.late.review", "dose.correction.review"} if historical else {"dose.report", "dose.prn.report"}
            )
            if (
                task.revision != b.task_revision
                or control.revision != b.task_revision
                or b.capability_id not in capabilities
                or task.capability_id != b.capability_id
                or task.state != "awaiting_confirmation"
                or control.mode != "allowed"
                or control.revoked
                or control.status != "idle"
                or task.save_mode != "allowed"
                or b.prepared_ref not in task.business_refs
                or self.revision(owner) != b.expected_domain_revision
            ):
                raise StaleVersionError("Current independent patient report preparation changed")
            if b.run_binding is not None:
                self._state.require_durable_run(owner, b.run_binding, self._clock.now())
            ref = b.prepared_ref
            if historical:
                return self._prepare_late(owner, command, task, ref, digest)
            plan = self._enrollment.get_regimen(owner, ref.id) if ref.kind == "regimen" else None
            if (
                plan is None
                or plan.version_no != ref.version
                or plan.state.value != "active"
                or plan.is_prn != (b.capability_id == "dose.prn.report")
            ):
                raise StaleVersionError("Current report plan changed")
            session = self._store.sessions.get((owner, command.session_id))
            if (
                session is None
                or session.state != "awaiting_confirmation"
                or session.state_version != command.session_state_version
                or session.expires_at <= self._clock.now()
            ):
                raise StaleVersionError("Independent patient session changed or expired")
            native_key = "report-" + str(command.operation_key)
            old = self._reports.find_confirmation(patient_id=owner, idempotency_key=native_key)
            if old is not None:
                self._check_challenge_binding(owner, task, ref, old)
                if old.session_id != session.id or old.session_state_version != session.state_version:
                    raise StaleVersionError("Confirmation belongs to a different patient session")
            occurrence_id = command.occurrence_id
            if plan.is_prn and occurrence_id is not None:
                raise ValidationError("PRN reports cannot use a scheduled occurrence")
            if not plan.is_prn:
                occurrence = self._schedule.get_occurrence(owner, occurrence_id) if occurrence_id is not None else None
                if occurrence is None or occurrence.regimen_id != plan.id:
                    raise ValidationError("Choose an existing currently due scheduled occurrence")
            with self._transaction():
                result = self._reports.request_confirmation(
                    patient_id=owner,
                    regimen_id=plan.id,
                    occurrence_id=occurrence_id,
                    intake_status=IntakeStatus(command.intake_status),
                    idempotency_key=native_key,
                    session_id=session.id,
                    session_state_version=session.state_version,
                )
                context = WorkflowContext(
                    owner=owner, task_id=task.id, capability_id=task.capability_id, revision=task.revision
                )
                actual = self._actions.reserve(context, result.challenge.id)
                self._actions.complete(context, actual.model_copy(update={"business_ref": ref}))
                if b.run_binding is not None:
                    self._state.require_durable_run(owner, b.run_binding, self._clock.now())
                receipt = BusinessWriteReceipt(
                    owner=owner,
                    task_id=task.id,
                    action_key=b.action_key,
                    capability_id=task.capability_id,
                    binding_revision=task.revision,
                    business_ref=ref,
                    domain_revision=self.revision(owner),
                    outcome="prepared",
                    recorded_at=self._clock.now(),
                )
                self._state.record_preparations[key] = (digest, result.challenge.id)
                self._state.business_receipts[key] = receipt
                return NativeWriteResult(receipt=receipt, result=result)

    def _prepare_review(self, owner, command):
        b, digest = command.binding, record_command_digest(command)
        with self._state.lock, self._store.clinical.lock, self._store.late_report_lock, self._store.session_lock:
            prior = self.lookup(owner, b.action_key)
            if prior is not None:
                if self._state.record_preparations.get((owner, b.action_key)) != (digest, None):
                    raise DuplicateEventError("Review event belongs to different record inputs")
                return NativeWriteResult(receipt=prior, result=None)
            task, control = self._tasks.get(owner, b.task_id), self._controls.get(owner, b.task_id)
            if (
                task.revision != b.task_revision
                or control.revision != b.task_revision
                or control.revoked
                or control.mode != "allowed"
                or control.status != "idle"
                or task.save_mode != "allowed"
                or task.state != "ready_for_review"
                or task.capability_id != b.capability_id
                or task.attachment_ids
                or task.business_refs
                or self.revision(owner) != b.expected_domain_revision
            ):
                raise StaleVersionError("Current saved report target changed")
            values = validate_workflow_values(task.capability_id, task.fields)
            if task.capability_id in {"dose.late.review", "dose.correction.review"}:
                ref = BusinessRef(kind="dose_occurrence", id=values.occurrence_id, version=values.expected_version)
                target = self._late.occurrence(owner, ref.id)
                if (
                    len(self._late.audit(owner, ref.id).corrections) + 1 != ref.version
                    or target.report_id != values.expected_report_id
                    or bool(target.report_id) != (task.capability_id == "dose.correction.review")
                ):
                    raise StaleVersionError("Current historical report changed")
            elif task.capability_id in {"dose.report", "dose.prn.report"}:
                ref = BusinessRef(kind="regimen", id=values.regimen_id, version=values.expected_version)
                plan = self._enrollment.get_regimen(owner, ref.id)
                med = self._enrollment.get_medication(owner, plan.patient_medication_id) if plan else None
                if (
                    plan is None
                    or med is None
                    or med.archived_at is not None
                    or plan.state.value != "active"
                    or plan.version_no != ref.version
                    or plan.is_prn != (task.capability_id == "dose.prn.report")
                ):
                    raise StaleVersionError("Current active report plan changed")
            else:
                raise ValidationError("This capability cannot prepare a patient report")
            if ref != b.prepared_ref:
                raise StaleVersionError("Reviewed target differs from saved selection")
            if b.run_binding is not None:
                self._state.require_durable_run(owner, b.run_binding, self._clock.now())
            with self._transaction():
                self._tasks.cas(
                    owner,
                    task.id,
                    task.revision,
                    b.action_key,
                    WorkflowUpdate(
                        state="awaiting_confirmation",
                        save_mode="allowed",
                        storage_state="saved",
                        fields=task.fields,
                        missing_fields=(),
                        attachment_ids=(),
                        business_refs=(ref,),
                    ),
                    request_digest=digest,
                )
                if b.run_binding is not None:
                    self._state.require_durable_run(owner, b.run_binding, self._clock.now())
                receipt = BusinessWriteReceipt(
                    owner=owner,
                    task_id=task.id,
                    action_key=b.action_key,
                    capability_id=task.capability_id,
                    binding_revision=task.revision + 1,
                    business_ref=ref,
                    domain_revision=self.revision(owner),
                    outcome="prepared",
                    recorded_at=self._clock.now(),
                )
                self._state.record_preparations[owner, b.action_key] = (digest, None)
                self._state.business_receipts[owner, b.action_key] = receipt
                return NativeWriteResult(receipt=receipt, result=None)

    def review(self, owner, task_id, revision):
        with self._state.lock:
            rows = [
                r
                for (patient, key), r in self._state.business_receipts.items()
                if patient == owner
                and r.task_id == task_id
                and r.binding_revision == revision
                and r.outcome == "prepared"
                and (patient, key) in self._state.record_preparations
                and self._state.record_preparations[patient, key][1] is None
            ]
            if len(rows) != 1:
                raise NotFoundError("Actual owned report target-selection receipt unavailable")
            return rows[0]

    def read_result(self, owner, receipt):
        with self._state.lock, self._store.clinical.lock, self._store.late_report_lock:
            if (
                receipt.owner != owner
                or receipt.outcome != "applied"
                or self.lookup(owner, receipt.action_key) != receipt
                or (owner, receipt.action_key) not in self._state.record_commands
            ):
                raise NotFoundError("Actual owned applied report receipt unavailable")
            target = self.review(owner, receipt.task_id, receipt.binding_revision - 1).business_ref
            if receipt.capability_id in {"dose.report", "dose.prn.report"}:
                event = self._reports.find_existing_report(
                    patient_id=owner, idempotency_key="report-" + str(receipt.action_key)
                )
                if (
                    event is None
                    or event.id != receipt.business_ref.id
                    or event.regimen_id != target.id
                    or receipt.business_ref.kind != "dose_event"
                ):
                    raise StaleVersionError("Applied report unavailable; retain its immutable receipt")
                native = SelfReportResultDTO(event=event, existing_event_id=event.id, already_recorded=True)
            else:
                native = next(
                    (
                        row
                        for row in self._late.audit(owner, target.id).corrections
                        if row.id == receipt.business_ref.id and row.version == receipt.business_ref.version
                    ),
                    None,
                )
                if native is None or receipt.business_ref.kind != "late_report":
                    raise StaleVersionError("Applied historical report unavailable; retain its receipt")
            return NativeWriteResult(receipt=receipt, result=native)

    def _prepare_late(self, owner, command, task, ref, digest):
        b = command.binding
        if (
            ref.kind != "dose_occurrence"
            or task.fields.get("occurrence_id") != str(ref.id)
            or task.fields.get("expected_version") != ref.version
            or task.fields.get("expected_report_id")
            != (str(command.values.expected_report_id) if command.values.expected_report_id else None)
            or (command.values.expected_report_id is not None) != (task.capability_id == "dose.correction.review")
        ):
            raise StaleVersionError("Current historical review differs from this proposed report")
        self._late.validate(owner, ref.id, command.values)
        if len(self._late.audit(owner, ref.id).corrections) + 1 != ref.version:
            raise StaleVersionError("Historical report version changed")
        session = self._store.sessions.get((owner, command.session_id))
        if (
            session is None
            or session.state != "awaiting_confirmation"
            or session.expires_at <= self._clock.now()
            or session.state_version != command.session_state_version
        ):
            raise StaleVersionError("Independent historical confirmation session changed")
        old = self._late.find_confirmation(owner, command.values.binding_key(ref.id))
        if old is not None:
            self._check_challenge_binding(owner, task, ref, old)
            if old.session_id != session.id or old.session_state_version != session.state_version:
                raise StaleVersionError("Historical confirmation belongs to another session")
        with self._transaction():
            result = self._late.prepare(owner, ref.id, command.values, session)
            context = WorkflowContext(
                owner=owner, task_id=task.id, capability_id=task.capability_id, revision=task.revision
            )
            issued = self._actions.reserve(context, result.challenge_id)
            self._actions.complete(context, issued.model_copy(update={"business_ref": ref}))
            if b.run_binding is not None:
                self._state.require_durable_run(owner, b.run_binding, self._clock.now())
            receipt = BusinessWriteReceipt(
                owner=owner,
                task_id=task.id,
                action_key=b.action_key,
                capability_id=task.capability_id,
                binding_revision=task.revision,
                business_ref=ref,
                domain_revision=self.revision(owner),
                outcome="prepared",
                recorded_at=self._clock.now(),
            )
            self._state.record_preparations[owner, b.action_key] = (digest, result.challenge_id)
            self._state.business_receipts[owner, b.action_key] = receipt
            return NativeWriteResult(receipt=receipt, result=result)

    def _check_challenge_binding(self, owner, task, ref, challenge):
        try:
            actual = self._actions.read(owner, challenge.id)
        except NotFoundError:
            raise StaleVersionError("Confirmation is not bound to this current review") from None
        if (
            actual.owner != owner
            or actual.task_id != task.id
            or actual.capability_id != task.capability_id
            or actual.binding_revision != task.revision
            or actual.business_ref != ref
        ):
            raise StaleVersionError("Confirmation belongs to another task or revision")

    def apply(self, owner, command):
        command = RECORD_WRITE_COMMAND.validate_python(command.model_dump())
        b = command.binding
        key = (owner, b.action_key)
        digest = record_command_digest(command)
        historical = command.kind in {"late_report", "correction"}
        with self._state.lock, self._store.clinical.lock, self._store.late_report_lock, self._store.session_lock:
            prior = self.lookup(owner, b.action_key)
            if prior is not None:
                if self._state.record_commands.get(key) != digest:
                    raise DuplicateEventError("Record action is already bound to different inputs")
                return self._read_native(owner, command, prior)
            task, control = self._tasks.get(owner, b.task_id), self._controls.get(owner, b.task_id)
            capability = {
                "self_report": "dose.report",
                "prn_report": "dose.prn.report",
                "late_report": "dose.late.review",
                "correction": "dose.correction.review",
            }[command.kind]
            if (
                task.revision != b.task_revision
                or control.revision != b.task_revision
                or task.capability_id != capability
                or b.capability_id != capability
                or task.state != "awaiting_confirmation"
                or control.mode != "allowed"
                or control.revoked
                or control.status != "idle"
                or task.save_mode != "allowed"
                or b.prepared_ref not in task.business_refs
                or self.revision(owner) != b.expected_domain_revision
            ):
                raise StaleVersionError("The current patient report review changed")
            if b.run_binding is not None:
                self._state.require_durable_run(owner, b.run_binding, self._clock.now())
            ref = b.prepared_ref
            if historical:
                if (
                    ref.kind != "dose_occurrence"
                    or ref.id != command.occurrence_id
                    or command.values.id != b.action_key
                    or task.fields.get("occurrence_id") != str(command.occurrence_id)
                    or task.fields.get("expected_report_id")
                    != (str(command.values.expected_report_id) if command.values.expected_report_id else None)
                ):
                    raise ValidationError("Historical confirmation differs from the selected report")
                actual = self._late.occurrence(owner, command.occurrence_id)
                if (
                    len(self._late.audit(owner, command.occurrence_id).corrections) + 1 != ref.version
                    or actual.report_id != command.values.expected_report_id
                ):
                    raise StaleVersionError("Current historical report changed")
                native_key = command.values.binding_key(command.occurrence_id)
                challenge = self._late.find_confirmation(owner, native_key)
            else:
                if (
                    ref.kind != "regimen"
                    or ref.id != command.values.regimen_id
                    or command.values.idempotency_key != "report-" + str(b.action_key)
                ):
                    raise ValidationError("Patient report request differs from its selected plan")
                plan = self._enrollment.get_regimen(owner, ref.id)
                if (
                    plan is None
                    or plan.version_no != ref.version
                    or plan.state.value != "active"
                    or plan.is_prn != (command.kind == "prn_report")
                ):
                    raise StaleVersionError("The reviewed medication plan changed")
                challenge = self._reports.find_confirmation(
                    patient_id=owner, idempotency_key=command.values.idempotency_key
                )
            if challenge is None or challenge.id != command.challenge_id:
                raise StaleVersionError("Request a matching independent confirmation first")
            try:
                original = self._actions.read(owner, challenge.id)
            except NotFoundError:
                raise StaleVersionError("Confirmation is not bound to this current review") from None
            if (
                original.owner != owner
                or original.task_id != task.id
                or original.capability_id != capability
                or original.binding_revision != task.revision
                or original.business_ref != ref
            ):
                raise StaleVersionError("Confirmation belongs to another task or revision")
            session = self._store.sessions.get((owner, challenge.session_id))
            if (
                session is None
                or session.state != "awaiting_confirmation"
                or session.expires_at <= self._clock.now()
                or session.state_version != challenge.session_state_version
            ):
                raise StaleVersionError("Independent confirmation session changed or expired")
            with self._transaction():
                if historical:
                    native = self._late.confirm(owner, command.occurrence_id, command.values, challenge.id)
                    result_ref = BusinessRef(kind="late_report", id=native.id, version=native.version)
                else:
                    payload = command.values.model_copy(update={"event_time": self._clock.now()})
                    self._reports.confirm_report(patient_id=owner, payload=payload, challenge_id=challenge.id)
                    native = self._reports.report(patient_id=owner, payload=payload, challenge_id=challenge.id)
                    actual = native.event or self._reports.find_existing_report(
                        patient_id=owner, idempotency_key=payload.idempotency_key
                    )
                    if actual is None:
                        raise StaleVersionError("Native report did not publish an owned event")
                    result_ref = BusinessRef(kind="dose_event", id=actual.id)
                if b.run_binding is not None:
                    self._state.require_durable_run(owner, b.run_binding, self._clock.now())
                self._tasks.cas(
                    owner,
                    task.id,
                    task.revision,
                    b.action_key,
                    WorkflowUpdate(
                        state="completed",
                        save_mode="allowed",
                        storage_state="saved",
                        fields=task.fields,
                        missing_fields=(),
                        attachment_ids=task.attachment_ids,
                        business_refs=(result_ref,),
                    ),
                )
                receipt = BusinessWriteReceipt(
                    owner=owner,
                    task_id=task.id,
                    action_key=b.action_key,
                    capability_id=capability,
                    binding_revision=task.revision + 1,
                    business_ref=result_ref,
                    domain_revision=self.revision(owner),
                    outcome="applied",
                    recorded_at=self._clock.now(),
                )
                self._state.record_commands[key] = digest
                self._state.business_receipts[key] = receipt
                return NativeWriteResult(receipt=receipt, result=native)


class SupabaseRecordWorkflowWrites:
    """Fixed owner-JWT domain transport; only native readback follows a receipt."""

    def __init__(self, *, data, reads, receipts):
        self._data, self._reads, self._receipts = data, reads, receipts

    def revision(self, owner):
        self._data.check_patient(owner)
        return self._reads.revision(owner)

    def lookup(self, owner, action_key):
        self._data.check_patient(owner)
        return self._receipts.read_receipt(owner, action_key)

    def review(self, owner, task_id, revision):
        self._data.check_patient(owner)
        raw = self._data.request(
            "POST",
            "/rest/v1/rpc/assistant_record_review_receipt",
            body={"p_task_id": str(task_id), "p_revision": revision},
        )
        if not isinstance(raw, dict) or set(raw) != {"result"}:
            raise NotFoundError("Actual owned report-selection receipt unavailable")
        try:
            receipt = BusinessWriteReceipt.model_validate(raw["result"])
            if (
                receipt.owner != owner
                or receipt.task_id != task_id
                or receipt.binding_revision != revision
                or receipt.outcome != "prepared"
                or receipt.capability_id
                not in {"dose.report", "dose.prn.report", "dose.late.review", "dose.correction.review"}
            ):
                raise ValueError
            return receipt
        except (ValueError, TypeError):
            raise ProviderUnavailableError("Owned report-selection receipt binding unavailable") from None

    def read_result(self, owner, receipt):
        self._data.check_patient(owner)
        if receipt.owner != owner or receipt.outcome != "applied" or self.lookup(owner, receipt.action_key) != receipt:
            raise NotFoundError("Actual owned applied report receipt unavailable")
        review = self.review(owner, receipt.task_id, receipt.binding_revision - 1)
        if review.capability_id != receipt.capability_id:
            raise ProviderUnavailableError("Applied report differs from its actual selected target")
        target = review.business_ref
        raw = self._data.request(
            "POST", "/rest/v1/rpc/assistant_record_result", body={"p_action_key": str(receipt.action_key)}
        )
        if not isinstance(raw, dict) or set(raw) != {"result"}:
            raise ProviderUnavailableError("Actual native report unavailable; retain its immutable receipt")
        try:
            result = NativeWriteResult[RecordNativeResult].model_validate(raw["result"])
            native = result.result
            if result.receipt != receipt:
                raise ValueError
            if receipt.capability_id in {"dose.report", "dose.prn.report"}:
                event = native.event if isinstance(native, SelfReportResultDTO) else native
                if (
                    not isinstance(event, DoseEventDTO)
                    or event.patient_id != owner
                    or target.kind != "regimen"
                    or event.regimen_id != target.id
                    or receipt.business_ref != BusinessRef(kind="dose_event", id=event.id)
                    or event.idempotency_key != "report-" + str(receipt.action_key)
                    or (event.occurrence_id is None) != (receipt.capability_id == "dose.prn.report")
                    or event.ingestion_proven is not False
                    or event.visual_status.value != "not_checked"
                ):
                    raise ValueError
            elif receipt.capability_id in {"dose.late.review", "dose.correction.review"}:
                if (
                    native.patient_id != owner
                    or target.kind != "dose_occurrence"
                    or native.occurrence_id != target.id
                    or receipt.business_ref != BusinessRef(kind="late_report", id=native.id, version=native.version)
                    or (native.expected_report_id is not None) != (receipt.capability_id == "dose.correction.review")
                    or native.ingestion_proven is not False
                    or native.visual_status != "not_checked"
                ):
                    raise ValueError
            else:
                raise ValueError
            return result
        except (ValueError, TypeError, AttributeError):
            raise ProviderUnavailableError("Actual report result binding unavailable") from None

    def prepare(self, owner, command):
        self._data.check_patient(owner)
        command = RECORD_PREPARATION_COMMAND.validate_python(command.model_dump())
        b = command.binding
        prior = self.lookup(owner, b.action_key)
        endpoint = "assistant_record_read" if prior is not None else "assistant_record_prepare"
        raw = self._data.request(
            "POST", "/rest/v1/rpc/" + endpoint, body={"p_command": command.model_dump(mode="json")}
        )
        if (
            not isinstance(raw, dict)
            or set(raw) not in ({"result"}, {"result", "replayed"}, {"error"})
            or ("replayed" in raw and type(raw["replayed"]) is not bool)
        ):
            raise ProviderUnavailableError("Record preparation outcome unavailable; inspect its receipt")
        if "error" in raw:
            errors = {
                "stale": StaleVersionError,
                "duplicate": DuplicateEventError,
                "invalid": ValidationError,
                "not_found": NotFoundError,
            }
            kind = raw["error"] if isinstance(raw["error"], str) else "unavailable"
            raise errors.get(kind, ProviderUnavailableError)("Record preparation changed; inspect its current receipt")
        try:
            result = NativeWriteResult[RecordPreparationNativeResult].model_validate(raw["result"])
            receipt, native = result.receipt, result.result
            if (
                receipt.owner != owner
                or receipt.task_id != b.task_id
                or receipt.action_key != b.action_key
                or receipt.capability_id != b.capability_id
                or receipt.binding_revision != b.task_revision + (1 if command.kind == "prepare_review" else 0)
                or receipt.business_ref != b.prepared_ref
                or receipt.domain_revision < b.expected_domain_revision
                or receipt.outcome != "prepared"
                or (prior is not None and (receipt != prior or raw.get("replayed") is not True))
            ):
                raise ValueError
            if command.kind == "prepare_review":
                if native is not None:
                    raise ValueError
                return result
            if command.kind == "prepare_late_report":
                if (
                    not isinstance(native, LateReportChallenge)
                    or native.session_id != command.session_id
                    or native.occurrence.occurrence_id != b.prepared_ref.id
                    or native.proposed != command.values
                ):
                    raise ValueError
            else:
                if not isinstance(native, SelfReportChallengeResultDTO):
                    raise ValueError
                challenge = native.challenge
                if (
                    challenge.patient_id != owner
                    or challenge.session_id != command.session_id
                    or challenge.session_state_version != command.session_state_version
                    or challenge.action != "record_self_report"
                    or challenge.regimen_id != b.prepared_ref.id
                    or challenge.occurrence_id != command.occurrence_id
                    or challenge.intended_intake_status.value != command.intake_status
                    or challenge.idempotency_key != "report-" + str(command.operation_key)
                    or native.summary.regimen_version_no != b.prepared_ref.version
                    or native.summary.ingestion_proven is not False
                    or native.summary.visual_status.value != "not_checked"
                ):
                    raise ValueError
                if prior is not None and (native.token != "" or native.created is not False):
                    raise ValueError
            return result
        except (ValueError, TypeError, AttributeError):
            raise ProviderUnavailableError(
                "Record preparation binding unavailable; inspect its native receipt"
            ) from None

    def apply(self, owner, command):
        self._data.check_patient(owner)
        command = RECORD_WRITE_COMMAND.validate_python(command.model_dump())
        b = command.binding
        prior = self.lookup(owner, b.action_key)
        endpoint = "assistant_record_read" if prior is not None else "assistant_record_write"
        raw = self._data.request(
            "POST", "/rest/v1/rpc/" + endpoint, body={"p_command": command.model_dump(mode="json")}
        )
        if (
            not isinstance(raw, dict)
            or set(raw) not in ({"result"}, {"result", "replayed"}, {"error"})
            or ("replayed" in raw and type(raw["replayed"]) is not bool)
        ):
            raise ProviderUnavailableError("Record write outcome unavailable; inspect its receipt")
        if "error" in raw:
            errors = {
                "stale": StaleVersionError,
                "duplicate": DuplicateEventError,
                "invalid": ValidationError,
                "not_found": NotFoundError,
            }
            kind = raw["error"] if isinstance(raw["error"], str) else "unavailable"
            raise errors.get(kind, ProviderUnavailableError)("Record write changed; inspect its current receipt")
        try:
            result = NativeWriteResult[RecordNativeResult].model_validate(raw["result"])
            receipt = result.receipt
            if (
                receipt.owner != owner
                or receipt.task_id != b.task_id
                or receipt.action_key != b.action_key
                or receipt.capability_id != b.capability_id
                or receipt.binding_revision != b.task_revision + 1
                or receipt.domain_revision < b.expected_domain_revision
                or receipt.outcome != "applied"
                or (prior is not None and (receipt != prior or raw.get("replayed") is not True))
            ):
                raise ValueError
            native = result.result
            if command.kind in {"self_report", "prn_report"}:
                if receipt.business_ref.kind != "dose_event":
                    raise ValueError
                event = native if isinstance(native, DoseEventDTO) else native.event
                if event is None:
                    if (
                        not isinstance(native, SelfReportResultDTO)
                        or not native.already_recorded
                        or native.existing_event_id != receipt.business_ref.id
                    ):
                        raise ValueError
                elif (
                    event.patient_id != owner
                    or event.id != receipt.business_ref.id
                    or event.regimen_id != command.values.regimen_id
                    or event.occurrence_id != command.values.occurrence_id
                    or event.intake_status != command.values.intake_status
                    or event.idempotency_key != command.values.idempotency_key
                    or event.ingestion_proven is not False
                    or event.visual_status.value != "not_checked"
                ):
                    raise ValueError
            else:
                if (
                    receipt.business_ref != BusinessRef(kind="late_report", id=native.id, version=native.version)
                    or native.patient_id != owner
                    or native.occurrence_id != command.occurrence_id
                    or any(
                        getattr(native, name) != getattr(command.values, name)
                        for name in type(command.values).model_fields
                    )
                    or native.ingestion_proven is not False
                    or native.visual_status != "not_checked"
                ):
                    raise ValueError
            return result
        except (ValueError, TypeError, AttributeError):
            raise ProviderUnavailableError("Record result binding unavailable; inspect its native receipt") from None
