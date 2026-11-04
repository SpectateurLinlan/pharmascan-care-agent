"""Fixed owner-JWT workflow commands. Not composed until SQL acceptance is approved.

Cross-service Python callbacks cannot be a PostgREST transaction. This adapter
therefore denies guarded content writes; it never substitutes a process mutex.
"""

from uuid import UUID

from pydantic import BaseModel
from pydantic import ValidationError as SchemaError

from ..contracts.assistant_workflows import ActionReceipt, ControlReceipt, WorkflowContext, WorkflowTask, WorkflowUpdate
from ..contracts.workflow_attachments import STORE_ONLY_KINDS, CleanupReceipt, OriginalAttachment
from ..contracts.workflow_persistence import BusinessWriteReceipt, parse_workflow_mutation
from ..domain.errors import (
    DuplicateEventError,
    NotFoundError,
    ProviderUnavailableError,
    StaleVersionError,
    ValidationError,
)
from .supabase_data import SupabaseDataClient


def _json(value):
    if isinstance(value, BaseModel):
        if isinstance(value, OriginalAttachment) and value.source_kind in STORE_ONLY_KINDS:
            raise ProviderUnavailableError("Reference originals require a separately accepted database contract")
        # Excluded object keys remain private HTTP-to-database fields, not public DTOs.
        result = value.model_dump(mode="json", exclude={"owner"})
        if isinstance(value, (OriginalAttachment, CleanupReceipt)):
            result["object_ref"] = value.object_ref
        return result
    if isinstance(value, UUID):
        return str(value)
    return value


class WorkflowCommands:
    def __init__(self, data: SupabaseDataClient):
        self._data = data

    def call(self, owner, operation, **values):
        self._data.check_patient(owner)
        payload = self._data.request(
            "POST",
            "/rest/v1/rpc/assistant_workflow_command",
            body={"p_operation": operation, "p_input": {key: _json(value) for key, value in values.items()}},
        )
        if not isinstance(payload, dict) or set(payload) not in ({"result"}, {"error"}):
            raise ProviderUnavailableError("Workflow persistence returned an invalid result")
        if "error" in payload:
            if not isinstance(payload["error"], str):
                raise ProviderUnavailableError("Workflow persistence returned an invalid error")
            errors = {
                "stale": StaleVersionError,
                "not_found": NotFoundError,
                "duplicate": DuplicateEventError,
                "invalid": ValidationError,
                "unavailable": ProviderUnavailableError,
            }
            raise errors.get(payload["error"], ProviderUnavailableError)(
                "Workflow result changed; inspect its current status"
            )
        return payload["result"]

    @staticmethod
    def parse(model, owner, value, *, task_id=None):
        try:
            row = model.model_validate(value)
            if row.owner != owner or (
                task_id is not None and getattr(row, "task_id", getattr(row, "id", None)) != task_id
            ):
                raise ValueError
            if (
                isinstance(row, (OriginalAttachment, CleanupReceipt))
                and row.object_ref != f"{owner}/workflow-originals/{row.task_id}/{row.id}"
            ):
                raise ValueError
            return row
        except (SchemaError, ValueError, TypeError):
            raise ProviderUnavailableError("Workflow persistence returned an invalid owned record") from None

    def one(self, model, owner, operation, *, task_id=None, **values):
        result = self.call(owner, operation, **({"task_id": task_id} if task_id else {}), **values)
        context = values.get("context")
        row = self.parse(model, owner, result, task_id=task_id or (context.task_id if context else None))
        expected = (
            values.get("attachment_id")
            or getattr(values.get("attachment"), "id", None)
            or getattr(values.get("receipt"), "id", None)
        )
        if expected is not None and getattr(row, "id", None) != expected:
            raise ProviderUnavailableError("Workflow result does not match the requested original")
        action_key = values.get("action_key")
        if action_key is not None and row.action_key != action_key:
            raise ProviderUnavailableError("Workflow result does not match the requested operation")
        return row

    def many(self, model, owner, operation, **values):
        result = self.call(owner, operation, **values)
        if not isinstance(result, list) or len(result) > 2000:
            raise ProviderUnavailableError("Workflow collection could not be completely verified")
        return tuple(self.parse(model, owner, row, task_id=values.get("task_id")) for row in result)


class SupabaseWorkflowRepository(WorkflowCommands):
    def create(self, task: WorkflowTask, *, suspend_foreground=False, event_id=None, request_digest=None):
        return self.one(
            WorkflowTask,
            task.owner,
            "task_create",
            task_id=task.id,
            task=task,
            suspend_foreground=suspend_foreground,
            event_id=event_id,
            request_digest=request_digest,
        )

    def get(self, owner, task_id):
        return self.one(WorkflowTask, owner, "task_get", task_id=task_id)

    def list(self, owner, workspace_id=None):
        return self.many(WorkflowTask, owner, "task_list", workspace_id=workspace_id)

    def cas(self, owner, task_id, expected_revision, event_id, update: WorkflowUpdate, request_digest=None):
        return self.one(
            WorkflowTask,
            owner,
            "task_cas",
            task_id=task_id,
            expected_revision=expected_revision,
            event_id=event_id,
            update=update,
            request_digest=request_digest,
        )

    def bind_conversation(self, owner, task_id, expected_revision, conversation_id):
        return self.one(
            WorkflowTask,
            owner,
            "task_bind",
            task_id=task_id,
            expected_revision=expected_revision,
            conversation_id=conversation_id,
        )

    def event_result(self, owner, task_id, event_id, request_digest):
        result = self.call(owner, "task_event", task_id=task_id, event_id=event_id, request_digest=request_digest)
        return self.parse(WorkflowTask, owner, result, task_id=task_id) if result is not None else None

    def persistence_snapshot(self, owner):
        # The acceptance harness uses public projections, never a secret all-owner dump.
        return {"tasks": [row.model_dump(mode="json") for row in self.list(owner)]}


class SupabaseWorkflowMutations(WorkflowCommands):
    """Closed patient commands, never a cross-HTTP Python callback."""

    def task_receipts(self, owner, task_id):
        self._data.check_patient(owner)
        rows = self._data.all_rows("assistant_business_receipts", owner=f"eq.{owner}", task_id=f"eq.{task_id}",
                                   order="recorded_at.asc,action_key.asc")
        result = tuple(self.parse(BusinessWriteReceipt, owner, row, task_id=task_id) for row in rows)
        if len({r.action_key for r in result}) != len(result):
            raise ProviderUnavailableError("Task receipt collection binding unavailable")
        return result

    def apply(self, owner, command):
        self._data.check_patient(owner)
        command = parse_workflow_mutation(command)
        nested = getattr(command, "task", getattr(command, "control", None))
        if nested is not None and nested.owner != owner:
            raise ValidationError("Workflow belongs to another patient")
        body = command.model_dump(mode="json", exclude={"task": {"owner"}, "control": {"owner"}}, exclude_none=True)
        payload = self._data.request("POST", "/rest/v1/rpc/assistant_workflow_mutate", body={"p_command": body})
        if not isinstance(payload, dict) or set(payload) not in ({"result"}, {"error"}):
            raise ProviderUnavailableError("Workflow mutation response unavailable")
        if "error" in payload:
            errors = {"stale": StaleVersionError, "not_found": NotFoundError, "duplicate": DuplicateEventError,
                      "invalid": ValidationError}
            error = payload["error"]
            cls = errors.get(error, ProviderUnavailableError) if isinstance(error, str) else ProviderUnavailableError
            raise cls("Workflow changed; inspect its current result")
        model = ControlReceipt if command.kind in {"start_ephemeral", "switch_mode", "revoke"} else WorkflowTask
        task_id = (command.target_task_id if command.kind == "resume_handoff" else
                   command.task.id if command.kind == "start" else
                   command.control.task_id if command.kind == "start_ephemeral" else command.task_id)
        return self.parse(model, owner, payload["result"], task_id=task_id)

    def read_receipt(self, owner, action_key):
        self._data.check_patient(owner)
        rows = self._data.rows(
            "assistant_business_receipts", owner=f"eq.{owner}", action_key=f"eq.{action_key}", limit="2"
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise ProviderUnavailableError("Business receipt binding unavailable")
        row = self.parse(BusinessWriteReceipt, owner, rows[0])
        if row.action_key != action_key:
            raise ProviderUnavailableError("Business receipt binding unavailable")
        return row


class SupabaseControlRepository(WorkflowCommands):
    def guarded_write(self, owner, task_id, revision, write):
        self._data.check_patient(owner)
        return False  # No callback invocation until an equivalent cross-service atomic boundary exists.

    def create(self, receipt: ControlReceipt, *, suspend_foreground=False):
        return self.one(
            ControlReceipt,
            receipt.owner,
            "control_create",
            task_id=receipt.task_id,
            receipt=receipt,
            suspend_foreground=suspend_foreground,
        )

    def get(self, owner, task_id):
        return self.one(ControlReceipt, owner, "control_get", task_id=task_id)

    def list(self, owner):
        return self.many(ControlReceipt, owner, "control_list")

    def claim(self, owner, task_id, expected_revision, event_id, capability_id, mode):
        return self.one(
            ControlReceipt,
            owner,
            "control_claim",
            task_id=task_id,
            expected_revision=expected_revision,
            event_id=event_id,
            capability_id=capability_id,
            mode=mode,
        )

    def revoke(self, owner, task_id, expected_revision, event_id=None):
        return self.one(
            ControlReceipt,
            owner,
            "control_revoke",
            task_id=task_id,
            expected_revision=expected_revision,
            event_id=event_id,
        )

    def finish(self, owner, task_id, expected_revision, event_id, *, status="idle"):
        return self.one(
            ControlReceipt,
            owner,
            "control_finish",
            task_id=task_id,
            expected_revision=expected_revision,
            event_id=event_id,
            status=status,
        )

    def switch_mode(self, owner, task_id, expected_revision, event_id, mode):
        return self.one(
            ControlReceipt,
            owner,
            "control_mode",
            task_id=task_id,
            expected_revision=expected_revision,
            event_id=event_id,
            mode=mode,
        )

    def recover(self, owner, task_id, expected_revision, event_id):
        return self.one(
            ControlReceipt,
            owner,
            "control_recover",
            task_id=task_id,
            expected_revision=expected_revision,
            event_id=event_id,
        )


class SupabaseActionRepository(WorkflowCommands):
    def reserve(self, context: WorkflowContext, action_key):
        return self.one(ActionReceipt, context.owner, "action_reserve", context=context, action_key=action_key)

    def complete(self, context, receipt):
        self._data.check_patient(context.owner)
        if receipt.state in {"succeeded", "failed"}:
            raise ProviderUnavailableError("A verified business-result persistence boundary is required")
        if receipt.clinical_revision is not None:
            raise ProviderUnavailableError("A verified clinical-version persistence boundary is required")
        self.call(
            context.owner,
            "action_complete",
            context=context,
            receipt=receipt.model_dump(mode="json", exclude={"owner", "clinical_revision"}),
        )

    def read(self, owner, action_key):
        return self.one(ActionReceipt, owner, "action_get", action_key=action_key)

    def list(self, owner, task_id):
        return self.many(ActionReceipt, owner, "action_list", task_id=task_id)


class SupabaseOriginalRepository(WorkflowCommands):
    def begin_extraction(self, context, attachment_id, event_id):
        return self.one(
            OriginalAttachment,
            context.owner,
            "original_begin",
            task_id=context.task_id,
            context=context,
            attachment_id=attachment_id,
            event_id=event_id,
        )

    def retry_reservation(self, context, attachment_id, event_id, *, starts_writer=True):
        return self.one(
            OriginalAttachment,
            context.owner,
            "original_retry",
            task_id=context.task_id,
            context=context,
            attachment_id=attachment_id,
            event_id=event_id,
            starts_writer=starts_writer,
        )

    def reserve(self, context, attachment):
        return self.one(
            OriginalAttachment,
            context.owner,
            "original_reserve",
            task_id=context.task_id,
            context=context,
            attachment=attachment,
        )

    def find_upload(self, owner, task_id, upload_id):
        result = self.call(owner, "original_upload", task_id=task_id, upload_id=upload_id)
        return self.parse(OriginalAttachment, owner, result, task_id=task_id) if result is not None else None

    def get(self, owner, task_id, attachment_id):
        return self.one(OriginalAttachment, owner, "original_get", task_id=task_id, attachment_id=attachment_id)

    def list(self, owner, task_id=None):
        return self.many(OriginalAttachment, owner, "original_list", task_id=task_id)

    def note_written(self, owner, task_id, attachment_id, writer_id=None):
        return (
            self.call(owner, "original_written", task_id=task_id, attachment_id=attachment_id, writer_id=writer_id)
            is True
        )

    def publish(self, context, attachment, *, event_id=None):
        return self.one(
            OriginalAttachment,
            context.owner,
            "original_publish",
            task_id=context.task_id,
            context=context,
            attachment=attachment,
            event_id=event_id or attachment.upload_id,
        )

    def finish_extraction(self, context, attachment, event_id):
        return self.one(
            OriginalAttachment,
            context.owner,
            "original_extract",
            task_id=context.task_id,
            context=context,
            attachment=attachment,
            event_id=event_id,
        )

    def protect_source(self, context, attachment_id, source_ref, event_id):
        return self.one(
            OriginalAttachment,
            context.owner,
            "original_protect",
            task_id=context.task_id,
            context=context,
            attachment_id=attachment_id,
            source_ref=source_ref,
            event_id=event_id,
        )


class SupabaseCleanupRepository(WorkflowCommands):
    def get(self, owner, attachment_id):
        return self.one(CleanupReceipt, owner, "cleanup_get", attachment_id=attachment_id)

    def list(self, owner, task_id):
        return self.many(CleanupReceipt, owner, "cleanup_list", task_id=task_id)

    def mark_written(self, owner, task_id, attachment_id, writer_id=None):
        self.call(owner, "cleanup_written", task_id=task_id, attachment_id=attachment_id, writer_id=writer_id)

    def update(self, receipt):
        self._data.check_patient(receipt.owner)
        if receipt.state == "deleted":
            raise ProviderUnavailableError("A verified Storage-deletion persistence boundary is required")
        self.call(receipt.owner, "cleanup_update", receipt=receipt)
