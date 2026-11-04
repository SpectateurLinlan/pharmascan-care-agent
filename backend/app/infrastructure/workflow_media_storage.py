"""Local technical copy tickets; no clinical service or registration in verifier."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from ..contracts.workflow_media_storage import (
    MediaCopyTarget,
    MediaStorageObservation,
    MediaStorageTicket,
    VerifiedMediaOperationRef,
)
from ..contracts.workflow_persistence import RunWriteBinding
from ..domain.errors import (
    DuplicateEventError,
    NotFoundError,
    ProviderUnavailableError,
    StaleVersionError,
    ValidationError,
)


@dataclass
class MemoryMediaTicket:
    value: MediaStorageTicket
    run_binding: RunWriteBinding | None = None
    state: str = "issued"


class MemoryMediaCopyVerifier:
    """Restricted-role analogue: consumes only issued technical metadata."""

    def __init__(self, *, state, clock):
        self._state, self._clock = state, clock

    def record_media_storage(self, observation, *, timeout_seconds):
        observation = MediaStorageObservation.model_validate(observation)
        with self._state.lock:
            row = self._state.media_storage_tickets.get(observation.ticket_id)
            if row is None or row.value.nonce != observation.nonce or row.value.generation != observation.generation:
                raise NotFoundError("Matching native-copy ticket required")
            if row.state == "issued":
                raise StaleVersionError("Native-copy operation was never claimed")
            ticket = row.value
            if observation.result == "bytes_verified" and (
                observation.source_checksum != ticket.source_checksum
                or observation.checksum != ticket.target.checksum
                or observation.byte_size != ticket.target.byte_size
                or observation.bucket_id != ticket.target.bucket_id
            ):
                raise StaleVersionError("Actual native/source bytes differ from the issued copy")
            for prior in self._state.media_storage_verifications.values():
                if prior.ticket_id != ticket.ticket_id:
                    continue
                if prior.result == observation.result:
                    return prior
                if prior.result != "outcome_unknown" and observation.result != "outcome_unknown":
                    raise DuplicateEventError("Native-copy operation already settled differently")
            proof = VerifiedMediaOperationRef(
                ticket_id=ticket.ticket_id,
                verification_id=uuid4(),
                generation=ticket.generation,
                result=observation.result,
            )
            self._state.media_storage_verifications[proof.verification_id] = proof
            if observation.result != "outcome_unknown":
                row.state = "settled"
            elif row.state != "settled":
                row.state = "unknown"
            return proof


class MemoryMediaCopyTickets:
    def __init__(self, *, state, clock, originals, controls):
        self._state, self._clock, self._originals, self._controls = state, clock, originals, controls

    def recover(self, context, attachment_id, target):
        target = MediaCopyTarget.model_validate(target.model_dump())
        if target.owner != context.owner or context.save_mode != "allowed":
            raise StaleVersionError("Use the owned saved native-copy scope")
        with self._state.lock:
            self._originals.get(context.owner, context.task_id, attachment_id)
            rows = [row.value for row in self._state.media_storage_tickets.values()
                    if row.value.target == target and row.value.task_id == context.task_id
                    and row.value.task_revision == context.revision
                    and row.value.capability_id == context.capability_id and row.value.attachment_id == attachment_id]
            proofs = [proof for proof in self._state.media_storage_verifications.values()
                      if proof.result == "bytes_verified" and any(
                          proof.ticket_id == row.ticket_id and proof.generation == row.generation for row in rows)]
            if proofs:
                return min(proofs, key=lambda proof: proof.generation)
            if rows:
                raise StaleVersionError("Native-copy outcome needs recovery; never repeat an issued writer")
            return None

    def _current(self, context, attachment_id, target, run_binding=None):
        control = self._controls.get(context.owner, context.task_id)
        if (
            context.save_mode != "allowed"
            or control.mode != "allowed"
            or control.revoked
            or control.revision != context.revision
            or control.capability_id != context.capability_id
            or target.owner != context.owner
        ):
            raise StaleVersionError("Native-copy saving permission changed")
        if run_binding is not None:
            self._state.require_durable_run(context.owner, run_binding, self._clock.now())
        self._state.require_original_reference(context.owner, attachment_id)
        if (context.owner, target.object_ref) in self._state.deleting_media_objects:
            raise StaleVersionError("Native object deletion is unresolved; this key cannot be reused")
        source = self._originals.get(context.owner, context.task_id, attachment_id)
        if source.state != "saved" or source.cleanup_pending:
            raise StaleVersionError("A saved owned original is required for native copying")
        if (target.media_kind == "pdf") != (source.content_type == "application/pdf"):
            raise StaleVersionError("Original media type differs from this native copy")
        return source

    def reserve(self, context, attachment_id, writer_id, target, *, run_binding=None):
        target = MediaCopyTarget.model_validate(target.model_dump())
        with self._state.lock:
            source = self._current(context, attachment_id, target, run_binding)
            prior = [
                row.value
                for row in self._state.media_storage_tickets.values()
                if row.value.target.owner == context.owner and row.value.target.object_ref == target.object_ref
            ]
            if any(row.writer_id == writer_id for row in prior):
                raise DuplicateEventError("Copy writer already issued; inspect its proof")
            if len([row for row in prior if self._state.media_storage_tickets[row.ticket_id].state != "settled"]) >= 64:
                raise StaleVersionError("Unresolved copy writers require recovery before starting more")
            ticket = MediaStorageTicket(
                ticket_id=uuid4(),
                nonce=uuid4(),
                task_id=context.task_id,
                task_revision=context.revision,
                capability_id=context.capability_id,
                attachment_id=attachment_id,
                writer_id=writer_id,
                generation=len(prior) + 1,
                source_checksum=source.original_checksum,
                source_byte_size=source.byte_size,
                target=target,
                expires_at=self._clock.now() + timedelta(seconds=45),
            )
            self._state.media_storage_tickets[ticket.ticket_id] = MemoryMediaTicket(ticket, run_binding)
            return ticket

    def claim(self, owner, ticket):
        from ..contracts.assistant_workflows import WorkflowContext

        with self._state.lock:
            row = self._state.media_storage_tickets.get(ticket.ticket_id)
            if row is None or row.value != ticket or ticket.target.owner != owner:
                raise NotFoundError("Owned native-copy ticket required")
            if row.state != "issued" or self._clock.now() >= ticket.expires_at:
                raise StaleVersionError("Native-copy ticket cannot be restarted")
            context = WorkflowContext(
                owner=owner,
                task_id=ticket.task_id,
                revision=ticket.task_revision,
                capability_id=ticket.capability_id,
                save_mode="allowed",
                language="en",
                timezone="UTC",
            )
            self._current(context, ticket.attachment_id, ticket.target, row.run_binding)
            row.state = "inflight"

    def read_verified(self, owner, reference):
        reference = VerifiedMediaOperationRef.model_validate(reference.model_dump())
        with self._state.lock:
            proof = self._state.media_storage_verifications.get(reference.verification_id)
            row = self._state.media_storage_tickets.get(reference.ticket_id)
            if proof != reference or row is None or row.value.target.owner != owner:
                raise ProviderUnavailableError("Matching independent native-copy proof unavailable")
            return row.value

    def assert_current_copy(self, context, reference):
        with self._state.lock:
            ticket = self.read_verified(context.owner, reference)
            if (
                reference.result != "bytes_verified"
                or ticket.task_id != context.task_id
                or ticket.task_revision != context.revision
                or ticket.capability_id != context.capability_id
            ):
                raise StaleVersionError("Copy proof belongs to another current patient review")
            # Technical proof survives its chat run. The current caller's run,
            # if any, is fenced separately by the native transaction boundary.
            self._current(context, ticket.attachment_id, ticket.target)
            return ticket


class SupabaseMediaCopyTickets:
    """Normal patient identity issues/reads tickets, never verification results."""

    def __init__(self, *, data):
        self._data = data

    def recover(self, context, attachment_id, target):
        self._data.check_patient(context.owner)
        target = MediaCopyTarget.model_validate(target.model_dump())
        if target.owner != context.owner or context.save_mode != "allowed":
            raise StaleVersionError("Use the owned saved native-copy scope")
        raw = self._data.request("POST", "/rest/v1/rpc/assistant_media_copy_command", body={"p_command": {
            "kind": "recover", "context": context.model_dump(mode="json"),
            "attachment_id": str(attachment_id), "target": target.model_dump(mode="json"),
        }})
        if not isinstance(raw, dict) or set(raw) != {"result"}:
            if isinstance(raw, dict) and raw.get("error") == "stale":
                raise StaleVersionError("Native-copy outcome needs recovery; never repeat an issued writer")
            raise ProviderUnavailableError("Owned native-copy recovery unavailable")
        if raw["result"] is None:
            return None
        try:
            proof = VerifiedMediaOperationRef.model_validate(raw["result"])
        except (ValueError, TypeError):
            raise ProviderUnavailableError("Actual native-copy proof unavailable") from None
        ticket = self.read_verified(context.owner, proof)
        if (proof.result != "bytes_verified" or ticket.task_id != context.task_id
                or ticket.task_revision != context.revision or ticket.capability_id != context.capability_id
                or ticket.attachment_id != attachment_id or ticket.target != target):
            raise ProviderUnavailableError("Recovered native-copy proof belongs to another review")
        return proof

    def _call(self, owner, kind, **values):
        self._data.check_patient(owner)
        body = {"kind": kind}
        for key, value in values.items():
            body[key] = (
                value.model_dump(mode="json")
                if hasattr(value, "model_dump")
                else str(value)
                if isinstance(value, UUID)
                else value
            )
        raw = self._data.request("POST", "/rest/v1/rpc/assistant_media_copy_command", body={"p_command": body})
        if not isinstance(raw, dict) or set(raw) not in ({"result"}, {"error"}):
            raise ProviderUnavailableError("Native-copy outcome unavailable; inspect its ticket")
        if "error" in raw:
            errors = {
                "stale": StaleVersionError,
                "duplicate": DuplicateEventError,
                "not_found": NotFoundError,
                "invalid": ValidationError,
            }
            code = raw["error"] if isinstance(raw["error"], str) else "unavailable"
            raise errors.get(code, ProviderUnavailableError)(
                "Native-copy binding unavailable; inspect its actual proof"
            )
        if kind == "claim":
            if raw["result"] is not True:
                raise ProviderUnavailableError("Native-copy operation was not claimed")
            return None
        try:
            ticket = MediaStorageTicket.model_validate(raw["result"])
            if ticket.target.owner != owner:
                raise ValueError
            return ticket
        except (ValueError, TypeError):
            raise ProviderUnavailableError("Owned native-copy ticket unavailable") from None

    def reserve(self, context, attachment_id, writer_id, target, *, run_binding=None):
        self._data.check_patient(context.owner)
        target = MediaCopyTarget.model_validate(target.model_dump())
        if target.owner != context.owner:
            raise StaleVersionError("Native copy belongs to another owner")
        ticket = self._call(
            context.owner,
            "reserve",
            context=context,
            attachment_id=attachment_id,
            writer_id=writer_id,
            target=target,
            run_binding=run_binding,
        )
        if (
            ticket.task_id != context.task_id
            or ticket.task_revision != context.revision
            or ticket.capability_id != context.capability_id
            or ticket.attachment_id != attachment_id
            or ticket.writer_id != writer_id
            or ticket.target != target
        ):
            raise ProviderUnavailableError("Native-copy ticket does not match the current request")
        return ticket

    def claim(self, owner, ticket):
        self._data.check_patient(owner)
        ticket = MediaStorageTicket.model_validate(ticket.model_dump())
        if ticket.target.owner != owner:
            raise StaleVersionError("Native copy belongs to another owner")
        return self._call(owner, "claim", ticket_id=ticket.ticket_id, nonce=ticket.nonce, generation=ticket.generation)

    def read_verified(self, owner, reference):
        reference = VerifiedMediaOperationRef.model_validate(reference.model_dump())
        ticket = self._call(owner, "read_verified", reference=reference)
        if ticket.ticket_id != reference.ticket_id or ticket.generation != reference.generation:
            raise ProviderUnavailableError("Native-copy proof differs from its actual ticket")
        return ticket

    def assert_current_copy(self, context, reference):
        reference = VerifiedMediaOperationRef.model_validate(reference.model_dump())
        ticket = self._call(context.owner, "assert_current", context=context, reference=reference)
        if (
            ticket.ticket_id != reference.ticket_id
            or ticket.generation != reference.generation
            or ticket.task_id != context.task_id
            or ticket.task_revision != context.revision
            or ticket.capability_id != context.capability_id
            or reference.result != "bytes_verified"
        ):
            raise ProviderUnavailableError("Native-copy proof does not match this patient review")
        return ticket
