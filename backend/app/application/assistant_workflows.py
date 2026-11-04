"""Deterministic coordination; adapters never gain patient confirmation authority."""

import hashlib
import json
from collections.abc import Callable, Mapping
from typing import TypeVar
from uuid import UUID, uuid5

from pydantic import BaseModel

from ..agent.capabilities import CapabilityRegistry
from ..contracts.agent_execution import current_execution
from ..contracts.assistant_workflows import (
    CapabilityAdapter,
    CapabilityBusinessWriter,
    CapabilityPatientActionGuard,
    CapabilityPatientResultReader,
    CapabilityTaskResumer,
    ControlReceipt,
    ControlRepository,
    EphemeralPayload,
    Preparation,
    SaveMode,
    WorkflowAttachmentReader,
    WorkflowContext,
    WorkflowEvent,
    WorkflowRepository,
    WorkflowTask,
    WorkflowUpdate,
    WorkflowView,
    validate_workflow_values,
)
from ..contracts.ports import Clock, IdGenerator
from ..contracts.workflow_coordination import WorkflowBusinessTransactions
from ..contracts.workflow_persistence import (
    AdvanceWorkflow,
    BindWorkflowConversation,
    ResumeWorkflowHandoff,
    RevokeWorkflow,
    StartEphemeralWorkflow,
    StartSavedWorkflow,
    SwitchWorkflowMode,
    WorkflowMutationPort,
)
from ..domain.errors import NotFoundError, ProviderUnavailableError, StaleVersionError, ValidationError
from .conversation_threads import ConversationThreadService
from .preferences import PreferenceService
from .workflow_cleanup import WorkflowCleanupService

TERMINAL = {"completed", "cancelled"}
T = TypeVar("T")


class WorkflowService:
    def __init__(
        self,
        *,
        repository: WorkflowRepository,
        registry: CapabilityRegistry,
        adapters: Mapping[str, CapabilityAdapter],
        clock: Clock,
        ids: IdGenerator,
        conversations: ConversationThreadService,
        preferences: PreferenceService,
        controls: ControlRepository | None = None,
        attachments: WorkflowAttachmentReader | None = None,
        cleanup: WorkflowCleanupService | None = None,
        writers: Mapping[str, CapabilityBusinessWriter] | None = None,
        patient_guards: Mapping[str, CapabilityPatientActionGuard] | None = None,
        patient_results: Mapping[str, CapabilityPatientResultReader] | None = None,
        task_resumers: Mapping[str, CapabilityTaskResumer] | None = None,
        mutations: WorkflowMutationPort | None = None,
        business_transactions: Mapping[str, WorkflowBusinessTransactions] | None = None,
    ):
        self._repository, self._registry, self._adapters = repository, registry, dict(adapters)
        self._clock, self._ids = clock, ids
        self._conversations, self._preferences = conversations, preferences
        self._controls = controls
        self._attachments = attachments
        self._cleanup = cleanup
        self._writers = dict(writers or {})
        self._patient_guards = dict(patient_guards or {})
        self._patient_results = dict(patient_results or {})
        self._task_resumers = dict(task_resumers or {})
        self._mutations = mutations
        self._business_transactions = dict(business_transactions or {})

    def _mutate(self, owner, command):
        control = current_execution.get()
        if control is not None:
            control.check()
            binding = getattr(control, "write_binding", None)
            if binding is None:
                raise ProviderUnavailableError("This task write requires an explicit transactional run binding")
            command = command.model_copy(update={"run_binding": binding})
        result = self._mutations.apply(owner, command)
        if control is not None:
            control.check()
        return result

    def _cleanup_view(self, owner: UUID, view: WorkflowView) -> WorkflowView:
        if self._cleanup is None:
            return view
        status = self._cleanup.status(owner, view.task_id)
        view = view.model_copy(
            update={
                "cleanup_pending": status.pending or view.visible_fields.get("cleanup_pending") is True,
                "protected_originals": status.protected,
            }
        )
        if view.save_mode != "ephemeral":
            return view
        if status.pending:
            return view.model_copy(
                update={"storage_state": "cleanup_pending", "prompt_key": "assistant.workflow.cleanup_pending"}
            )
        if status.protected:
            return view.model_copy(update={"prompt_key": "assistant.workflow.source_retained"})
        return view

    def _require_controls(self) -> ControlRepository:
        if self._controls is None:
            raise ValidationError("No-save workflow controls are unavailable")
        return self._controls

    def control(self, owner: UUID, task_id: UUID) -> ControlReceipt:
        return self._require_controls().get(owner, task_id)

    def guarded_write(self, owner: UUID, task_id: UUID, revision: int, write: Callable[[], None]) -> bool:
        return self._require_controls().guarded_write(owner, task_id, revision, write)

    def guarded_device_action(
        self, owner: UUID, task_id: UUID, revision: int, capability_id: str, write: Callable[[WorkflowContext], T]
    ) -> T:
        """Patient native device APIs only; never an LLM tool or a read query."""
        if capability_id not in {"notification.subscribe", "notification.unsubscribe", "notification.test"}:
            raise ValidationError("This operation is not an allowlisted device action")
        output = []

        def checked():
            task = self._repository.get(owner, task_id)
            control = self.control(owner, task_id)
            if (
                task.revision != revision
                or task.capability_id != capability_id
                or task.save_mode != "allowed"
                or control.status != "idle"
                or task.state in TERMINAL | {"suspended"}
            ):
                raise StaleVersionError("Reopen the current saved device action")
            self._adapter(capability_id)
            validate_workflow_values(capability_id, task.fields)
            output.append(write(self._context(task)))

        if not self.guarded_write(owner, task_id, revision, checked):
            raise StaleVersionError("The device task or saving permission changed")
        return output[0]

    def guarded_conversation_action(
        self,
        owner: UUID,
        task_id: UUID,
        revision: int,
        capability_id: str,
        write: Callable[[WorkflowContext, BaseModel], T],
    ) -> T:
        """Only explicit native conversation transitions, never historical tool execution."""
        if capability_id not in {"conversation.new", "conversation.resume", "conversation.clear"}:
            raise ValidationError("This operation is not a conversation transition")
        output = []

        def checked():
            task = self._repository.get(owner, task_id)
            control = self.control(owner, task_id)
            if (
                task.revision != revision
                or task.capability_id != capability_id
                or task.save_mode != "allowed"
                or control.status != "idle"
                or task.state in TERMINAL | {"suspended"}
            ):
                raise StaleVersionError("Reopen the current saved conversation action")
            values = validate_workflow_values(capability_id, task.fields)
            output.append(write(self._context(task), values))

        if not self.guarded_write(owner, task_id, revision, checked):
            raise StaleVersionError("The conversation task or saving permission changed")
        return output[0]

    def guarded_patient_action(
        self,
        owner: UUID,
        task_id: UUID,
        revision: int,
        *,
        capability_id: str,
        target_id: UUID,
        target_kind: str,
        write: Callable[[], T],
    ) -> T:
        """Existing patient API only; never exposed as an LLM-executable tool."""
        output = []

        def guarded():
            task = self._repository.get(owner, task_id)
            control = self.control(owner, task_id)
            if (
                task.revision != revision
                or task.capability_id != capability_id
                or task.save_mode != "allowed"
                or control.status != "idle"
                or task.state not in {"awaiting_confirmation", "completed"}
            ):
                raise StaleVersionError("The patient review changed; reopen the current saved action")
            ref = next((row for row in task.business_refs if row.kind == target_kind and row.id == target_id), None)
            if ref is None:
                raise ValidationError("The patient action does not match the prepared owned record")
            prepared = self._prepare(task)
            if prepared.result_ref != ref or prepared.workflow_state not in {"awaiting_confirmation", "completed"}:
                raise StaleVersionError("The current record no longer matches this patient review")
            patient_guard = self._patient_guards.get(capability_id)
            output.append(
                patient_guard.run_patient_action(self._context(task), ref, write) if patient_guard else write()
            )

        if not self.guarded_write(owner, task_id, revision, guarded):
            raise StaleVersionError("Saving permission changed; this patient action cannot continue")
        return output[0]

    def bind_conversation(self, owner: UUID, task_id: UUID, revision: int, conversation_id: UUID) -> WorkflowView:
        self._conversations.require(owner, conversation_id)
        if self._mutations is not None:
            return self._view(
                self._mutate(
                    owner,
                    BindWorkflowConversation(
                        task_id=task_id,
                        expected_revision=revision,
                        conversation_id=conversation_id,
                    ),
                )
            )
        return self._view(self._repository.bind_conversation(owner, task_id, revision, conversation_id))

    def _create_saved(self, task: WorkflowTask, *, suspend_foreground=False, event_id=None, request_digest=None):
        if self._mutations is not None:
            return self._mutate(
                task.owner,
                StartSavedWorkflow(
                    task=task,
                    event_id=event_id,
                    request_digest=request_digest,
                ),
            )
        return self._repository.create(
            task, suspend_foreground=suspend_foreground, event_id=event_id, request_digest=request_digest
        )

    def preview(self, owner: UUID, task_id: UUID, payload: EphemeralPayload) -> WorkflowView:
        control = self.control(owner, task_id)
        if control.mode != "ephemeral" or control.capability_id != payload.capability_id:
            raise ValidationError("Page input does not belong to this no-save workflow")
        task = self._transient(control, payload.fields)
        prepared = self._prepare(task)
        state = (
            control.status
            if control.status in {"suspended", "cancelled", "completed"}
            else "outcome_unknown"
            if control.status in {"processing", "interrupted"}
            else prepared.workflow_state
        )
        return self._view(task.model_copy(update={"state": state, "missing_fields": prepared.missing_fields}), prepared)

    def _adapter(self, capability_id: str) -> CapabilityAdapter:
        self._registry.get(capability_id)
        adapter = self._adapters.get(capability_id)
        if adapter is None:
            raise ValidationError("Assistant capability is not implemented")
        return adapter

    def implemented_capabilities(self) -> frozenset[str]:
        return frozenset(self._adapters)

    def read_only_input(
        self,
        owner: UUID,
        task_id: UUID,
        revision: int,
        capability_id: str,
        ephemeral: EphemeralPayload | None = None,
    ) -> tuple[WorkflowContext, BaseModel]:
        """Current typed query input; no persistence, provider call or write authority."""
        if self._registry.get(capability_id).mode != "read" and capability_id not in {
            "image.compare",
            "source.preview",
            "reminder.calendar.export",
        }:
            raise ValidationError("This capability is not a read-only query")
        self._adapter(capability_id)
        control = self.control(owner, task_id)
        if control.capability_id != capability_id:
            raise ValidationError("This task cannot execute this query")
        if control.revision != revision or control.status != "idle":
            raise StaleVersionError("The query changed; reopen its current input")
        if control.mode == "ephemeral":
            if ephemeral is None or ephemeral.capability_id != capability_id:
                raise ValidationError("Provide the current no-save page input")
            task = self._transient(control, ephemeral.fields)
        else:
            if ephemeral is not None:
                raise ValidationError("Saved queries do not accept page-state replacement")
            task = self._repository.get(owner, task_id)
        if task.revision != revision or task.state in TERMINAL | {"suspended"}:
            raise StaleVersionError("This query is no longer active")
        return self._context(task), validate_workflow_values(capability_id, task.fields)

    def _context(self, task: WorkflowTask) -> WorkflowContext:
        preferences = self._preferences.get(task.owner)
        return WorkflowContext(
            owner=task.owner,
            task_id=task.id,
            revision=task.revision,
            capability_id=task.capability_id,
            language=preferences.preferred_language,
            timezone=preferences.timezone,
            save_mode=task.save_mode,
        )

    def _prepare(self, task: WorkflowTask) -> Preparation:
        transaction = self._business_transactions.get(task.capability_id)
        if transaction is not None:
            actual = transaction.project(task)
            if actual is not None:
                return actual
        writer = self._writers.get(task.capability_id)
        if task.save_mode == "allowed" and not task.business_refs and writer is not None:
            prior = writer.reconcile(
                self._context(task), uuid5(task.id, f"{task.capability_id}:revision:{task.revision}")
            )
            if prior is not None:
                return Preparation(
                    workflow_state="outcome_unknown",
                    prompt_key="assistant.enrollment.check_preparation",
                    view_fields=task.fields,
                )
        values = validate_workflow_values(task.capability_id, task.fields)
        assets = (
            self._attachments.assets(task.owner, task.id)
            if self._attachments and task.attachment_ids and task.save_mode == "allowed"
            else ()
        )
        return self._adapter(task.capability_id).prepare(self._context(task), values, assets, task.business_refs)

    def _view(self, task: WorkflowTask, prepared: Preparation | None = None) -> WorkflowView:
        prepared = prepared or self._prepare(task)
        return self._cleanup_view(
            task.owner,
            WorkflowView(
                input_fields=prepared.input_fields,
                task_id=task.id,
                workspace_id=task.workspace_id,
                conversation_id=task.conversation_id,
                revision=task.revision,
                capability_id=task.capability_id,
                state=prepared.workflow_state
                if task.state in {"ready_for_review", "collecting", "awaiting_confirmation"}
                else task.state,
                save_mode=task.save_mode,
                storage_state=task.storage_state,
                prompt_key=prepared.prompt_key,
                visible_fields=prepared.view_fields,
                missing_fields=prepared.missing_fields,
                actions=() if task.state in TERMINAL or task.state == "suspended" else prepared.actions,
                result_ref=prepared.result_ref,
            ),
        )

    def start(
        self,
        owner: UUID,
        capability_id: str,
        workspace_id: UUID,
        conversation_id: UUID | None,
        values: dict[str, object],
        save_mode: SaveMode = "allowed",
        client_event_id: UUID | None = None,
    ) -> WorkflowView:
        self._adapter(capability_id)
        if conversation_id is not None:
            self._conversations.require(owner, conversation_id)
        parsed = validate_workflow_values(capability_id, values)
        if capability_id == "medication.enroll" and (
            values.get("existing_medication_id") or values.get("distinct_product_confirmed")
        ):
            raise ValidationError("Use the explicit medication record choice")
        task = WorkflowTask(
            id=uuid5(workspace_id, f"{owner}:{client_event_id}") if client_event_id else self._ids.new_id(),
            owner=owner,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            capability_id=capability_id,
            save_mode=save_mode,
            storage_state="saved" if save_mode == "allowed" else "ephemeral",
            fields=parsed.model_dump(mode="json", exclude_none=True),
            updated_at=self._clock.now(),
        )
        prepared = self._prepare(task)
        task = task.model_copy(update={"state": prepared.workflow_state, "missing_fields": prepared.missing_fields})
        if save_mode == "allowed":
            digest = hashlib.sha256(
                json.dumps(
                    {
                        "capability_id": capability_id,
                        "workspace_id": str(workspace_id),
                        "conversation_id": str(conversation_id),
                        "save_mode": save_mode,
                        "values": values,
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            saved = self._create_saved(task, suspend_foreground=True, event_id=client_event_id, request_digest=digest)
            return self._view(saved)
        control = ControlReceipt(
            owner=owner,
            task_id=task.id,
            revision=task.revision,
            capability_id=capability_id,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            mode="ephemeral",
        )
        if self._mutations is not None:
            self._mutate(owner, StartEphemeralWorkflow(control=control))
        else:
            self._require_controls().create(control, suspend_foreground=True)
        return self._view(task, prepared)

    def _transient(self, control: ControlReceipt, fields: dict[str, object]) -> WorkflowTask:
        parsed = validate_workflow_values(control.capability_id, fields)
        if control.workspace_id is None:
            raise ValidationError("Workflow workspace binding is missing")
        return WorkflowTask(
            id=control.task_id,
            owner=control.owner,
            workspace_id=control.workspace_id,
            conversation_id=control.conversation_id,
            capability_id=control.capability_id,
            revision=control.revision,
            save_mode=control.mode,
            storage_state="ephemeral" if control.mode == "ephemeral" else "saved",
            fields=parsed.model_dump(mode="json", exclude_none=True),
            updated_at=self._clock.now(),
        )

    def _lost(self, control: ControlReceipt) -> WorkflowView:
        interrupted = control.status in {"processing", "interrupted"}
        return self._cleanup_view(
            control.owner,
            WorkflowView(
                task_id=control.task_id,
                workspace_id=control.workspace_id,
                conversation_id=control.conversation_id,
                revision=control.revision,
                capability_id=control.capability_id,
                state="outcome_unknown"
                if interrupted
                else (
                    control.status
                    if control.status in {"suspended", "cancelled", "completed"}
                    else "failed_recoverable"
                ),
                save_mode=control.mode,
                storage_state="ephemeral" if control.mode == "ephemeral" else "save_failed",
                prompt_key="assistant.workflow.interrupted"
                if interrupted
                else (
                    "assistant.workflow.ephemeral_lost"
                    if control.mode == "ephemeral"
                    else "assistant.workflow.save_failed"
                ),
            ),
        )

    def _privacy_event(
        self,
        control: ControlReceipt,
        event: WorkflowEvent,
        ephemeral: dict | None,
    ) -> WorkflowView:
        controls = self._require_controls()
        if event.values:
            raise ValidationError("Saving controls do not accept fields")
        if event.kind == "cancel_save":
            local = None
            if control.mode == "allowed":
                try:
                    local = self._repository.get(control.owner, control.task_id)
                except NotFoundError:
                    pass
            if self._mutations is not None:
                revoked = self._mutate(
                    control.owner,
                    RevokeWorkflow(
                        task_id=control.task_id,
                        expected_revision=event.expected_revision,
                        event_id=event.event_id,
                    ),
                )
                if self._cleanup is not None:
                    self._cleanup.retry_cleanup(control.owner, control.task_id)
            else:
                revoked = (
                    self._cleanup.revoke(control.owner, control.task_id, event.expected_revision, event.event_id)
                    if self._cleanup
                    else controls.revoke(control.owner, control.task_id, event.expected_revision, event.event_id)
                )
            if local is None:
                return self._lost(revoked)
            return self._view(
                local.model_copy(
                    update={
                        "revision": revoked.revision,
                        "save_mode": "ephemeral",
                        "storage_state": "ephemeral",
                    }
                )
            )
        if control.mode == "allowed":
            try:
                self._repository.get(control.owner, control.task_id)
            except NotFoundError:
                pass  # Retry a previously failed explicit save, with fresh page input.
            else:
                raise ValidationError("This workflow is already saved")
        if ephemeral is None:
            raise ValidationError("Saving requires the current page input")
        payload = EphemeralPayload.model_validate(ephemeral)
        if payload.capability_id != control.capability_id:
            raise ValidationError("Workflow input belongs to another capability")
        # Permission CAS precedes semantic validation or any saving service.
        switched = (
            self._mutate(
                control.owner,
                SwitchWorkflowMode(
                    task_id=control.task_id,
                    expected_revision=event.expected_revision,
                    event_id=event.event_id,
                    mode="allowed",
                ),
            )
            if self._mutations is not None
            else controls.switch_mode(
                control.owner, control.task_id, event.expected_revision, event.event_id, "allowed"
            )
        )
        try:
            task = self._transient(switched, payload.fields)
            prepared = self._prepare(task)
        except (ValueError, ValidationError):
            return self._lost(switched)
        task = task.model_copy(update={"state": prepared.workflow_state, "missing_fields": prepared.missing_fields})
        return self._view(self._create_saved(task), prepared)

    @staticmethod
    def _event_values(capability_id, fields, event):
        values = dict(event.values)
        if capability_id == "medication.plan.change" and isinstance(values.get("details"), dict):
            same_target = all(
                name not in values or values[name] == fields.get(name)
                for name in ("regimen_id", "expected_version", "expected_state")
            )
            prior = fields.get("details")
            if same_target and isinstance(prior, dict):
                values["details"] = {**prior, **values["details"]}
        if event.kind == "select_candidate":
            if capability_id != "medication.enroll":
                raise ValidationError("This task cannot select an enrollment record")
            if values == {"choice": "different_product"}:
                return {"medication_name": None, "existing_medication_id": None, "distinct_product_confirmed": None}
            if values == {"choice": "distinct_product"}:
                return {"existing_medication_id": None, "distinct_product_confirmed": True}
            if set(values) == {"source_attachment_id", "source_candidate_index"}:
                if any(values[key] != fields.get(key) for key in values):
                    reset = {name: None for name in type(validate_workflow_values(capability_id, {})).model_fields}
                    return {**reset, "method": "photo", **values}
                return values
            if set(values) != {"existing_medication_id"} or not values["existing_medication_id"]:
                raise ValidationError("Choose one current medication record")
            return {**values, "distinct_product_confirmed": None}
        if capability_id == "medication.enroll":
            if "existing_medication_id" in values or "distinct_product_confirmed" in values:
                raise ValidationError("Use the explicit medication record choice")
            if "medication_name" in values and values["medication_name"] != fields.get("medication_name"):
                values["existing_medication_id"] = None
                values["distinct_product_confirmed"] = None
        return values

    def _prepare_event(self, task: WorkflowTask, event: WorkflowEvent) -> Preparation:
        prepared = self._prepare(task)
        if (
            event.kind == "select_candidate"
            and event.values == {"choice": "distinct_product"}
            and "existing_medication_choice" in prepared.missing_fields
        ):
            raise ValidationError("The recorded product attributes do not establish a different product")
        if (
            event.kind == "select_candidate"
            and "source_attachment_id" in event.values
            and (
                prepared.workflow_state == "failed_recoverable"
                or "source_product_choice" in prepared.missing_fields
                or prepared.view_fields.get("source_attachment_id") != event.values["source_attachment_id"]
                or prepared.view_fields.get("source_candidate_index") != event.values["source_candidate_index"]
            )
        ):
            raise ValidationError("Choose a product offered by the current owned original")
        if (
            event.kind == "select_candidate"
            and event.values.get("existing_medication_id")
            and "existing_medication_choice" in prepared.missing_fields
        ):
            raise ValidationError("Choose a current owned medication matching the complete product name")
        return prepared

    def _advance_ephemeral(
        self,
        control: ControlReceipt,
        event: WorkflowEvent,
        ephemeral: dict | None,
    ) -> WorkflowView:
        controls = self._require_controls()
        if event.kind == "retry" and control.status == "interrupted":
            recovered = controls.recover(control.owner, control.task_id, event.expected_revision, event.event_id)
            return (
                self.preview(control.owner, control.task_id, EphemeralPayload.model_validate(ephemeral))
                if ephemeral is not None
                else self._lost(recovered)
            )
        if event.kind not in {"provide_fields", "choose_method", "select_candidate", "pause", "resume", "cancel_task"}:
            raise ValidationError("This no-save event is not implemented")
        if control.status == "suspended" and event.kind not in {"resume", "cancel_task"}:
            raise ValidationError("Resume the workflow before providing fields")
        if event.kind in {"pause", "resume", "cancel_task"} and event.values:
            raise ValidationError("This control event does not accept fields")
        if ephemeral is None:
            raise ValidationError("No-save fields were lost; provide them again")
        payload = EphemeralPayload.model_validate(ephemeral)
        if payload.capability_id != control.capability_id:
            raise ValidationError("Workflow input belongs to another capability")
        task = self._transient(
            control, {**payload.fields, **self._event_values(control.capability_id, payload.fields, event)}
        )
        prepared = self._prepare_event(task, event)
        controls.claim(
            control.owner, control.task_id, event.expected_revision, event.event_id, control.capability_id, "ephemeral"
        )
        state = (
            "suspended"
            if event.kind == "pause"
            else "cancelled"
            if event.kind == "cancel_task"
            else prepared.workflow_state
        )
        finished = controls.finish(
            control.owner,
            control.task_id,
            event.expected_revision,
            event.event_id,
            status=state if state in {"suspended", "cancelled", "completed"} else "idle",
        )
        return self._view(
            task.model_copy(
                update={
                    "revision": finished.revision,
                    "state": state,
                    "missing_fields": prepared.missing_fields,
                }
            ),
            prepared,
        )

    def advance(
        self,
        owner: UUID,
        task_id: UUID,
        event: WorkflowEvent,
        ephemeral: dict | None = None,
    ) -> WorkflowView:
        if self._controls is not None:
            control = self._controls.get(owner, task_id)
            if event.kind in {"cancel_save", "allow_save"}:
                return self._privacy_event(control, event, ephemeral)
            if control.mode == "ephemeral":
                return self._advance_ephemeral(control, event, ephemeral)
        task = self._repository.get(owner, task_id)
        if ephemeral is not None:
            raise ValidationError("Saved workflows do not accept page-state replacement")
        EphemeralPayload(capability_id=task.capability_id, fields=event.values)
        transaction = self._business_transactions.get(task.capability_id)
        if transaction is not None and event.kind in {"prepare_confirmation", "report_business_result"}:
            if event.values or task.state == "suspended":
                raise ValidationError("Use the current saved independent review without supplied result fields")
            if event.kind == "prepare_confirmation":
                execution = current_execution.get()
                run = None
                if execution is not None:
                    execution.check()
                    run = getattr(execution, "write_binding", None)
                    if run is None:
                        raise ProviderUnavailableError("Typed preparation needs the current durable run binding")
                transaction.prepare(task, event.expected_revision, event.event_id, run)
            elif event.expected_revision != task.revision:
                raise StaleVersionError("Refresh the current settings result before checking it")
            return self.view(owner, task_id)
        request_digest = hashlib.sha256(json.dumps(event.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
        replay = self._repository.event_result(owner, task_id, event.event_id, request_digest)
        if replay is not None:
            return self._view(replay)
        if task.revision != event.expected_revision:
            raise StaleVersionError("Workflow changed; refresh it before continuing")
        if task.state in TERMINAL:
            raise ValidationError("Finished workflows cannot be executed again")
        if event.kind in {"prepare_confirmation", "report_business_result"}:
            return self._business_event(task, event, request_digest)
        if event.kind not in {"provide_fields", "choose_method", "select_candidate", "pause", "resume", "cancel_task"}:
            raise ValidationError("This workflow event is not implemented")
        if task.state == "suspended" and event.kind not in {"resume", "cancel_task"}:
            raise ValidationError("Resume the workflow before providing fields")
        refs = task.business_refs
        prior_fields = task.fields
        if not refs and event.kind != "cancel_task" and self._prepare(task).workflow_state == "outcome_unknown":
            raise StaleVersionError("Check the prepared business result before changing task state")
        if not refs and event.kind in {"provide_fields", "choose_method", "select_candidate"}:
            current = self._prepare(task)
            if current.workflow_state == "outcome_unknown":
                raise StaleVersionError("Check the prepared business result before editing these details")
            input_keys = type(validate_workflow_values(task.capability_id, prior_fields)).model_fields
            prior_fields = {
                **prior_fields,
                **{key: value for key, value in current.view_fields.items() if key in input_keys},
            }
        if refs and event.kind in {"provide_fields", "choose_method", "select_candidate"}:
            writer = self._writers.get(task.capability_id)
            if writer is None:
                raise ValidationError("Prepared review cannot be edited here")
            prior_fields = {**prior_fields, **writer.revise_inputs(self._context(task), refs[0])}
            refs = ()
        if event.kind in {"pause", "resume", "cancel_task"} and event.values:
            raise ValidationError("This control event does not accept fields")
        fields = {**prior_fields, **self._event_values(task.capability_id, prior_fields, event)}
        parsed = validate_workflow_values(task.capability_id, fields)
        candidate = task.model_copy(
            update={"fields": parsed.model_dump(mode="json", exclude_none=True), "business_refs": refs}
        )
        prepared = self._prepare_event(candidate, event)
        state = (
            "suspended"
            if event.kind == "pause"
            else "cancelled"
            if event.kind == "cancel_task"
            else prepared.workflow_state
        )
        update = WorkflowUpdate(
            state=state,
            save_mode=task.save_mode,
            storage_state=task.storage_state,
            fields=candidate.fields,
            missing_fields=prepared.missing_fields,
            attachment_ids=task.attachment_ids,
            business_refs=refs,
        )
        updated = (
            self._mutate(
                owner,
                AdvanceWorkflow(
                    task_id=task_id,
                    expected_revision=event.expected_revision,
                    event_id=event.event_id,
                    update=update,
                    request_digest=request_digest,
                ),
            )
            if self._mutations is not None
            else self._repository.cas(
                owner,
                task_id,
                event.expected_revision,
                event.event_id,
                update,
                request_digest=request_digest,
            )
        )
        return self._view(updated, prepared)

    def _business_event(self, task: WorkflowTask, event: WorkflowEvent, digest: str) -> WorkflowView:
        if event.values or task.state == "suspended":
            raise ValidationError("Resume the task and use the current review without supplied result fields")
        results = []

        def write():
            control = self.control(task.owner, task.id)
            if control.status in {"processing", "interrupted"}:
                raise StaleVersionError("Check the interrupted operation before preparing review")
            refs = task.business_refs
            writer = self._writers.get(task.capability_id)
            key = uuid5(task.id, f"{task.capability_id}:revision:{task.revision}")
            prior = writer.reconcile(self._context(task), key) if writer is not None and not refs else None
            if prior is not None:
                refs = (prior,)
            if event.kind == "prepare_confirmation" and not refs:
                current = self._prepare(task)
                if current.workflow_state != "ready_for_review":
                    raise ValidationError("Complete the missing details before preparing review")
                writer = self._writers.get(task.capability_id)
                if writer is None:
                    raise ValidationError("Business preparation is unavailable")
                assets = (
                    self._attachments.assets(task.owner, task.id) if self._attachments and task.attachment_ids else ()
                )
                ref = writer.prepare_once(
                    self._context(task), validate_workflow_values(task.capability_id, task.fields), assets, key
                )
                refs = (ref,)
            if not refs:
                raise ValidationError("This task has no prepared business result")
            if event.kind == "report_business_result" and task.capability_id in self._patient_results:
                if len(refs) != 1:
                    raise ValidationError("Patient result capture needs one prepared owned reference")
                refs = (
                    self._patient_results[task.capability_id].read_patient_result(
                        self._context(task), refs[0], validate_workflow_values(task.capability_id, task.fields)
                    ),
                )
            candidate = task.model_copy(update={"business_refs": refs})
            prepared = self._prepare(candidate)
            updated = self._repository.cas(
                task.owner,
                task.id,
                event.expected_revision,
                event.event_id,
                WorkflowUpdate(
                    state=prepared.workflow_state,
                    save_mode=task.save_mode,
                    storage_state=task.storage_state,
                    fields=task.fields,
                    missing_fields=prepared.missing_fields,
                    attachment_ids=task.attachment_ids,
                    business_refs=refs,
                ),
                request_digest=digest,
            )
            results.append(self._view(updated, prepared))

        if not self.guarded_write(task.owner, task.id, event.expected_revision, write):
            raise StaleVersionError("Workflow saving permission changed")
        return results[0]

    def view(self, owner: UUID, task_id: UUID) -> WorkflowView:
        if self._controls is not None:
            control = self._controls.get(owner, task_id)
            if control.mode == "ephemeral":
                return self._lost(control)
            try:
                view = self._view(self._repository.get(owner, task_id))
                if control.status in {"processing", "interrupted"}:
                    view = view.model_copy(
                        update={
                            "state": "outcome_unknown",
                            "prompt_key": "assistant.workflow.interrupted",
                            "actions": (),
                        }
                    )
                return view
            except NotFoundError:
                return self._lost(control)
        return self._view(self._repository.get(owner, task_id))

    def persistence_snapshot(self, owner: UUID) -> dict[str, object]:
        return self._repository.persistence_snapshot(owner)

    def started(self, owner: UUID, workspace_id: UUID, client_event_id: UUID) -> WorkflowView:
        return self.view(owner, uuid5(workspace_id, f"{owner}:{client_event_id}"))

    def saved_tasks(self, owner: UUID, workspace_id: UUID | None = None) -> tuple[WorkflowTask, ...]:
        return tuple(row for row in self._repository.list(owner, workspace_id) if row.save_mode == "allowed")

    def list_views(self, owner: UUID, workspace_id: UUID | None = None, *, include_ephemeral: bool = False):
        views = [self.view(owner, row.id) for row in self.saved_tasks(owner, workspace_id)]
        if include_ephemeral:
            views.extend(
                self._lost(control)
                for control in self._require_controls().list(owner)
                if control.mode == "ephemeral"
                and control.status not in TERMINAL
                and (workspace_id is None or control.workspace_id == workspace_id)
            )
        return tuple(views)

    def resume(self, owner: UUID, task_id: UUID) -> WorkflowView:
        task = self._repository.get(owner, task_id)
        return self.advance(
            owner,
            task_id,
            WorkflowEvent(
                event_id=self._ids.new_id(),
                expected_revision=task.revision,
                kind="resume",
            ),
        )

    def resume_draft(self, owner: UUID, task_id: UUID, revision: int) -> WorkflowView:
        if self._mutations is not None:
            task = self._repository.get(owner, task_id)
            control = self.control(owner, task_id)
            resumer = self._task_resumers.get(task.capability_id)
            if (
                task.revision != revision
                or task.save_mode != "allowed"
                or task.state in TERMINAL | {"suspended"}
                or control.status != "idle"
                or resumer is None
            ):
                raise StaleVersionError("The recovery task changed; reopen its current saved version")
            target_id = resumer.resume_target(
                self._context(task), validate_workflow_values(task.capability_id, task.fields)
            )
            target = self._repository.get(owner, target_id)
            prepared = self._prepare(target)
            resumed = self._view(
                self._mutate(
                    owner,
                    ResumeWorkflowHandoff(
                        task_id=task_id,
                        expected_revision=revision,
                        target_task_id=target_id,
                        target_revision=target.revision,
                        target_state=prepared.workflow_state,
                        event_id=self._ids.new_id(),
                    ),
                ),
                prepared,
            )
            if (
                resumed.capability_id in self._patient_results
                and resumed.result_ref is not None
                and resumed.result_ref.kind == "enrollment_task"
            ):
                return self.advance(
                    owner,
                    target_id,
                    WorkflowEvent(
                        event_id=self._ids.new_id(),
                        expected_revision=resumed.revision,
                        kind="report_business_result",
                    ),
                )
            return resumed
        output = []

        def handoff():
            task = self._repository.get(owner, task_id)
            control = self.control(owner, task_id)
            resumer = self._task_resumers.get(task.capability_id)
            if (
                task.revision != revision
                or task.save_mode != "allowed"
                or task.state in TERMINAL
                or task.state == "suspended"
                or control.status != "idle"
                or resumer is None
            ):
                raise StaleVersionError("The recovery task changed; reopen its current saved version")
            values = validate_workflow_values(task.capability_id, task.fields)
            target = resumer.resume_target(self._context(task), values)
            self.advance(
                owner,
                task_id,
                WorkflowEvent(
                    event_id=self._ids.new_id(),
                    expected_revision=revision,
                    kind="pause",
                ),
            )
            resumed = self.resume(owner, target)
            if (
                resumed.capability_id in self._patient_results
                and resumed.result_ref is not None
                and resumed.result_ref.kind == "enrollment_task"
            ):
                resumed = self.advance(
                    owner,
                    target,
                    WorkflowEvent(
                        event_id=self._ids.new_id(),
                        expected_revision=resumed.revision,
                        kind="report_business_result",
                    ),
                )
            output.append(resumed)

        if not self.guarded_write(owner, task_id, revision, handoff):
            raise StaleVersionError("Saving permission changed; the old recovery action cannot continue")
        return output[0]
