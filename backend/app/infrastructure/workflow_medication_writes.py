"""Coupled native memory transactions. Patient SQL composition is separately gated."""

import hashlib
import json
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from uuid import UUID, uuid5

from ..application.enrollment_operations import EnrollmentOperationService
from ..application.evidence_enrollment import EvidenceEnrollmentService
from ..application.source_operations import SourceEnrollmentOperationService
from ..contracts.assistant_workflows import (
    ActionReceipt,
    AttachmentRef,
    BusinessRef,
    CapabilityAdapter,
    WorkflowContext,
    WorkflowUpdate,
    validate_workflow_values,
)
from ..contracts.draft_deletion import LocalDraftDeletionMetadataPort
from ..contracts.dto import ActivationResultDTO
from ..contracts.enums import SourceKind
from ..contracts.medication_evidence import LocalEvidenceEnrollmentWritePort
from ..contracts.workflow_medication_writes import (
    MEDICATION_WRITE_COMMAND,
    MedicationNativeResult,
    MedicationWritePreparationPort,
    MedicationWriteRequest,
    PrepareMedication,
)
from ..contracts.workflow_persistence import BusinessWriteReceipt, NativeWriteResult, WorkflowWriteBinding
from ..domain.errors import (
    DuplicateEventError,
    NotFoundError,
    ProviderUnavailableError,
    StaleVersionError,
    ValidationError,
)


def command_digest(command):
    encoded = json.dumps(command.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


class MemoryMedicationWorkflowWrites:
    def __init__(
        self,
        *,
        state,
        store,
        clock,
        tasks,
        controls,
        originals,
        enrollment,
        enrollments,
        operations: EnrollmentOperationService,
        deletions: LocalDraftDeletionMetadataPort,
        source_operations: SourceEnrollmentOperationService,
        source_transactions: LocalEvidenceEnrollmentWritePort,
        evidence: EvidenceEnrollmentService,
        source_adapter: CapabilityAdapter,
    ):
        self._state, self._store, self._clock = state, store, clock
        self._tasks, self._controls, self._originals = tasks, controls, originals
        self._enrollment, self._enrollments = enrollment, enrollments
        self._operations, self._deletions = operations, deletions
        self._source_operations, self._source_transactions, self._evidence = (
            source_operations,
            source_transactions,
            evidence,
        )
        self._source_adapter = source_adapter

    def revision(self, owner):
        return self._enrollments.revision(owner)

    def lookup(self, owner, action_key):
        with self._state.lock:
            return self._state.business_receipts.get((owner, action_key))

    def for_attachment(self, owner, attachment_id):
        return self._enrollments.for_attachment(owner, attachment_id)

    def apply(self, owner, command):
        command = MEDICATION_WRITE_COMMAND.validate_python(command.model_dump())
        if command.kind == "prepare_maintenance":
            return self._prepare_maintenance(owner, command)
        if command.kind in {"prepare_source", "save_source", "review_registration"}:
            return self._apply_source(owner, command)
        if command.kind != "prepare":
            return self._apply_native(owner, command)
        digest = command_digest(command)
        binding = command.binding
        key = (owner, binding.action_key)
        # Memory reproduces transaction semantics only. All readers of these
        # clinical rows share the existing clinical lock; owner lock comes first.
        with self._state.lock, self._store.clinical.lock:
            prior = self.lookup(owner, binding.action_key)
            if prior is not None:
                if self._state.medication_commands.get(key) != digest:
                    raise DuplicateEventError("Action key already belongs to different medication inputs")
                native = self._enrollments.lookup(owner, binding.action_key)
                if native is None:
                    raise StaleVersionError("The native preparation receipt is unavailable")
                return NativeWriteResult(receipt=prior, result=native)
            task = self._tasks.get(owner, binding.task_id)
            control = self._controls.get(owner, binding.task_id)
            if (
                task.revision != binding.task_revision
                or control.revision != binding.task_revision
                or task.capability_id != binding.capability_id
                or control.mode != "allowed"
                or control.revoked
                or control.status != "idle"
                or task.state != "ready_for_review"
                or self.revision(owner) != binding.expected_domain_revision
            ):
                raise StaleVersionError("The current medication review or records changed")
            if binding.run_binding is not None:
                self._state.require_durable_run(owner, binding.run_binding, self._clock.now())
            prepared = command.prepared
            ref = BusinessRef(kind="regimen", id=prepared.result.regimen.id, version=prepared.result.regimen.version_no)
            if (
                prepared.workflow_task_id != task.id
                or prepared.workflow_revision != task.revision
                or prepared.result.regimen.patient_id != owner
                or binding.prepared_ref != ref
                or task.capability_id
                not in {
                    "medication.enroll",
                    "medication.plan.change",
                    "medication.draft.resume",
                    "medication.source.add",
                    "medication.source.review",
                }
            ):
                raise ValidationError("Prepared medication is not bound to this owned review")
            for attachment_id in prepared.attachment_ids:
                self._state.require_original_reference(owner, attachment_id)
                original = self._originals.get(owner, task.id, attachment_id)
                if (
                    attachment_id not in task.attachment_ids
                    or original.state != "saved"
                    or not original.object_written
                    or original.extraction_status != "succeeded"
                    or original.extraction is None
                    or original.extraction.source_kind != prepared.source.source_kind.value
                ):
                    raise ValidationError("The original source has not been verified for this preparation")
                index = prepared.source_candidate_index
                if (
                    index is None
                    or index >= len(original.extraction.candidates)
                    or prepared.source.extraction_evidence
                    != original.extraction.model_copy(update={"candidates": [original.extraction.candidates[index]]})
                ):
                    raise ValidationError("Prepared provenance differs from the selected original extraction")
                if not any(
                    proof.result == "bytes_verified"
                    and (ticket := self._state.storage_tickets.get(proof.ticket_id)) is not None
                    and ticket.owner == owner
                    and ticket.value.task_id == task.id
                    and ticket.value.attachment_id == attachment_id
                    and ticket.value.expected_checksum == original.original_checksum
                    for proof in self._state.storage_verifications.values()
                ):
                    raise ValidationError("The original needs an independently verified byte proof")
            self._validate_prepared_inputs(owner, task, prepared)
            # Explicitly snapshot owned infrastructure state; no application
            # component reaches into another component's private repository.
            tables = (self._store.sources, self._store.source_fields, self._store.medications, self._store.regimens)
            snapshots = [deepcopy(table.rows) for table in tables]
            dictionaries = (
                self._store.enrollment_operations,
                self._store.clinical.revisions,
                self._state.tasks,
                self._state.controls,
                self._state.events,
                self._state.originals,
                self._state.business_receipts,
                self._state.medication_commands,
            )
            backups = [deepcopy(value) for value in dictionaries]
            used = set(self._state.used)
            try:
                native = self._enrollments.create_once(
                    owner,
                    binding.action_key,
                    command.binding_digest,
                    prepared,
                    expected_revision=binding.expected_domain_revision,
                )
                for attachment_id in prepared.attachment_ids:
                    row = self._originals.get(owner, task.id, attachment_id)
                    if row.source_ref is None:
                        self._state.originals[(owner, attachment_id)] = row.model_copy(
                            update={"source_ref": BusinessRef(kind="source", id=prepared.source.id)}
                        )
                if binding.run_binding is not None:
                    self._state.require_durable_run(owner, binding.run_binding, self._clock.now())
                self._tasks.cas(
                    owner,
                    task.id,
                    task.revision,
                    binding.action_key,
                    WorkflowUpdate(
                        state="awaiting_confirmation",
                        save_mode="allowed",
                        storage_state="saved",
                        fields=task.fields,
                        missing_fields=(),
                        attachment_ids=task.attachment_ids,
                        business_refs=(ref,),
                    ),
                )
                if binding.run_binding is not None:
                    self._state.require_durable_run(owner, binding.run_binding, self._clock.now())
                receipt = BusinessWriteReceipt(
                    owner=owner,
                    task_id=task.id,
                    action_key=binding.action_key,
                    capability_id=task.capability_id,
                    binding_revision=task.revision + 1,
                    business_ref=ref,
                    domain_revision=self.revision(owner),
                    outcome="prepared",
                    recorded_at=self._clock.now(),
                )
                self._state.business_receipts[key] = receipt
                self._state.medication_commands[key] = digest
                return NativeWriteResult(receipt=receipt, result=native)
            except BaseException:
                for table, snapshot in zip(tables, snapshots, strict=True):
                    table.rows = snapshot
                # create_once replaces its publication dictionary; restore its
                # public store attribute as well as preserving other dictionary identities.
                self._store.enrollment_operations = backups[0]
                for value, backup in zip(dictionaries[1:], backups[1:], strict=True):
                    value.clear()
                    value.update(backup)
                self._state.used.clear()
                self._state.used.update(used)
                raise

    def _prepare_maintenance(self, owner, command):
        b, digest = command.binding, command_digest(command)
        with self._state.lock, self._store.clinical.lock:
            prior = self.lookup(owner, b.action_key)
            if prior is not None:
                if self._state.medication_commands.get((owner, b.action_key)) != digest:
                    raise DuplicateEventError("Maintenance preparation differs from its original event")
                return NativeWriteResult(receipt=prior, result=None)
            task, control = self._tasks.get(owner, b.task_id), self._controls.get(owner, b.task_id)
            if (
                task.capability_id not in {"medication.plan.end", "medication.draft.delete"}
                or task.capability_id != b.capability_id
                or task.revision != b.task_revision
                or control.revision != b.task_revision
                or task.state != "ready_for_review"
                or task.save_mode != "allowed"
                or control.mode != "allowed"
                or control.revoked
                or control.status != "idle"
                or task.business_refs
                or task.attachment_ids
                or self.revision(owner) != b.expected_domain_revision
            ):
                raise StaleVersionError("Current independently reviewed maintenance target changed")
            f = validate_workflow_values(task.capability_id, task.fields)
            if task.capability_id == "medication.plan.end":
                row = self._enrollment.get_regimen(owner, f.regimen_id)
                if row is None or row.version_no != f.expected_version or row.state.value != "active":
                    raise StaleVersionError("Choose the current active plan")
                ref = BusinessRef(kind="regimen", id=row.id, version=row.version_no)
            else:
                version = self._deletions.current_version(owner, f.kind, f.target_id)
                if version != f.expected_version:
                    raise StaleVersionError("Selected unfinished draft changed")
                ref = BusinessRef(
                    kind="regimen" if f.kind == "draft" else "enrollment_task", id=f.target_id, version=version
                )
            if ref != b.prepared_ref:
                raise StaleVersionError("Maintenance target differs from saved draft")
            if b.run_binding is not None:
                self._state.require_durable_run(owner, b.run_binding, self._clock.now())
            with self._native_transaction():
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
                        attachment_ids=(),
                        missing_fields=(),
                        business_refs=(ref,),
                    ),
                    request_digest=digest,
                )
                if b.run_binding is not None:
                    self._state.require_durable_run(owner, b.run_binding, self._clock.now())
                self._state.actions[owner, b.action_key] = ActionReceipt(
                    owner=owner,
                    task_id=task.id,
                    capability_id=task.capability_id,
                    action_key=b.action_key,
                    binding_revision=task.revision + 1,
                    state="succeeded",
                    business_ref=ref,
                    clinical_revision=self.revision(owner),
                    updated_at=self._clock.now(),
                )
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
                self._state.medication_commands[owner, b.action_key] = digest
                self._state.business_receipts[owner, b.action_key] = receipt
                return NativeWriteResult(receipt=receipt, result=None)

    @contextmanager
    def _native_transaction(self):
        tables = [
            getattr(self._store, name)
            for name in (
                "sources",
                "source_fields",
                "medications",
                "regimens",
                "dose_rules",
                "occurrences",
                "challenges",
            )
        ]
        snapshots = [deepcopy(table.rows) for table in tables]
        values = [
            getattr(self._state, name)
            for name in (
                "tasks",
                "controls",
                "actions",
                "events",
                "originals",
                "business_receipts",
                "medication_commands",
                "medication_result_refs",
            )
        ]
        values.extend([self._store.clinical.revisions, self._store.sessions])
        backups, used = [deepcopy(value) for value in values], set(self._state.used)
        enrollment_rows = self._store.enrollment_operations
        enrollment_backup = deepcopy(enrollment_rows)
        try:
            yield
        except BaseException:
            for table, snapshot in zip(tables, snapshots, strict=True):
                table.rows = snapshot
            for value, backup in zip(values, backups, strict=True):
                value.clear()
                value.update(backup)
            self._state.used.clear()
            self._state.used.update(used)
            enrollment_rows.clear()
            enrollment_rows.update(enrollment_backup)
            self._store.enrollment_operations = enrollment_rows
            raise

    def _validate_prepared_inputs(self, owner, task, prepared):
        """A prepared DTO cannot replace the dose/source fields shown in the saved task."""
        if task.capability_id != "medication.enroll":
            # Other native command branches validate their own target/version.
            # A source review cannot be smuggled through the enrollment command.
            if task.capability_id not in {"medication.plan.change", "medication.draft.resume"}:
                raise ValidationError("Use the independent native source review transaction")
            if task.capability_id == "medication.draft.resume":
                if (
                    not prepared.already_persisted
                    or task.fields.get("regimen_id") != str(prepared.result.regimen.id)
                    or task.fields.get("expected_version") != prepared.result.regimen.version_no
                ):
                    raise StaleVersionError("The selected native draft changed")
                return
            values = validate_workflow_values(task.capability_id, task.fields)
            preview = self._operations.plan_change_preview(
                owner, values.regimen_id, values.expected_version, values.expected_state, values.details
            )
            if preview.preview.normalized_draft is None:
                raise ValidationError("Complete the changed instructions")
            draft = preview.preview.normalized_draft.model_copy(
                update={
                    "patient_edited": True,
                    "supersedes_regimen_id": preview.target.id if preview.target.state.value == "active" else None,
                }
            )
            selected, dose_basis = preview.target.patient_medication_id, None
        else:
            values = validate_workflow_values(task.capability_id, task.fields)
            if (
                values.draft is None
                or prepared.result.regimen.evidence_task_id is not None
                or prepared.already_persisted
            ):
                raise ValidationError("Complete the current enrollment inputs")
            if values.method == "manual":
                if (
                    prepared.attachment_ids
                    or prepared.source.extraction_evidence is not None
                    or prepared.source.source_kind != SourceKind.USER_MANUAL
                ):
                    raise ValidationError("Manual enrollment cannot claim photo provenance")
            else:
                if (
                    len(prepared.attachment_ids) != 1
                    or values.source_attachment_id != prepared.attachment_ids[0]
                    or values.source_candidate_index != prepared.source_candidate_index
                ):
                    raise ValidationError("The selected original product changed")
                row = self._originals.get(owner, task.id, prepared.attachment_ids[0])
                EvidenceEnrollmentService.validate_workflow_fields(row.extraction, values)
            draft, selected, dose_basis = values.draft, values.existing_medication_id, values.dose_basis
        if selected is not None:
            medication = self._enrollment.get_medication(owner, selected)
            if medication is None or prepared.result.medication.id != selected:
                raise StaleVersionError("The selected medication changed")
            draft = draft.model_copy(update={"medication_name": medication.display_name})
        expected = self._enrollment.prepare_draft(
            patient_id=owner,
            draft=draft,
            existing_medication_id=selected,
            dose_basis=dose_basis,
            source_kind=prepared.source.source_kind,
            extraction_evidence=prepared.source.extraction_evidence,
        )
        actual, target = prepared.result.regimen, expected.result.regimen
        comparable = (
            "version_no",
            "dose_amount",
            "dose_unit",
            "frequency_rule",
            "is_prn",
            "route",
            "food_instruction",
            "course_start_date",
            "course_end_date",
            "patient_edited",
            "supersedes_id",
            "evidence_task_id",
        )
        if (
            any(getattr(actual, name) != getattr(target, name) for name in comparable)
            or actual.effective_from is not None
            or actual.effective_to is not None
            or actual.confirmation_challenge_id is not None
            or prepared.create_medication != expected.create_medication
            or prepared.result.medication.display_name != expected.result.medication.display_name
            or prepared.source.dose_basis != expected.source.dose_basis
        ):
            raise ValidationError("Prepared medication differs from the current saved patient inputs")
        fields = {field.field_name: field.field_value for field in prepared.result.source_fields}
        wanted = {field.field_name: field.field_value for field in expected.result.source_fields}
        if (
            len(fields) != len(prepared.result.source_fields)
            or not self._same_source_values(fields, wanted)
            or any(
                field.review_status.value != "extracted" or field.reviewed_at is not None
                for field in prepared.result.source_fields
            )
        ):
            raise ValidationError("Prepared source fields differ from the current saved patient inputs")

    @classmethod
    def _same_source_values(cls, actual, expected):
        if isinstance(expected, bool):
            return type(actual) is bool and actual == expected
        if isinstance(expected, (int, float)):
            return type(actual) in {int, float} and actual == expected
        if isinstance(expected, dict):
            return (
                isinstance(actual, dict)
                and actual.keys() == expected.keys()
                and all(cls._same_source_values(actual[key], value) for key, value in expected.items())
            )
        if isinstance(expected, list):
            return (
                isinstance(actual, list)
                and len(actual) == len(expected)
                and all(cls._same_source_values(a, b) for a, b in zip(actual, expected, strict=True))
            )
        return type(actual) is type(expected) and actual == expected

    def _native_result(self, owner, command, receipt):
        if command.kind in {"prepare_source", "review_identity"}:
            return NativeWriteResult(receipt=receipt, result=None)
        native_id = self._state.medication_result_refs.get((owner, receipt.action_key))
        if command.kind in {"save_source", "review_registration"}:
            result = self._evidence.get(owner, native_id)
        elif command.kind == "review_source":
            result = self._enrollment.get_source(owner, native_id)
        elif command.kind == "request_challenge":
            result = self._store.challenges.get((owner, native_id))
        elif command.kind in {"end_plan", "change_plan"}:
            result = self._enrollment.get_regimen(owner, native_id)
        elif command.kind == "delete_draft":
            result = self._deletions.receipt(owner, command.draft_kind, native_id)
        else:
            regimen = self._enrollment.get_regimen(owner, native_id)
            if regimen is None or regimen.state.value != "active":
                raise StaleVersionError("The applied plan changed; inspect its native history and receipt")
            result = ActivationResultDTO(
                regimen=regimen, superseded_regimen_ids=[regimen.supersedes_id] if regimen.supersedes_id else []
            )
        if result is None:
            raise ProviderUnavailableError("The applied native record is unavailable; inspect its receipt")
        return NativeWriteResult(receipt=receipt, result=result)

    def _apply_native(self, owner, command):
        binding = command.binding
        key = (owner, binding.action_key)
        digest = command_digest(command)
        with self._state.lock, self._store.clinical.lock:
            prior = self.lookup(owner, binding.action_key)
            if prior is not None:
                if self._state.medication_commands.get(key) != digest:
                    raise DuplicateEventError("Action key already belongs to different medication inputs")
                return self._native_result(owner, command, prior)
            task = self._tasks.get(owner, binding.task_id)
            control = self._controls.get(owner, binding.task_id)
            changing, deleting = command.kind == "change_plan", command.kind == "delete_draft"
            if (
                task.revision != binding.task_revision
                or control.revision != binding.task_revision
                or task.capability_id != binding.capability_id
                or control.mode != "allowed"
                or control.revoked
                or control.status != "idle"
                or task.state != ("ready_for_review" if changing else "awaiting_confirmation")
                or (not changing and binding.prepared_ref not in task.business_refs)
                or self.revision(owner) != binding.expected_domain_revision
            ):
                raise StaleVersionError("The current medication review or records changed")
            if binding.run_binding is not None:
                self._state.require_durable_run(owner, binding.run_binding, self._clock.now())
            permitted = (
                {"medication.draft.delete"}
                if deleting
                else {"medication.plan.end"}
                if command.kind == "end_plan"
                else {"medication.plan.change"}
                if changing
                else {
                    "medication.enroll",
                    "medication.plan.change",
                    "medication.draft.resume",
                    "medication.source.add",
                    "medication.source.review",
                }
            )
            if task.capability_id not in permitted:
                raise ValidationError("This capability cannot review or activate a medication")
            ref = binding.prepared_ref
            regimen = None
            if deleting:
                expected_kind = "regimen" if command.draft_kind == "draft" else "enrollment_task"
                if (
                    ref.kind != expected_kind
                    or self._deletions.current_version(owner, command.draft_kind, ref.id) != ref.version
                ):
                    raise StaleVersionError("The owned unfinished registration changed")
            else:
                regimen = self._enrollment.get_regimen(owner, ref.id) if ref.kind == "regimen" else None
                if regimen is None or regimen.version_no != ref.version:
                    raise StaleVersionError("The owned prepared plan changed")
            with self._native_transaction(), self._deletions.local_transaction() if deleting else nullcontext():
                advance = True
                result_ref = ref
                if deleting:
                    deletion = self._deletions.delete_metadata(owner, command.draft_kind, ref.id)
                    native_id = ref.id
                elif changing:
                    values = command.values
                    if (
                        values.action_key != binding.action_key
                        or values.workflow_task_id != task.id
                        or values.workflow_revision != task.revision
                        or values.predecessor_id != regimen.id
                        or values.expected_version != regimen.version_no
                        or task.fields.get("regimen_id") != str(regimen.id)
                        or task.fields.get("expected_version") != regimen.version_no
                        or task.fields.get("expected_state") != values.expected_state
                        or task.fields.get("details") != values.fields.model_dump(mode="json")
                    ):
                        raise StaleVersionError("The changed instructions differ from the current saved review")
                    result = self._operations.prepare_plan_change_once(owner, values)
                    native_id = result.regimen.id
                    result_ref = BusinessRef(kind="regimen", id=native_id, version=result.regimen.version_no)
                elif command.kind == "end_plan":
                    self._enrollment.end_regimen(patient_id=owner, regimen_id=regimen.id)
                    native_id = regimen.id
                elif command.kind == "review_identity":
                    self._enrollment.review_original_identity(owner, regimen.id)
                    native_id = regimen.id
                elif command.kind == "review_source":
                    if command.source_id != regimen.source_id:
                        raise ValidationError("This source does not belong to the prepared plan")
                    self._enrollment.review_source_fields(
                        patient_id=owner,
                        source_id=command.source_id,
                        field_ids=list(command.field_ids) if command.field_ids is not None else None,
                    )
                    native_id = command.source_id
                elif command.kind == "request_challenge":
                    session = self._store.sessions.get((owner, command.session_id))
                    if (
                        session is None
                        or session.state != "awaiting_confirmation"
                        or session.state_version != command.session_state_version
                        or session.expires_at <= self._clock.now()
                    ):
                        raise StaleVersionError("The independent confirmation session changed or expired")
                    challenge, _token = self._enrollment.request_activation_challenge(
                        patient_id=owner,
                        regimen_id=regimen.id,
                        session_id=session.id,
                        session_state_version=session.state_version,
                    )
                    native_id, advance = challenge.id, False
                else:
                    challenge = self._store.challenges.get((owner, command.challenge_id))
                    session = self._store.sessions.get((owner, challenge.session_id)) if challenge is not None else None
                    if (
                        session is None
                        or challenge.regimen_id != regimen.id
                        or session.state != "awaiting_confirmation"
                        or challenge.session_state_version != command.session_state_version
                        or session.state_version != command.session_state_version
                        or session.expires_at <= self._clock.now()
                    ):
                        raise StaleVersionError("The independent confirmation session changed or expired")
                    self._enrollment.confirm_challenge(patient_id=owner, challenge_id=challenge.id)
                    self._enrollment.activate_regimen(
                        patient_id=owner,
                        regimen_id=regimen.id,
                        challenge_id=challenge.id,
                        session_state=session.state,
                        session_state_version=session.state_version,
                    )
                    native_id = regimen.id
                if binding.run_binding is not None:
                    self._state.require_durable_run(owner, binding.run_binding, self._clock.now())
                if advance:
                    self._tasks.cas(
                        owner,
                        task.id,
                        task.revision,
                        binding.action_key,
                        WorkflowUpdate(
                            state="outcome_unknown"
                            if deleting and deletion.cleanup_pending
                            else "completed"
                            if command.kind in {"activate", "end_plan", "delete_draft"}
                            else "awaiting_confirmation",
                            save_mode="allowed",
                            storage_state="cleanup_pending" if deleting and deletion.cleanup_pending else "saved",
                            fields=task.fields,
                            missing_fields=(),
                            attachment_ids=task.attachment_ids,
                            business_refs=(result_ref,),
                        ),
                    )
                if binding.run_binding is not None:
                    self._state.require_durable_run(owner, binding.run_binding, self._clock.now())
                receipt = BusinessWriteReceipt(
                    owner=owner,
                    task_id=task.id,
                    action_key=binding.action_key,
                    capability_id=task.capability_id,
                    binding_revision=task.revision + int(advance),
                    business_ref=result_ref,
                    domain_revision=self.revision(owner),
                    outcome="applied" if command.kind in {"activate", "end_plan", "delete_draft"} else "prepared",
                    recorded_at=self._clock.now(),
                )
                self._state.business_receipts[key] = receipt
                self._state.medication_commands[key] = digest
                self._state.medication_result_refs[key] = native_id
                return self._native_result(owner, command, receipt)

    def _apply_source(self, owner, command):
        binding, preparing = command.binding, command.kind == "prepare_source"
        digest = command_digest(command)
        key = (owner, binding.action_key)
        with self._state.lock, self._store.clinical.lock:
            prior = self.lookup(owner, binding.action_key)
            if prior is not None:
                if self._state.medication_commands.get(key) != digest:
                    raise DuplicateEventError("This source action belongs to different inputs")
                return self._native_result(owner, command, prior)
            task, control = self._tasks.get(owner, binding.task_id), self._controls.get(owner, binding.task_id)
            states = {"ready_for_review", "collecting"} if preparing else {"awaiting_confirmation"}
            if (
                preparing
                and task.capability_id == "medication.source.add"
                and len(task.business_refs) == 1
                and task.business_refs[0].kind == "media_review"
                and task.business_refs[0].id == task.id
                and task.business_refs[0].version is not None
                and task.business_refs[0].version < task.revision
            ):
                states.add("awaiting_confirmation")
            if (
                task.revision != binding.task_revision
                or control.revision != binding.task_revision
                or task.capability_id != binding.capability_id
                or control.mode != "allowed"
                or control.revoked
                or control.status != "idle"
                or self.revision(owner) != binding.expected_domain_revision
                or task.state not in states
                or task.capability_id
                not in (
                    {"medication.source.add", "medication.source.review"}
                    if preparing or command.kind == "review_registration"
                    else {"medication.source.add"}
                )
            ):
                raise StaleVersionError("The current source review changed")
            if binding.run_binding is not None:
                self._state.require_durable_run(owner, binding.run_binding, self._clock.now())
            ref, native_id = binding.prepared_ref, None
            with self._native_transaction(), self._source_transactions.local_transaction():
                if preparing:
                    context = WorkflowContext(
                        owner=owner, task_id=task.id, revision=task.revision, capability_id=task.capability_id
                    )
                    assets = tuple(
                        AttachmentRef(
                            id=row.id,
                            task_id=task.id,
                            original_checksum=row.original_checksum,
                            content_type=row.content_type,
                            extraction_status=row.extraction_status,
                        )
                        for row in self._originals.list(owner, task.id)
                        if row.id in task.attachment_ids and row.state == "saved"
                    )
                    proposal = self._source_adapter.prepare(
                        context, validate_workflow_values(task.capability_id, task.fields), assets
                    )
                    if proposal.workflow_state != "ready_for_review":
                        raise ValidationError("Complete the current source inputs before preparing review")
                    existing = task.fields.get("source_task_id")
                    if existing is not None:
                        actual = self._evidence.get(owner, UUID(existing))
                        expected = BusinessRef(kind="enrollment_task", id=actual.id, version=actual.version)
                        if task.fields.get("expected_version") != actual.version:
                            raise StaleVersionError("The selected source registration changed")
                    else:
                        if task.capability_id != "medication.source.add" or not task.attachment_ids:
                            raise ValidationError("Choose an owned saved source original")
                        expected = BusinessRef(kind="media_review", id=task.id, version=task.revision + 1)
                    if ref != expected:
                        raise ValidationError("The source preparation marker is not bound to this task")
                elif command.kind == "review_registration":
                    if ref.kind != "enrollment_task" or ref not in task.business_refs:
                        raise StaleVersionError("The current source registration reference changed")
                    actual = self._evidence.get(owner, ref.id)
                    if actual.version != ref.version:
                        raise StaleVersionError("The native source review changed")
                    context = WorkflowContext(
                        owner=owner, task_id=task.id, revision=task.revision, capability_id=task.capability_id
                    )
                    actual = self._source_operations.review(
                        context,
                        ref.id,
                        draft=command.draft,
                        patient_reviewed=command.confirmed,
                        distinct_product_confirmed=command.distinct_product_confirmed,
                        product_category=command.product_category,
                        replace_active_plan=command.replace_active_plan,
                    )
                    native = self._enrollments.for_regimen(owner, actual.draft_regimen_id)
                    if native is None or native.workflow_task_id != task.id:
                        raise StaleVersionError("The reviewed draft has no current owned native binding")
                    native_id = actual.id
                    ref = BusinessRef(kind="regimen", id=native.regimen_id, version=native.version_no)
                else:
                    if ref not in task.business_refs:
                        raise StaleVersionError("The current source preparation changed")
                    if ref.kind == "media_review":
                        if ref.id != task.id or ref.version != task.revision:
                            raise StaleVersionError("The source preparation marker changed")
                        target = uuid5(task.id, "source-registration")
                    elif ref.kind == "enrollment_task":
                        target = ref.id
                    else:
                        raise ValidationError("This source cannot accept an original")
                    self._state.require_original_reference(owner, command.attachment_id)
                    original = self._originals.get(owner, task.id, command.attachment_id)
                    if command.attachment_id not in task.attachment_ids or not any(
                        proof.result == "bytes_verified"
                        and (ticket := self._state.storage_tickets.get(proof.ticket_id)) is not None
                        and ticket.owner == owner
                        and ticket.value.attachment_id == original.id
                        and ticket.value.expected_checksum == original.original_checksum
                        for proof in self._state.storage_verifications.values()
                    ):
                        raise ValidationError("This source original has no independently verified byte proof")
                    context = WorkflowContext(
                        owner=owner, task_id=task.id, revision=task.revision, capability_id=task.capability_id
                    )
                    actual = self._source_operations.save(context, target, command.attachment_id, binding.action_key)
                    protected = self._source_transactions.original_sources(owner, original.id)
                    if len(protected) != 1:
                        raise StaleVersionError("The source protection receipt is unresolved")
                    if original.source_ref is not None and original.source_ref.id != protected[0]:
                        raise ValidationError("A formal source association cannot be replaced")
                    self._state.originals[(owner, original.id)] = original.model_copy(
                        update={"source_ref": BusinessRef(kind="source", id=protected[0])}
                    )
                    native_id = actual.id
                    ref = BusinessRef(kind="enrollment_task", id=actual.id, version=actual.version)
                if binding.run_binding is not None:
                    self._state.require_durable_run(owner, binding.run_binding, self._clock.now())
                self._tasks.cas(
                    owner,
                    task.id,
                    task.revision,
                    binding.action_key,
                    WorkflowUpdate(
                        state="awaiting_confirmation",
                        save_mode="allowed",
                        storage_state="saved",
                        fields=task.fields,
                        missing_fields=(),
                        attachment_ids=task.attachment_ids,
                        business_refs=(ref,),
                    ),
                )
                if binding.run_binding is not None:
                    self._state.require_durable_run(owner, binding.run_binding, self._clock.now())
                receipt = BusinessWriteReceipt(
                    owner=owner,
                    task_id=task.id,
                    action_key=binding.action_key,
                    capability_id=task.capability_id,
                    binding_revision=task.revision + 1,
                    business_ref=ref,
                    domain_revision=self.revision(owner),
                    outcome="prepared" if preparing or command.kind == "review_registration" else "applied",
                    recorded_at=self._clock.now(),
                )
                self._state.business_receipts[key] = receipt
                self._state.medication_commands[key] = digest
                if native_id is not None:
                    self._state.medication_result_refs[key] = native_id
                return self._native_result(owner, command, receipt)


class CoupledEnrollmentWritePort:
    """Compatibility facade over public ports; never a Python transaction fallback."""

    def __init__(self, *, native, writes, tasks):
        self._native, self._writes, self._tasks = native, writes, tasks

    def revision(self, owner):
        return self._writes.revision(owner)

    def lookup(self, owner, action_key):
        return self._native.lookup(owner, action_key)

    def for_regimen(self, owner, regimen_id):
        return self._native.for_regimen(owner, regimen_id)

    def for_attachment(self, owner, attachment_id):
        return self._writes.for_attachment(owner, attachment_id)

    def create_once(self, owner, action_key, binding_digest, prepared, *, expected_revision):
        if prepared.workflow_task_id is None:
            return self._native.create_once(
                owner, action_key, binding_digest, prepared, expected_revision=expected_revision
            )
        from ..contracts.agent_execution import current_execution

        execution = current_execution.get()
        if execution is not None:
            execution.check()
            if getattr(execution, "write_binding", None) is None:
                raise ProviderUnavailableError("A durable run binding is required")
        # This owned read selects the command's capability only. The transaction
        # rechecks task/control/revision/capability before any native write.
        task = self._tasks.get(owner, prepared.workflow_task_id)
        result = self._writes.apply(
            owner,
            PrepareMedication(
                prepared=prepared,
                binding_digest=binding_digest,
                binding=WorkflowWriteBinding(
                    task_id=prepared.workflow_task_id,
                    task_revision=prepared.workflow_revision,
                    capability_id=task.capability_id,
                    action_key=action_key,
                    prepared_ref=BusinessRef(
                        kind="regimen", id=prepared.result.regimen.id, version=prepared.result.regimen.version_no
                    ),
                    expected_domain_revision=expected_revision,
                    run_binding=execution.write_binding if execution is not None else None,
                ),
            ),
        )
        return result.result


class SupabaseMedicationWorkflowWrites:
    """One fixed patient RPC; no callback, direct table writes, or implicit mutation retry."""

    def __init__(self, *, data, reads, receipts, preparations: MedicationWritePreparationPort | None = None):
        self._data, self._reads, self._receipts, self._preparations = data, reads, receipts, preparations

    def revision(self, owner):
        self._data.check_patient(owner)
        return self._reads.revision(owner)

    def lookup(self, owner, action_key):
        self._data.check_patient(owner)
        return self._receipts.read_receipt(owner, action_key)

    def for_attachment(self, owner, attachment_id):
        self._data.check_patient(owner)
        rows = self._data.rows(
            "assistant_enrollment_originals", owner=f"eq.{owner}", attachment_id=f"eq.{attachment_id}", limit="2"
        )
        if not rows:
            return None
        if len(rows) != 1 or rows[0].get("owner") != str(owner) or rows[0].get("attachment_id") != str(attachment_id):
            raise ProviderUnavailableError("Original enrollment binding unavailable")
        try:
            receipt = self._reads.lookup(owner, UUID(rows[0]["action_key"]))
            if receipt is None or attachment_id not in receipt.attachment_ids:
                raise ValueError
            return receipt
        except (ValueError, KeyError, TypeError):
            raise ProviderUnavailableError("Original enrollment binding unavailable") from None

    def apply(self, owner, command):
        self._data.check_patient(owner)
        command = MEDICATION_WRITE_COMMAND.validate_python(command.model_dump())
        derived = command.kind in {"change_plan", "save_source", "review_registration"}
        prior = self.lookup(owner, command.binding.action_key) if derived else None
        request = None
        if prior is not None:
            raw = self._data.request(
                "POST", "/rest/v1/rpc/assistant_medication_read", body={"p_command": command.model_dump(mode="json")}
            )
        else:
            if self._preparations is None:
                if derived:
                    raise ProviderUnavailableError("Verified native medication preparation is unavailable")
                request = MedicationWriteRequest(command=command)
            else:
                request = self._preparations.prepare(owner, command)
                if request.command != command:
                    raise ProviderUnavailableError("Native medication preparation binding changed")
            raw = self._data.request(
                "POST", "/rest/v1/rpc/assistant_medication_write", body={"p_request": request.model_dump(mode="json")}
            )
        if (
            not isinstance(raw, dict)
            or set(raw) not in ({"result"}, {"result", "replayed"}, {"error"})
            or ("replayed" in raw and type(raw["replayed"]) is not bool)
        ):
            raise ProviderUnavailableError("Medication write outcome unavailable; inspect its receipt")
        if "error" in raw:
            errors = {
                "not_found": NotFoundError,
                "stale": StaleVersionError,
                "duplicate": DuplicateEventError,
                "invalid": ValidationError,
            }
            code = raw["error"] if isinstance(raw["error"], str) else "unavailable"
            raise errors.get(code, ProviderUnavailableError)("Medication write changed; inspect its current receipt")
        try:
            replayed = raw.get("replayed", False)
            result = NativeWriteResult[MedicationNativeResult].model_validate(raw["result"])
            receipt, binding = result.receipt, command.binding
            if prior is not None and (not replayed or receipt != prior):
                raise ValueError
            revision = binding.task_revision + int(command.kind != "request_challenge")
            outcome = (
                "applied" if command.kind in {"activate", "end_plan", "delete_draft", "save_source"} else "prepared"
            )
            if (
                receipt.owner != owner
                or receipt.task_id != binding.task_id
                or receipt.action_key != binding.action_key
                or receipt.capability_id != binding.capability_id
                or receipt.binding_revision != revision
                or receipt.outcome != outcome
                or receipt.domain_revision < binding.expected_domain_revision
            ):
                raise ValueError
            native = result.result
            if command.kind == "prepare":
                if (
                    native.regimen_id != command.prepared.result.regimen.id
                    or native.medication_id != command.prepared.result.medication.id
                    or native.source_id != command.prepared.source.id
                    or native.workflow_task_id != binding.task_id
                    or native.binding_digest != command.binding_digest
                    or native.version_no != command.prepared.result.regimen.version_no
                    or native.attachment_ids != command.prepared.attachment_ids
                    or native.source_candidate_index != command.prepared.source_candidate_index
                ):
                    raise ValueError
            elif command.kind in {"prepare_source", "prepare_maintenance", "review_identity"}:
                if native is not None:
                    raise ValueError
            elif command.kind == "request_challenge":
                if (
                    native.patient_id != owner
                    or native.session_id != command.session_id
                    or native.session_state_version != command.session_state_version
                    or native.regimen_id != binding.prepared_ref.id
                    or native.action != "activate_regimen"
                ):
                    raise ValueError
            elif command.kind == "activate":
                if native.regimen.patient_id != owner or native.regimen.id != binding.prepared_ref.id:
                    raise ValueError
            elif command.kind in {"change_plan", "end_plan"}:
                if native.patient_id != owner or native.id != receipt.business_ref.id:
                    raise ValueError
                if (
                    command.kind == "change_plan"
                    and not replayed
                    and (
                        request.prepared is None
                        or native.id != request.prepared.result.regimen.id
                        or native.version_no != request.prepared.result.regimen.version_no
                    )
                ):
                    raise ValueError
                if command.kind == "change_plan" and replayed and request is not None:
                    expected = request.prepared.result.regimen
                    comparable = (
                        "patient_medication_id",
                        "dose_amount",
                        "dose_unit",
                        "frequency_rule",
                        "is_prn",
                        "route",
                        "food_instruction",
                        "course_start_date",
                        "course_end_date",
                        "patient_edited",
                    )
                    if any(
                        getattr(native, name) != getattr(expected, name) for name in comparable
                    ) or native.supersedes_id != (
                        command.values.predecessor_id if command.values.expected_state == "active" else None
                    ):
                        raise ValueError
            elif command.kind in {"save_source", "review_registration"}:
                if native.patient_id != owner:
                    raise ValueError
                if command.kind == "save_source" and native.id != receipt.business_ref.id:
                    raise ValueError
                if (
                    command.kind == "save_source"
                    and request is not None
                    and (
                        request.materialized_source is None
                        or native.id != request.materialized_source.metadata.task.id
                        or (not replayed and native.version != request.materialized_source.metadata.task.version)
                    )
                ):
                    raise ValueError
                if command.kind == "review_registration" and native.draft_regimen_id != receipt.business_ref.id:
                    raise ValueError
                if command.kind == "review_registration" and request is not None:
                    expected = (
                        request.prepared.result.regimen.id
                        if request.prepared is not None
                        else request.existing_review.draft_regimen_id
                    )
                    if native.id != binding.prepared_ref.id or (not replayed and native.draft_regimen_id != expected):
                        raise ValueError
                if command.kind == "review_registration" and native.id != binding.prepared_ref.id:
                    raise ValueError
            elif command.kind == "review_source":
                if native.patient_id != owner or native.id != command.source_id:
                    raise ValueError
            elif command.kind == "delete_draft" and native.deleted is not True:
                raise ValueError
            if command.kind not in {"change_plan", "save_source", "review_registration"}:
                if receipt.business_ref != binding.prepared_ref:
                    raise ValueError
            return result
        except (ValueError, TypeError, AttributeError):
            raise ProviderUnavailableError(
                "Medication receipt binding unavailable; inspect the native result"
            ) from None
