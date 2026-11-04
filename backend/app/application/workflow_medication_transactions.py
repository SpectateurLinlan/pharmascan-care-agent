"""Existing independent patient enrollment APIs over fixed medication transactions."""

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING
from uuid import UUID, uuid5

from ..contracts.agent_execution import current_execution
from ..contracts.assistant_workflows import (
    BusinessRef,
    CapabilityBusinessWriter,
    Preparation,
    WorkflowContext,
    WorkflowRepository,
    validate_workflow_values,
)
from ..contracts.enrollment_operations import EnrollmentWritePort
from ..contracts.ports import Clock, ConfirmationChallengeRepository
from ..contracts.workflow_coordination import BusinessReceiptReader
from ..contracts.workflow_medication_writes import (
    ActivateMedication,
    DeleteMedicationDraft,
    EndMedicationPlan,
    MedicationWorkflowWritePort,
    PrepareMedicationMaintenance,
    PrepareSourceReview,
    RequestMedicationChallenge,
    ReviewMedicationIdentity,
    ReviewMedicationSource,
    ReviewSourceRegistration,
    SaveSourceRegistration,
)
from ..contracts.workflow_persistence import WorkflowWriteBinding
from ..domain.errors import NotFoundError, ProviderUnavailableError, StaleVersionError, ValidationError
from .assistant_capabilities.enrollment import EnrollmentAdapter
from .enrollment import MedicationEnrollmentService
from .preferences import PreferenceService
from .workflow_attachments import WorkflowAttachmentService

if TYPE_CHECKING:
    from ..agent.orchestrator import AgentOrchestrator


class MedicationWorkflowTransactions:
    capability_ids = frozenset({"medication.enroll"})

    def __init__(
        self,
        *,
        writes: MedicationWorkflowWritePort,
        bindings: EnrollmentWritePort,
        tasks: WorkflowRepository,
        receipts: BusinessReceiptReader,
        adapter: EnrollmentAdapter,
        attachments: WorkflowAttachmentService,
        enrollment: MedicationEnrollmentService,
        challenges: ConfirmationChallengeRepository,
        orchestrator: "AgentOrchestrator",
        preferences: PreferenceService,
        clock: Clock,
        preparers: Mapping[str, CapabilityBusinessWriter] | None = None,
        maintenance=None,
        deletion=None,
        source_adapter=None,
    ):
        self._writes, self._bindings, self._tasks, self._receipts = writes, bindings, tasks, receipts
        self._adapter, self._attachments, self._enrollment = adapter, attachments, enrollment
        self._challenges, self._orchestrator, self._preferences = challenges, orchestrator, preferences
        self._clock = clock
        self._preparers = dict(preparers or {"medication.enroll": adapter})
        if not set(self._preparers).issubset(
            {"medication.enroll", "medication.plan.change", "medication.draft.resume"}
        ):
            raise ValidationError("Use explicit medication preparation adapters")
        self._maintenance, self._deletion = maintenance, deletion
        self._source_adapter = source_adapter
        self.capability_ids = frozenset(self._preparers) | (
            {"medication.plan.end", "medication.draft.delete"} if maintenance else set()
        )
        if source_adapter:
            self.capability_ids |= {"medication.source.add", "medication.source.review"}

    def _context(self, task):
        prefs = self._preferences.get(task.owner)
        return WorkflowContext(
            owner=task.owner,
            task_id=task.id,
            revision=task.revision,
            capability_id=task.capability_id,
            language=prefs.preferred_language,
            timezone=prefs.timezone,
            save_mode=task.save_mode,
        )

    def prepare(self, task, expected_revision, action_key, run_binding=None):
        prior = self._writes.lookup(task.owner, action_key)
        if prior is not None:
            if (
                prior.task_id != task.id
                or prior.capability_id != task.capability_id
                or prior.outcome != "prepared"
                or prior.binding_revision != expected_revision + 1
                or prior.business_ref.kind not in {"regimen", "enrollment_task", "media_review"}
            ):
                raise StaleVersionError("Enrollment preparation belongs to another scope")
            return prior
        if (
            task.capability_id not in self.capability_ids
            or task.save_mode != "allowed"
            or task.revision != expected_revision
        ):
            raise StaleVersionError("Use the current saved enrollment draft")
        execution = current_execution.get()
        if run_binding is not None and (execution is None or getattr(execution, "write_binding", None) != run_binding):
            raise ProviderUnavailableError("Current durable enrollment execution is unavailable")
        fields = validate_workflow_values(task.capability_id, task.fields)
        if task.capability_id in {"medication.source.add", "medication.source.review"}:
            ref = (
                BusinessRef(kind="enrollment_task", id=fields.source_task_id, version=fields.expected_version)
                if fields.source_task_id
                else BusinessRef(kind="media_review", id=task.id, version=expected_revision + 1)
            )
            return self._writes.apply(
                task.owner,
                PrepareSourceReview(
                    binding=WorkflowWriteBinding(
                        task_id=task.id,
                        task_revision=expected_revision,
                        capability_id=task.capability_id,
                        action_key=action_key,
                        prepared_ref=ref,
                        expected_domain_revision=self._writes.revision(task.owner),
                        run_binding=run_binding,
                    )
                ),
            ).receipt
        if task.capability_id in {"medication.plan.end", "medication.draft.delete"}:
            ready = self._maintenance.prepare(self._context(task), fields, ())
            if ready.workflow_state != "ready_for_review":
                raise ValidationError("Choose the current maintenance target")
            ref = (
                BusinessRef(kind="regimen", id=fields.regimen_id, version=fields.expected_version)
                if task.capability_id == "medication.plan.end"
                else BusinessRef(
                    kind="regimen" if fields.kind == "draft" else "enrollment_task",
                    id=fields.target_id,
                    version=ready.input_fields["expected_version"],
                )
            )
            return self._writes.apply(
                task.owner,
                PrepareMedicationMaintenance(
                    binding=WorkflowWriteBinding(
                        task_id=task.id,
                        task_revision=expected_revision,
                        capability_id=task.capability_id,
                        action_key=action_key,
                        prepared_ref=ref,
                        expected_domain_revision=self._writes.revision(task.owner),
                        run_binding=run_binding,
                    )
                ),
            ).receipt
        assets = self._attachments.assets(task.owner, task.id) if task.attachment_ids else ()
        ref = self._preparers[task.capability_id].prepare_once(self._context(task), fields, assets, action_key)
        receipt = self._writes.lookup(task.owner, action_key)
        if (
            receipt is None
            or receipt.owner != task.owner
            or receipt.task_id != task.id
            or receipt.capability_id != task.capability_id
            or receipt.business_ref != ref
            or receipt.outcome != "prepared"
            or receipt.binding_revision != expected_revision + 1
        ):
            raise StaleVersionError("Actual coupled enrollment receipt unavailable")
        return receipt

    def handles_regimen(self, owner: UUID, regimen_id: UUID):
        binding = self._bindings.for_regimen(owner, regimen_id)
        if binding is None or binding.workflow_task_id is None:
            return False
        return self._tasks.get(owner, binding.workflow_task_id).capability_id in self.capability_ids

    def handles_source_task(self, owner, task_id):
        return self._source_adapter is not None and self._tasks.get(owner, task_id).capability_id in {
            "medication.source.add",
            "medication.source.review",
        }

    def _source_binding(self, owner, task_id, revision, key):
        task = self._tasks.get(owner, task_id)
        if task.save_mode != "allowed" or task.state == "suspended" or not self.handles_source_task(owner, task_id):
            raise StaleVersionError("Use the current saved source review")
        prior = self._writes.lookup(owner, key)
        if prior is None and (task.revision != revision or task.state != "awaiting_confirmation"):
            raise StaleVersionError("Current source review changed")
        if prior is not None and (
            prior.task_id != task_id
            or prior.capability_id != task.capability_id
            or prior.binding_revision != revision + 1
        ):
            raise StaleVersionError("Source event belongs to another review")
        rows = [
            r
            for r in self._receipts.task_receipts(owner, task_id)
            if r.capability_id == task.capability_id
            and r.binding_revision == revision
            and r.business_ref.kind in {"media_review", "enrollment_task"}
        ]
        if not rows or len({(r.business_ref, r.domain_revision) for r in rows}) != 1:
            raise StaleVersionError("Actual source preparation receipt unavailable")
        r = rows[0]
        return WorkflowWriteBinding(
            task_id=task_id,
            task_revision=revision,
            capability_id=task.capability_id,
            action_key=key,
            prepared_ref=r.business_ref,
            expected_domain_revision=r.domain_revision,
        )

    def save_source(self, owner, task_id, revision, target, attachment_id):
        key = uuid5(task_id, f"source-save:{revision}:{target}:{attachment_id}")
        b = self._source_binding(owner, task_id, revision, key)
        expected = uuid5(task_id, "source-registration") if b.prepared_ref.kind == "media_review" else b.prepared_ref.id
        if target != expected:
            raise StaleVersionError("Source target differs from the current owned original")
        return self._writes.apply(
            owner, SaveSourceRegistration(binding=b, attachment_id=attachment_id, confirmed=True)
        ).result

    def review_registration(self, owner, task_id, revision, target, payload):
        if payload.patient_reviewed is not True:
            raise ValidationError("Independent source review is required")
        key = uuid5(task_id, f"source-review:{target}:{revision}")
        b = self._source_binding(owner, task_id, revision, key)
        if b.prepared_ref.kind != "enrollment_task" or b.prepared_ref.id != target:
            raise StaleVersionError("Choose the current saved source registration")
        return self._writes.apply(
            owner,
            ReviewSourceRegistration(
                binding=b,
                draft=payload.draft,
                distinct_product_confirmed=payload.distinct_product_confirmed,
                product_category=payload.product_category,
                replace_active_plan=payload.replace_active_plan,
                confirmed=True,
            ),
        ).result

    def maintain(self, owner, task_id, revision, target, *, deleting=False, draft_kind=None):
        task = self._tasks.get(owner, task_id)
        cap = "medication.draft.delete" if deleting else "medication.plan.end"
        if task.capability_id != cap or task.save_mode != "allowed" or task.state == "suspended":
            raise StaleVersionError("Use the current independently confirmed maintenance task")
        rows = [
            r
            for r in self._receipts.task_receipts(owner, task_id)
            if r.capability_id == cap and r.outcome == "prepared" and r.binding_revision == revision
        ]
        if len(rows) != 1 or rows[0].business_ref.id != target:
            raise StaleVersionError("Patient maintenance target or revision changed")
        prep = rows[0]
        b = WorkflowWriteBinding(
            task_id=task_id,
            task_revision=revision,
            capability_id=cap,
            action_key=uuid5(prep.action_key, "patient-maintenance"),
            prepared_ref=prep.business_ref,
            expected_domain_revision=prep.domain_revision,
        )
        if deleting:
            fields = validate_workflow_values(cap, task.fields)
            if fields.kind != draft_kind:
                raise StaleVersionError("Draft deletion kind changed")
            return self._writes.apply(
                owner, DeleteMedicationDraft(binding=b, draft_kind=draft_kind, confirmed=True)
            ).result
        return self._writes.apply(owner, EndMedicationPlan(binding=b, confirmed=True)).result

    def _task(self, owner, regimen_id):
        binding = self._bindings.for_regimen(owner, regimen_id)
        if binding is None or binding.workflow_task_id is None:
            raise NotFoundError("Task-bound enrollment unavailable")
        task = self._tasks.get(owner, binding.workflow_task_id)
        if (
            task.capability_id not in self.capability_ids
            or task.save_mode != "allowed"
            or task.state not in {"awaiting_confirmation", "completed"}
            or not any(
                ref.kind == "regimen" and ref.id == regimen_id and ref.version == binding.version_no
                for ref in task.business_refs
            )
        ):
            raise StaleVersionError("Reopen the current saved patient enrollment review")
        return task

    def _binding(self, task, regimen_id, action_key, *, advances=True):
        prior = self._writes.lookup(task.owner, action_key)
        revision = prior.binding_revision - int(advances) if prior is not None else task.revision
        rows = [
            r
            for r in self._receipts.task_receipts(task.owner, task.id)
            if r.capability_id == task.capability_id
            and r.outcome == "prepared"
            and r.binding_revision == revision
            and r.business_ref.kind == "regimen"
            and r.business_ref.id == regimen_id
        ]
        if not rows or len({(r.business_ref, r.domain_revision) for r in rows}) != 1:
            raise StaleVersionError("Actual current enrollment preparation unavailable")
        ref, domain = rows[0].business_ref, rows[0].domain_revision
        if prior is not None and (
            prior.task_id != task.id or prior.capability_id != task.capability_id or prior.business_ref != ref
        ):
            raise StaleVersionError("Patient enrollment action belongs to another review")
        return WorkflowWriteBinding(
            task_id=task.id,
            task_revision=revision,
            capability_id=task.capability_id,
            action_key=action_key,
            prepared_ref=ref,
            expected_domain_revision=domain,
        )

    def source_regimen(self, owner: UUID, source_id: UUID):
        medicines = self._enrollment.list_medications(owner)
        rows = [
            row
            for row in self._enrollment.list_regimens_for_medications(owner, [m.id for m in medicines])
            if row.source_id == source_id and self.handles_regimen(owner, row.id)
        ]
        if not rows:
            return None
        if len(rows) != 1:
            raise StaleVersionError("Choose one current independently reviewed enrollment")
        return rows[0].id

    def review_source(self, owner, regimen_id, source_id, field_ids):
        task = self._task(owner, regimen_id)
        fields = self._enrollment.list_source_fields(owner, source_id)
        selected = None if field_ids is None else tuple(sorted(set(field_ids), key=str))
        if selected is not None and not set(selected).issubset({field.id for field in fields}):
            raise ValidationError("Choose fields belonging to the current original source")
        key = uuid5(
            task.id,
            "patient-source-review:"
            + str(source_id)
            + ":"
            + json.dumps(None if selected is None else [str(value) for value in selected]),
        )
        self._writes.apply(
            owner,
            ReviewMedicationSource(
                binding=self._binding(task, regimen_id, key), source_id=source_id, field_ids=selected, confirmed=True
            ),
        )
        return len(fields) if selected is None else len(selected)

    def review_identity(self, owner, task_id, revision, regimen_id):
        task = self._task(owner, regimen_id)
        if task.id != task_id:
            raise StaleVersionError("Original-name review belongs to another task")
        key = uuid5(task.id, f"patient-original-name-review:{regimen_id}")
        b = self._binding(task, regimen_id, key)
        if revision != b.task_revision:
            raise StaleVersionError("Original-name review changed")
        if (
            self._writes.lookup(owner, key) is None
            and self._enrollment.original_identity_review(owner, regimen_id) is None
        ):
            return 0
        self._writes.apply(owner, ReviewMedicationIdentity(binding=b, confirmed=True))
        return 1

    def challenge(self, owner, regimen_id, session_id):
        task = self._task(owner, regimen_id)
        if task.state == "completed":
            raise StaleVersionError("This plan is already active")
        session = self._orchestrator.get_session(patient_id=owner, session_id=session_id)
        if session is None:
            raise NotFoundError("Owned independent confirmation session unavailable")
        if session.state != "awaiting_confirmation":
            session = self._orchestrator.await_confirmation(patient_id=owner, session_id=session_id)
        key = uuid5(
            task.id, f"patient-activation-summary:{regimen_id}:{task.revision}:{session.id}:{session.state_version}"
        )
        result = self._writes.apply(
            owner,
            RequestMedicationChallenge(
                binding=self._binding(task, regimen_id, key, advances=False),
                session_id=session.id,
                session_state_version=session.state_version,
            ),
        )
        if result.result.expires_at <= self._clock.now():
            session = self._orchestrator.await_confirmation(patient_id=owner, session_id=session_id)
            key = uuid5(
                task.id, f"patient-activation-summary:{regimen_id}:{task.revision}:{session.id}:{session.state_version}"
            )
            result = self._writes.apply(
                owner,
                RequestMedicationChallenge(
                    binding=self._binding(task, regimen_id, key, advances=False),
                    session_id=session.id,
                    session_state_version=session.state_version,
                ),
            )
        return result.result, session

    def activate(self, owner, regimen_id, challenge_id, session_id, session_state, session_state_version):
        task = self._task(owner, regimen_id)
        challenge = self._challenges.get(owner, challenge_id)
        if (
            challenge is None
            or challenge.regimen_id != regimen_id
            or challenge.session_id != session_id
            or challenge.action != "activate_regimen"
            or session_state != "awaiting_confirmation"
            or challenge.session_state_version != session_state_version
        ):
            raise StaleVersionError("Confirm the exact independent patient activation summary")
        key = uuid5(challenge_id, "patient-activate")
        return self._writes.apply(
            owner,
            ActivateMedication(
                binding=self._binding(task, regimen_id, key),
                challenge_id=challenge_id,
                session_state_version=session_state_version,
                confirmed=True,
            ),
        ).result

    def project(self, task):
        if task.capability_id in {"medication.plan.end", "medication.draft.delete"}:
            if not task.business_refs:
                return None
            actual = [
                r
                for r in self._receipts.task_receipts(task.owner, task.id)
                if r.capability_id == task.capability_id
                and r.outcome == "applied"
                and r.binding_revision <= task.revision
                and task.business_refs == (r.business_ref,)
            ]
            try:
                result = self._maintenance.prepare(
                    self._context(task),
                    validate_workflow_values(task.capability_id, task.fields),
                    (),
                    task.business_refs,
                )
                if result.workflow_state != "completed" or len(actual) == 1:
                    return result
            except (NotFoundError, StaleVersionError, ProviderUnavailableError):
                if len(actual) == 1 and task.capability_id == "medication.plan.end":
                    return Preparation(
                        input_fields=task.fields,
                        result_ref=actual[0].business_ref,
                        workflow_state="completed",
                        prompt_key="assistant.enrollment.result_changed",
                        view_fields={"actual_result_available": False, "historical_result": True},
                    )
            return Preparation(
                input_fields=task.fields,
                result_ref=task.business_refs[0],
                workflow_state="outcome_unknown",
                prompt_key="assistant.enrollment.check_preparation",
                view_fields={"actual_result_available": False},
            )
        if task.state != "completed":
            if task.state == "awaiting_confirmation" and task.business_refs:
                ref = task.business_refs[0]
                regimen = self._enrollment.get_regimen(task.owner, ref.id) if ref.kind == "regimen" else None
                if regimen and regimen.state.value == "active":
                    return Preparation(
                        input_fields=task.fields,
                        result_ref=ref,
                        workflow_state="outcome_unknown",
                        prompt_key="assistant.enrollment.check_preparation",
                        view_fields={"actual_result_available": False},
                    )
            return None
        rows = [
            r
            for r in self._receipts.task_receipts(task.owner, task.id)
            if r.capability_id == task.capability_id
            and r.outcome == "applied"
            and r.binding_revision <= task.revision
            and task.business_refs == (r.business_ref,)
        ]
        if len(rows) != 1:
            raise StaleVersionError("Completed enrollment has no actual activation receipt")
        receipt = rows[0]
        try:
            regimen = self._enrollment.get_regimen(task.owner, receipt.business_ref.id)
            if regimen is None or regimen.version_no != receipt.business_ref.version or regimen.state.value != "active":
                raise StaleVersionError("Actual activated plan changed; retain its receipt")
            current = self._adapter.prepare(
                self._context(task), validate_workflow_values(task.capability_id, task.fields), (), task.business_refs
            )
            if current.workflow_state != "completed":
                raise StaleVersionError("Actual activation cannot currently be checked")
            return current
        except (NotFoundError, StaleVersionError, ProviderUnavailableError):
            return Preparation(
                input_fields=task.fields,
                result_ref=receipt.business_ref,
                workflow_state="completed",
                prompt_key="assistant.enrollment.result_changed",
                view_fields={"actual_result_available": False, "historical_result": True},
            )
