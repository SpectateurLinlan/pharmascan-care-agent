"""Explicit memory proof model and owner-JWT original commands; no remote mutex facade."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from pydantic import BaseModel

from ..contracts.agent_execution import current_execution
from ..contracts.workflow_attachments import CleanupReceipt, OriginalAttachment
from ..contracts.workflow_persistence import RunWriteBinding
from ..contracts.workflow_verification import StorageObservation, StorageOperationTicket, VerifiedOperationRef
from ..domain.errors import DuplicateEventError, NotFoundError, ProviderUnavailableError, StaleVersionError
from .workflow_repos import SupabaseOriginalRepository


@dataclass
class MemoryStorageTicket:
    owner: UUID
    value: StorageOperationTicket
    state: str = "issued"
    run_binding: RunWriteBinding | None = None


class MemoryStorageVerifier:
    """Technical state only: never reads a clinical repository or publishes content."""

    def __init__(self, *, state, clock):
        self._state, self._clock = state, clock

    def record_storage(self, observation: StorageObservation, *, timeout_seconds):
        observation = StorageObservation.model_validate(observation)
        with self._state.lock:
            row = self._state.storage_tickets.get(observation.ticket_id)
            if row is None or row.value.nonce != observation.nonce or row.value.generation != observation.generation:
                raise NotFoundError("Storage observation ticket is unavailable")
            if row.state == "issued":
                raise StaleVersionError("Storage operation was never claimed")
            ticket = row.value
            if observation.result == "bytes_verified" and (
                ticket.operation != "upload"
                or observation.checksum != ticket.expected_checksum
                or observation.byte_size != ticket.byte_size
            ):
                raise StaleVersionError("Observed bytes do not match this writer")
            if observation.result == "absent_after_delete" and (
                ticket.operation != "delete" or (row.owner, ticket.attachment_id) not in self._state.deleting_originals
            ):
                raise StaleVersionError("No matching deletion exclusion exists")
            for reference in self._state.storage_verifications.values():
                if reference.ticket_id != ticket.ticket_id:
                    continue
                if reference.result == observation.result:
                    return reference
                if reference.result != "outcome_unknown" and observation.result != "outcome_unknown":
                    raise DuplicateEventError("Storage operation already settled differently")
            reference = VerifiedOperationRef(
                ticket_id=ticket.ticket_id,
                generation=ticket.generation,
                verification_id=uuid4(),
                result=observation.result,
            )
            self._state.storage_verifications[reference.verification_id] = reference
            if observation.result != "outcome_unknown":
                row.state = "settled"
            elif row.state != "settled":
                row.state = "unknown"
            return reference


class MemoryVerifiedOriginals:
    def __init__(self, *, state, clock, originals, controls, cleanup, protection=None):
        self._state, self._clock, self._originals = state, clock, originals
        self._controls, self._cleanup, self._protection = controls, cleanup, protection

    def get(self, owner, task_id, attachment_id):
        return self._originals.get(owner, task_id, attachment_id)

    def verification_for(self,owner,task_id,attachment_id):
        with self._state.lock:
            self._state.require_original_reference(owner,attachment_id)
            source=self.get(owner,task_id,attachment_id)
            if source.state!='saved' or source.cleanup_pending:
                raise StaleVersionError('A current saved original is required')
            found=[]
            for proof in self._state.storage_verifications.values():
                row=self._state.storage_tickets.get(proof.ticket_id)
                if (proof.result=='bytes_verified' and row is not None and row.owner==owner
                    and isinstance(row.value,StorageOperationTicket) and row.value.task_id==task_id
                    and row.value.attachment_id==attachment_id and row.value.operation=='upload'
                    and row.value.object_ref==source.object_ref
                    and row.value.expected_checksum==source.original_checksum
                    and row.value.byte_size==source.byte_size):
                    found.append(proof)
            if not found:
                raise ProviderUnavailableError('Independent original byte verification is unavailable')
            return max(found,key=lambda item:item.generation)

    def _current(self, context, run_binding=None):
        control = self._controls.get(context.owner, context.task_id)
        if (
            context.save_mode != "allowed"
            or control.revoked
            or control.mode != "allowed"
            or control.revision != context.revision
            or control.capability_id != context.capability_id
        ):
            raise StaleVersionError("Original saving permission changed")
        if run_binding is not None:
            self._state.require_durable_run(context.owner, run_binding, self._clock.now())

    def reserve_ticket(self, context, attachment_id, writer_id, *, run_binding=None):
        with self._state.lock:
            self._current(context, run_binding)
            self._state.require_original_reference(context.owner, attachment_id)
            row = self.get(context.owner, context.task_id, attachment_id)
            if writer_id not in row.pending_writer_ids:
                raise StaleVersionError("No matching pending upload writer")
            existing = [
                t
                for t in self._state.storage_tickets.values()
                if t.owner == context.owner and t.value.attachment_id == attachment_id
            ]
            if any(t.value.writer_id == writer_id for t in existing):
                raise DuplicateEventError("Writer was already issued; inspect its proof before retrying")
            ticket = StorageOperationTicket(
                ticket_id=uuid4(),
                nonce=uuid4(),
                task_id=context.task_id,
                attachment_id=attachment_id,
                writer_id=writer_id,
                operation="upload",
                generation=len(existing) + 1,
                object_ref=row.object_ref,
                expected_checksum=row.original_checksum,
                content_type=row.content_type,
                byte_size=row.byte_size,
                expires_at=self._clock.now() + timedelta(seconds=45),
            )
            self._state.storage_tickets[ticket.ticket_id] = MemoryStorageTicket(
                context.owner, ticket, run_binding=run_binding
            )
            return ticket

    def claim_ticket(self, owner, ticket):
        with self._state.lock:
            stored = self._state.storage_tickets.get(ticket.ticket_id)
            if stored is None or stored.owner != owner or stored.value != ticket:
                raise NotFoundError("Owned storage ticket required")
            if stored.state != "issued" or self._clock.now() >= ticket.expires_at:
                raise StaleVersionError("Storage operation cannot be restarted")
            if ticket.operation == "upload":
                if stored.run_binding is not None:
                    self._state.require_durable_run(owner, stored.run_binding, self._clock.now())
                self._state.require_original_reference(owner, ticket.attachment_id)
                control = self._controls.get(owner, ticket.task_id)
                if control.revoked or control.mode != "allowed":
                    raise StaleVersionError("Upload saving was cancelled")
            stored.state = "inflight"

    def read_verified(self, owner, reference):
        with self._state.lock:
            stored = self._state.storage_verifications.get(reference.verification_id)
            ticket = self._state.storage_tickets.get(reference.ticket_id)
            if stored != reference or ticket is None or ticket.owner != owner:
                raise ProviderUnavailableError("No matching independently verified operation")
            return ticket.value

    def settle_writer(self, owner, reference):
        with self._state.lock:
            ticket = self.read_verified(owner, reference)
            if ticket.operation != "upload" or reference.result not in {"bytes_verified", "definitely_not_started"}:
                raise StaleVersionError("This observation does not settle an upload writer")
            if (owner, ticket.attachment_id) in self._state.originals:
                if reference.result == "bytes_verified":
                    self._originals.note_written(owner, ticket.task_id, ticket.attachment_id, ticket.writer_id)
                else:
                    row = self._state.originals[(owner, ticket.attachment_id)]
                    self._state.originals[(owner, ticket.attachment_id)] = row.model_copy(
                        update={"pending_writer_ids": tuple(w for w in row.pending_writer_ids if w != ticket.writer_id)}
                    )
            else:
                receipt = self._cleanup.get(owner, ticket.attachment_id)
                remaining = tuple(w for w in receipt.pending_writer_ids if w != ticket.writer_id)
                self._state.cleanup[(owner, ticket.attachment_id)] = receipt.model_copy(
                    update={
                        "writer_pending": bool(remaining),
                        "pending_writer_ids": remaining,
                        "state": "pending",
                        "reason": "upload_inflight" if remaining else None,
                    }
                )

    def publish_verified(self, context, attachment_id, reference, *, run_binding=None):
        with self._state.lock:
            self._current(context, run_binding)
            self._state.require_original_reference(context.owner, attachment_id)
            ticket = self.read_verified(context.owner, reference)
            if (
                ticket.task_id != context.task_id
                or ticket.attachment_id != attachment_id
                or ticket.operation != "upload"
                or reference.result != "bytes_verified"
            ):
                raise StaleVersionError("Byte proof does not match this original")
            row = self.get(context.owner, context.task_id, attachment_id)
            if row.operation_event_id != ticket.writer_id:
                raise StaleVersionError("Only the current upload may publish")
            return self._originals.publish(context, row, event_id=ticket.writer_id)

    def start_deleting(self, owner, attachment_id):
        with self._state.lock:
            receipt = self._cleanup.get(owner, attachment_id)
            if receipt.state in {"deleted", "protected"}:
                return receipt
            if receipt.writer_pending or receipt.pending_writer_ids:
                return receipt.model_copy(update={"state": "pending", "reason": "upload_inflight"})
            if (owner, attachment_id) in self._state.deleting_originals:
                return receipt.model_copy(update={"state": "pending", "reason": "operation_unknown"})
            # The public protection port shares this explicit local transaction boundary.
            if self._protection is None:
                return receipt.model_copy(update={"state": "pending", "reason": "protection_unavailable"})
            protection = self._protection.references(owner, attachment_id)
            if protection.protected or receipt.source_ref is not None:
                updated = receipt.model_copy(
                    update={
                        "state": "protected",
                        "reason": protection.reason if protection.protected else "formal_source",
                    }
                )
                self._cleanup.update(updated)
                return updated
            previous = [
                t
                for t in self._state.storage_tickets.values()
                if t.owner == owner and t.value.attachment_id == attachment_id
            ]
            if not previous:
                return receipt.model_copy(update={"state": "pending", "reason": "operation_unknown"})
            original = previous[0].value
            ticket = original.model_copy(
                update={
                    "ticket_id": uuid4(),
                    "nonce": uuid4(),
                    "operation": "delete",
                    "writer_id": None,
                    "generation": len(previous) + 1,
                    "expires_at": self._clock.now() + timedelta(seconds=45),
                }
            )
            self._state.storage_tickets[ticket.ticket_id] = MemoryStorageTicket(owner, ticket)
            self._state.deleting_originals.add((owner, attachment_id))
            return ticket

    def settle_cleanup(self, owner, reference):
        with self._state.lock:
            ticket = self.read_verified(owner, reference)
            if ticket.operation != "delete" or reference.result != "absent_after_delete":
                raise StaleVersionError("Cleanup needs a matching completed delete observation")
            receipt = self._cleanup.get(owner, ticket.attachment_id)
            if receipt.writer_pending or receipt.pending_writer_ids:
                raise StaleVersionError("An unresolved writer still protects this object")
            updated = receipt.model_copy(update={"state": "deleted", "reason": "removed"})
            self._cleanup.update(updated)
            return updated


class SupabaseVerifiedOriginals(SupabaseOriginalRepository):
    """Closed patient RPCs cannot manufacture storage observations or attest a write."""

    def verification_for(self,owner,task_id,attachment_id):
        self._data.check_patient(owner)
        raw=self._data.request('POST','/rest/v1/rpc/assistant_original_verification_ref',
            body={'p_task_id':str(task_id),'p_attachment_id':str(attachment_id)})
        if not isinstance(raw,dict) or set(raw) not in ({'result'},{'error'}):
            raise ProviderUnavailableError('Owned original proof lookup unavailable')
        if 'error' in raw:
            if raw['error']=='stale':
                raise StaleVersionError('Original saving or deletion state changed')
            raise ProviderUnavailableError('Independent original verification unavailable')
        try:
            proof=VerifiedOperationRef.model_validate(raw['result'])
            if proof.result!='bytes_verified':
                raise ValueError
            ticket=self.read_verified(owner,proof)
            if ticket.task_id!=task_id or ticket.attachment_id!=attachment_id or ticket.operation!='upload':
                raise ValueError
            return proof
        except (ValueError,TypeError,AttributeError):
            raise ProviderUnavailableError('Original proof differs from its actual owned upload') from None

    def _command(self, owner, kind, **values):
        self._data.check_patient(owner)

        def encode(value):
            if isinstance(value, BaseModel):
                result = value.model_dump(mode="json", exclude={"owner"})
                if isinstance(value, (OriginalAttachment, CleanupReceipt)):
                    result["object_ref"] = value.object_ref
                return result
            return str(value) if isinstance(value, UUID) else value

        result = self._data.request(
            "POST",
            "/rest/v1/rpc/assistant_original_command",
            body={"p_command": {"kind": kind, **{k: encode(v) for k, v in values.items()}}},
        )
        if not isinstance(result, dict) or set(result) not in ({"error"}, {"result"}):
            raise ProviderUnavailableError("Original verification result unavailable")
        if "error" in result:
            errors = {"not_found": NotFoundError, "stale": StaleVersionError, "duplicate": DuplicateEventError}
            code = result["error"] if isinstance(result["error"], str) else "unavailable"
            raise errors.get(code, ProviderUnavailableError)("Original operation changed; inspect its status")
        return result["result"]

    @staticmethod
    def _run_binding():
        execution = current_execution.get()
        if execution is None:
            return None
        execution.check()
        if not hasattr(execution, "write_binding"):
            raise ProviderUnavailableError("A durable run binding is required")
        return execution.write_binding

    def call(self, owner, operation, **values):
        allowed = {
            "original_get",
            "original_list",
            "original_upload",
            "original_reserve",
            "original_retry",
            "original_begin",
            "original_extract",
            "original_protect",
        }
        if operation not in allowed:
            raise ProviderUnavailableError("This command needs an independently verified original operation")
        # Native operations remain individually validated inside the fixed RPC.
        prepared = {}
        for key, value in values.items():
            if isinstance(value, BaseModel):
                prepared[key] = value.model_dump(mode="json", exclude={"owner"})
                if isinstance(value, OriginalAttachment):
                    prepared[key]["object_ref"] = value.object_ref
            else:
                prepared[key] = str(value) if isinstance(value, UUID) else value
        return self._command(owner, "native", operation=operation, input=prepared, run_binding=self._run_binding())

    def reserve_ticket(self, context, attachment_id, writer_id, *, run_binding=None):
        ticket = StorageOperationTicket.model_validate(
            self._command(
                context.owner,
                "reserve_ticket",
                context=context,
                attachment_id=attachment_id,
                writer_id=writer_id,
                run_binding=run_binding,
            )
        )
        if (
            ticket.task_id != context.task_id
            or ticket.attachment_id != attachment_id
            or ticket.writer_id != writer_id
            or ticket.operation != "upload"
            or not ticket.object_ref.startswith(str(context.owner) + "/")
        ):
            raise ProviderUnavailableError("Storage ticket binding unavailable")
        return ticket

    def claim_ticket(self, owner, ticket):
        result = self._command(owner, "claim_ticket", ticket_id=ticket.ticket_id, generation=ticket.generation)
        if result is not True:
            raise ProviderUnavailableError("Storage claim outcome unavailable")

    def read_verified(self, owner, reference):
        ticket = StorageOperationTicket.model_validate(self._command(owner, "read_verified", reference=reference))
        if (
            ticket.ticket_id != reference.ticket_id
            or ticket.generation != reference.generation
            or not ticket.object_ref.startswith(str(owner) + "/")
        ):
            raise ProviderUnavailableError("Verified ticket binding unavailable")
        return ticket

    def settle_writer(self, owner, reference):
        if self._command(owner, "settle_writer", reference=reference) is not True:
            raise ProviderUnavailableError("Writer settlement outcome unavailable")

    def publish_verified(self, context, attachment_id, reference, *, run_binding=None):
        raw = self._command(
            context.owner,
            "publish_verified",
            context=context,
            attachment_id=attachment_id,
            reference=reference,
            run_binding=run_binding,
        )
        row = self.parse(OriginalAttachment, context.owner, raw, task_id=context.task_id)
        if row.id != attachment_id or row.state != "saved":
            raise ProviderUnavailableError("Verified publication binding unavailable")
        return row

    def start_deleting(self, owner, attachment_id):
        raw = self._command(owner, "start_deleting", attachment_id=attachment_id)
        if isinstance(raw, dict) and "ticket_id" in raw:
            ticket = StorageOperationTicket.model_validate(raw)
            if (
                ticket.attachment_id != attachment_id
                or ticket.operation != "delete"
                or not ticket.object_ref.startswith(str(owner) + "/")
            ):
                raise ProviderUnavailableError("Delete ticket binding unavailable")
            return ticket
        return self.parse(CleanupReceipt, owner, raw)

    def settle_cleanup(self, owner, reference):
        return self.parse(CleanupReceipt, owner, self._command(owner, "settle_cleanup", reference=reference))
