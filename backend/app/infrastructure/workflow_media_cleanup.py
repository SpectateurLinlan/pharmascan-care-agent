"""Local native deletion fences and atomic acknowledgement; no Storage I/O here."""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4, uuid5

from ..contracts.assistant_workflows import WorkflowUpdate
from ..contracts.workflow_media_cleanup import (
    MEDIA_CLEANUP_DECISION,
    MediaCleanupSettlement,
    MediaDeleteObservation,
    MediaDeleteTicket,
    VerifiedMediaDeleteRef,
)
from ..contracts.workflow_media_writes import MediaNativeResult
from ..contracts.workflow_persistence import NativeWriteResult
from ..domain.errors import (
    DuplicateEventError,
    NotFoundError,
    ProviderUnavailableError,
    StaleVersionError,
    ValidationError,
)


@dataclass
class MemoryMediaDeleteTicket:
    value: MediaDeleteTicket
    state: str = "issued"


class MemoryMediaDeleteVerifier:
    """Technical metadata only; never queries or acknowledges a clinical record."""

    def __init__(self, *, state, clock):
        self._state, self._clock = state, clock

    def record_media_delete(self, observation, *, timeout_seconds):
        observation = MediaDeleteObservation.model_validate(observation)
        with self._state.lock:
            row = self._state.media_delete_tickets.get(observation.ticket_id)
            if row is None or row.value.nonce != observation.nonce or row.value.generation != observation.generation:
                raise NotFoundError("Matching native delete ticket required")
            ticket = row.value
            if observation.result == "absent_after_delete" and observation.bucket_id != ticket.bucket_id:
                raise StaleVersionError("Native absence was observed in another storage bucket")
            if row.state == "issued" or (ticket.owner, ticket.object_ref) not in self._state.deleting_media_objects:
                raise StaleVersionError("A claimed persistent native deletion exclusion is required")
            for prior in self._state.media_delete_verifications.values():
                if prior.ticket_id != ticket.ticket_id:
                    continue
                if prior.result == observation.result:
                    return prior
                if prior.result == "absent_after_delete":
                    return prior
            proof = VerifiedMediaDeleteRef(
                ticket_id=ticket.ticket_id,
                verification_id=uuid4(),
                generation=ticket.generation,
                result=observation.result,
            )
            self._state.media_delete_verifications[proof.verification_id] = proof
            row.state = "settled" if proof.result == "absent_after_delete" else "unknown"
            return proof


class MemoryMediaCleanupTickets:
    def __init__(self, *, state, store, clock, tasks, controls, gallery, library, images, files):
        self._state, self._store, self._clock = state, store, clock
        self._tasks, self._controls = tasks, controls
        self._gallery, self._library, self._images, self._files = gallery, library, images, files

    def _native(self, owner, receipt):
        if (
            receipt.owner != owner
            or receipt.outcome != "applied"
            or receipt.business_ref.kind != "file"
            or receipt.capability_id not in {"gallery.photo.delete", "library.pdf.delete"}
        ):
            raise StaleVersionError("Actual independently confirmed native deletion receipt required")
        photo = receipt.capability_id == "gallery.photo.delete"
        row = (self._gallery if photo else self._library).metadata(owner, receipt.business_ref.id, include_deleted=True)
        version = row.metadata_version if photo else row.version
        if row.deleted_at is None or version != receipt.business_ref.version:
            raise StaleVersionError("Native deletion record changed after patient confirmation")
        if (photo and row.source_id is not None) or (not photo and (row.source_document_id or row.regimen_version_id)):
            raise ValidationError("Protected native evidence cannot be physically deleted")
        references = self._images.list(owner, "images") if photo else self._files.references(owner, row.storage_path)
        if any(other.id != row.id and other.storage_path == row.storage_path for other in references):
            raise ValidationError("Shared native media cannot be physically deleted")
        return row, photo

    def _receipt(self, owner, action_key):
        receipt = self._state.business_receipts.get((owner, action_key))
        if receipt is None:
            raise NotFoundError("Owned native deletion receipt unavailable")
        return receipt

    def _writers_closed(self, owner, path):
        if any(
            row.value.target.owner == owner and row.value.target.object_ref == path and row.state != "settled"
            for row in self._state.media_storage_tickets.values()
        ):
            raise StaleVersionError("Native object has an unresolved copy writer")

    def start(self, owner, action_key):
        with (
            self._state.lock,
            self._store.clinical.lock,
            self._images.local_transaction(),
            self._files.local_transaction(),
        ):
            receipt = self._receipt(owner, action_key)
            row, photo = self._native(owner, receipt)
            settlement = self._state.media_cleanup_settlements.get((owner, action_key))
            if settlement is not None:
                if row.cleanup_pending or settlement.native_ref != receipt.business_ref:
                    raise StaleVersionError("Native cleanup result changed; retain its historical settlement")
                return NativeWriteResult(receipt=receipt, result=row)
            if not row.cleanup_pending:
                raise StaleVersionError("No independent physical deletion settlement is available")
            self._writers_closed(owner, row.storage_path)
            prior = next(
                (
                    value
                    for value in self._state.media_delete_tickets.values()
                    if value.value.owner == owner and value.value.object_ref == row.storage_path
                ),
                None,
            )
            if prior is not None:
                if prior.value.action_key != action_key:
                    raise StaleVersionError("Native object is bound to another deletion")
                proof = next(
                    (
                        proof
                        for proof in self._state.media_delete_verifications.values()
                        if proof.ticket_id == prior.value.ticket_id and proof.result == "absent_after_delete"
                    ),
                    None,
                )
                if proof is not None:
                    return proof
                if prior.state != "issued":
                    raise StaleVersionError("Native deletion remains unresolved; never replay its request")
                return prior.value
            ticket = MediaDeleteTicket(
                ticket_id=uuid4(),
                nonce=uuid4(),
                generation=1,
                owner=owner,
                task_id=receipt.task_id,
                task_revision=receipt.binding_revision,
                action_key=action_key,
                media_kind="photo" if photo else "pdf",
                medication_id=row.medication_id,
                native_ref=receipt.business_ref,
                object_ref=row.storage_path,
                checksum=row.checksum,
                expires_at=self._clock.now() + timedelta(seconds=45),
            )
            self._state.deleting_media_objects.add((owner, ticket.object_ref))
            self._state.media_delete_tickets[ticket.ticket_id] = MemoryMediaDeleteTicket(ticket)
            return ticket

    def claim(self, owner, ticket):
        with (
            self._state.lock,
            self._store.clinical.lock,
            self._images.local_transaction(),
            self._files.local_transaction(),
        ):
            stored = self._state.media_delete_tickets.get(ticket.ticket_id)
            if stored is None or stored.value != ticket or ticket.owner != owner:
                raise NotFoundError("Owned actual native delete ticket required")
            if stored.state != "issued" or self._clock.now() >= ticket.expires_at:
                raise StaleVersionError("Native delete operation cannot be restarted")
            row, _photo = self._native(owner, self._receipt(owner, ticket.action_key))
            if not row.cleanup_pending or row.storage_path != ticket.object_ref or row.checksum != ticket.checksum:
                raise StaleVersionError("Native object differs from this deletion")
            self._writers_closed(owner, ticket.object_ref)
            if (owner, ticket.object_ref) not in self._state.deleting_media_objects:
                raise StaleVersionError("Persistent native deleting exclusion is missing")
            stored.state = "inflight"

    @contextmanager
    def _transaction(self):
        maps = [self._state.tasks, self._state.controls, self._state.events, self._state.media_cleanup_settlements]
        backups = [deepcopy(value) for value in maps]
        used = set(self._state.used)
        with self._images.local_transaction(), self._files.local_transaction():
            try:
                yield
            except BaseException:
                for current, old in zip(maps, backups, strict=True):
                    current.clear()
                    current.update(old)
                self._state.used.clear()
                self._state.used.update(used)
                raise

    def settle(self, owner, proof):
        proof = VerifiedMediaDeleteRef.model_validate(proof.model_dump())
        with (
            self._state.lock,
            self._store.clinical.lock,
            self._images.local_transaction(),
            self._files.local_transaction(),
        ):
            stored = self._state.media_delete_tickets.get(proof.ticket_id)
            if (
                self._state.media_delete_verifications.get(proof.verification_id) != proof
                or stored is None
                or stored.value.owner != owner
                or stored.value.generation != proof.generation
                or proof.result != "absent_after_delete"
            ):
                raise ProviderUnavailableError("Actual independently observed native deletion proof required")
            ticket = stored.value
            receipt = self._receipt(owner, ticket.action_key)
            row, photo = self._native(owner, receipt)
            if (
                owner,
                ticket.object_ref,
            ) not in self._state.deleting_media_objects or row.storage_path != ticket.object_ref:
                raise StaleVersionError("Native deletion exclusion or target changed")
            self._writers_closed(owner, ticket.object_ref)
            prior = self._state.media_cleanup_settlements.get((owner, ticket.action_key))
            if prior is not None:
                if row.cleanup_pending or prior.proof != proof:
                    raise DuplicateEventError("Native deletion has a different settlement")
                return NativeWriteResult(receipt=receipt, result=row)
            with self._transaction():
                if photo:
                    self._images.acknowledge_image_cleanup(owner, row.id)
                else:
                    self._files.acknowledge_cleanup(owner, row.id)
                try:
                    task = self._tasks.get(owner, receipt.task_id)
                except NotFoundError:
                    task = None  # Revocation may clear content; technical settlement must not restore it.
                control = self._controls.get(owner, receipt.task_id)
                if (
                    task is not None
                    and task.revision == receipt.binding_revision
                    and control.revision == task.revision
                    and task.state == "outcome_unknown"
                    and task.capability_id == receipt.capability_id
                    and receipt.business_ref in task.business_refs
                    and task.save_mode == "allowed"
                    and control.mode == "allowed"
                    and not control.revoked
                    and control.status == "idle"
                ):
                    self._tasks.cas(
                        owner,
                        task.id,
                        task.revision,
                        uuid5(ticket.ticket_id, "cleanup-settlement"),
                        WorkflowUpdate(
                            state="completed",
                            save_mode="allowed",
                            storage_state="saved",
                            fields=task.fields,
                            missing_fields=(),
                            attachment_ids=task.attachment_ids,
                            business_refs=task.business_refs,
                        ),
                    )
                self._state.media_cleanup_settlements[owner, ticket.action_key] = MediaCleanupSettlement(
                    owner=owner,
                    action_key=ticket.action_key,
                    native_ref=receipt.business_ref,
                    proof=proof,
                    recorded_at=self._clock.now(),
                )
                actual = (self._gallery if photo else self._library).metadata(owner, row.id, include_deleted=True)
                return NativeWriteResult(receipt=receipt, result=actual)


class SupabaseMediaCleanupTickets:
    """Normal owned metadata commands, with no external delete or proof-writing RPC."""

    def __init__(self, *, data, receipts):
        self._data, self._receipts = data, receipts

    def _receipt(self, owner, action_key):
        self._data.check_patient(owner)
        receipt = self._receipts.read_receipt(owner, action_key)
        if receipt is None:
            raise NotFoundError("Owned confirmed native deletion receipt unavailable")
        if (
            receipt.capability_id not in {"gallery.photo.delete", "library.pdf.delete"}
            or receipt.business_ref.kind != "file"
            or receipt.outcome != "applied"
        ):
            raise StaleVersionError("A confirmed native tombstone is required for cleanup")
        return receipt

    def _call(self, owner, kind, **values):
        self._data.check_patient(owner)
        body = {"kind": kind} | values
        raw = self._data.request("POST", "/rest/v1/rpc/assistant_media_cleanup_command", body={"p_command": body})
        if not isinstance(raw, dict) or set(raw) not in ({"result"}, {"error"}):
            raise ProviderUnavailableError("Native cleanup outcome unavailable; inspect its actual proof")
        if "error" in raw:
            errors = {
                "stale": StaleVersionError,
                "duplicate": DuplicateEventError,
                "not_found": NotFoundError,
                "invalid": ValidationError,
            }
            code = raw["error"] if isinstance(raw["error"], str) else "unavailable"
            raise errors.get(code, ProviderUnavailableError)("Native cleanup binding unavailable")
        return raw["result"]

    @staticmethod
    def _validate_native(owner, result, receipt):
        from ..contracts.library_files import LibraryFileDTO
        from ..contracts.medication_evidence import MedicationImage

        row = result.result
        photo = receipt.capability_id == "gallery.photo.delete"
        if not isinstance(row, MedicationImage if photo else LibraryFileDTO):
            raise ValueError
        version = row.metadata_version if photo else row.version
        if (
            result.receipt != receipt
            or row.patient_id != owner
            or row.id != receipt.business_ref.id
            or version != receipt.business_ref.version
            or row.deleted_at is None
            or row.cleanup_pending
        ):
            raise ValueError
        expected = (
            f"{owner}/{row.medication_id}/{row.checksum}.png"
            if photo
            else f"{owner}/library/{row.medication_id}/{row.checksum}.pdf"
        )
        if row.storage_path != expected:
            raise ValueError
        return result

    def start(self, owner, action_key):
        receipt = self._receipt(owner, action_key)
        raw = self._call(owner, "start", action_key=str(action_key))
        try:
            decision = MEDIA_CLEANUP_DECISION.validate_python(raw)
            if decision.kind == "settled":
                return self._validate_native(owner, decision.result, receipt)
            ticket = decision.ticket
            if (
                ticket.owner != owner
                or ticket.action_key != action_key
                or ticket.task_id != receipt.task_id
                or ticket.task_revision != receipt.binding_revision
                or ticket.native_ref != receipt.business_ref
                or (ticket.media_kind == "photo") != (receipt.capability_id == "gallery.photo.delete")
            ):
                raise ValueError
            return ticket if decision.kind == "ticket" else decision.proof
        except (ValueError, TypeError, AttributeError):
            raise ProviderUnavailableError("Native cleanup decision differs from its actual deletion receipt") from None

    def claim(self, owner, ticket):
        self._data.check_patient(owner)
        ticket = MediaDeleteTicket.model_validate(ticket.model_dump())
        if ticket.owner != owner:
            raise NotFoundError("Owned native delete ticket required")
        result = self._call(
            owner, "claim", ticket_id=str(ticket.ticket_id), nonce=str(ticket.nonce), generation=ticket.generation
        )
        if result is not True:
            raise ProviderUnavailableError("Native delete operation was not claimed")

    def settle(self, owner, proof):
        self._data.check_patient(owner)
        proof = VerifiedMediaDeleteRef.model_validate(proof.model_dump())
        if proof.result != "absent_after_delete":
            raise StaleVersionError("Unresolved native deletion cannot be acknowledged")
        raw = self._call(owner, "settle", reference=proof.model_dump(mode="json"))
        try:
            result = NativeWriteResult[MediaNativeResult].model_validate(raw)
            if result.receipt.owner != owner:
                raise ValueError
            receipt = self._receipt(owner, result.receipt.action_key)
            return self._validate_native(owner, result, receipt)
        except (ValueError, TypeError, AttributeError):
            raise ProviderUnavailableError("Actual native cleanup acknowledgement binding unavailable") from None
