"""Explicit local media metadata transactions; external Storage is never rolled back."""

import hashlib
import json
from contextlib import contextmanager
from copy import deepcopy

from ..contracts.assistant_workflows import (
    ActionReceipt,
    BusinessRef,
    WorkflowContext,
    WorkflowUpdate,
    validate_workflow_values,
)
from ..contracts.workflow_media_writes import (
    MEDIA_WRITE_COMMAND,
    LocalMediaFilePort,
    LocalMediaImagePort,
    MediaNativeResult,
    PrepareMediaReview,
)
from ..contracts.workflow_persistence import BusinessWriteReceipt, NativeWriteResult
from ..domain.errors import (
    DuplicateEventError,
    NotFoundError,
    ProviderUnavailableError,
    StaleVersionError,
    ValidationError,
)

CAPABILITIES = {
    "edit_photo": "gallery.photo.edit",
    "remove_photo": "gallery.photo.remove",
    "delete_photo": "gallery.photo.delete",
    "retire_photo": "gallery.photo.retire",
    "edit_pdf": "library.pdf.edit",
    "tombstone_pdf": "library.pdf.delete",
    "register_photo": "gallery.photo.add",
    "register_pdf": "library.pdf.add",
}


def media_digest(command):
    return hashlib.sha256(
        json.dumps(command.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class MemoryMediaWorkflowWrites:
    def __init__(
        self,
        *,
        state,
        store,
        clock,
        tasks,
        controls,
        gallery,
        images: LocalMediaImagePort,
        library,
        files: LocalMediaFilePort,
        drafts,
        preferences,
        copies=None,
        originals=None,
        enrollment=None,
    ):
        self._state, self._store, self._clock = state, store, clock
        self._tasks, self._controls = tasks, controls
        self._gallery, self._images, self._library, self._files = gallery, images, library, files
        self._drafts, self._preferences = drafts, preferences
        if any(value is not None for value in (copies, originals, enrollment)) and not all(
            value is not None for value in (copies, originals, enrollment)
        ):
            raise ValueError("Media registration needs explicit paired copy/original/enrollment ports")
        self._copies, self._originals, self._enrollment = copies, originals, enrollment

    def revision(self, owner):
        with self._store.clinical.lock:
            return (
                self._store.clinical.revisions.get(owner, 0)
                + self._images.media_revision(owner)
                + self._files.revision(owner)
            )

    def lookup(self, owner, action_key):
        with self._state.lock:
            return self._state.business_receipts.get((owner, action_key))

    @contextmanager
    def _transaction(self):
        maps = [
            self._state.tasks,
            self._state.controls,
            self._state.events,
            self._state.actions,
            self._state.business_receipts,
            self._state.media_commands,
            self._state.media_preparations,
            self._state.originals,
            self._state.media_registration_duplicates,
            self._state.media_original_links,
        ]
        old = [deepcopy(value) for value in maps]
        used = set(self._state.used)
        with self._images.local_transaction(), self._files.local_transaction():
            try:
                yield
            except BaseException:
                for current, before in zip(maps, old, strict=True):
                    current.clear()
                    current.update(before)
                self._state.used.clear()
                self._state.used.update(used)
                raise

    def _run_current(self, owner, binding):
        if binding.run_binding is not None:
            self._state.require_durable_run(owner, binding.run_binding, self._clock.now())

    def _current(self, owner, b):
        task, control = self._tasks.get(owner, b.task_id), self._controls.get(owner, b.task_id)
        if (
            task.revision != b.task_revision
            or control.revision != b.task_revision
            or task.capability_id != b.capability_id
            or control.capability_id != b.capability_id
            or task.capability_id not in CAPABILITIES.values()
            or task.save_mode != "allowed"
            or control.mode != "allowed"
            or control.revoked
            or control.status != "idle"
            or (task.attachment_ids and task.capability_id not in {"gallery.photo.add", "library.pdf.add"})
            or self.revision(owner) != b.expected_domain_revision
        ):
            raise StaleVersionError("The current owned media review changed")
        self._run_current(owner, b)
        prefs = self._preferences.get(owner)
        context = WorkflowContext(
            owner=owner,
            task_id=task.id,
            revision=task.revision,
            capability_id=task.capability_id,
            timezone=prefs.timezone,
            language=prefs.preferred_language,
        )
        return task, context, validate_workflow_values(task.capability_id, task.fields)

    def _upload_original(self, owner, task, values):
        if self._copies is None:
            raise ValidationError("Verified native registration is not composed")
        if values.source_attachment_id not in task.attachment_ids:
            raise StaleVersionError("Select the actual original in this owned task")
        source = self._originals.get(owner, task.id, values.source_attachment_id)
        self._state.require_original_reference(owner, source.id)
        if (
            source.state != "saved"
            or source.cleanup_pending
            or self._enrollment.get_medication(owner, values.medication_id) is None
        ):
            raise StaleVersionError("A saved owned original and medication are required")
        photo = task.capability_id == "gallery.photo.add"
        if (
            source.source_kind != ("reference_photo" if photo else "library_pdf")
            or (photo and (values.image_kind is None or not values.source_description))
            or (not photo and (values.filename is None or values.category is None))
        ):
            raise ValidationError("Complete the current typed native upload draft")
        return source

    def _advance(self, owner, task, b, ref, *, preparing, pending=False):
        self._run_current(owner, b)
        self._tasks.cas(
            owner,
            task.id,
            task.revision,
            b.action_key,
            WorkflowUpdate(
                state="awaiting_confirmation" if preparing else "outcome_unknown" if pending else "completed",
                save_mode="allowed",
                storage_state="cleanup_pending" if pending else "saved",
                fields=task.fields,
                missing_fields=(),
                attachment_ids=task.attachment_ids,
                business_refs=(ref,),
            ),
        )
        receipt = BusinessWriteReceipt(
            owner=owner,
            task_id=task.id,
            action_key=b.action_key,
            capability_id=task.capability_id,
            binding_revision=task.revision + 1,
            business_ref=ref,
            domain_revision=self.revision(owner),
            outcome="prepared" if preparing else "applied",
            recorded_at=self._clock.now(),
        )
        self._state.business_receipts[owner, b.action_key] = receipt
        return receipt

    def prepare(self, owner, command):
        command = PrepareMediaReview.model_validate(command.model_dump())
        b, digest = command.binding, media_digest(command)
        with (
            self._state.lock,
            self._store.clinical.lock,
            self._images.local_transaction(),
            self._files.local_transaction(),
        ):
            prior = self.lookup(owner, b.action_key)
            if prior is not None:
                if self._state.media_commands.get((owner, b.action_key)) != digest:
                    raise DuplicateEventError("Media preparation key already used")
                return NativeWriteResult(receipt=prior, result=None)
            task, context, values = self._current(owner, b)
            old = (
                self._state.media_preparations.get((owner, task.business_refs[0].id))
                if len(task.business_refs) == 1 and task.business_refs[0].kind == "media_review"
                else None
            )
            stale = old is not None and (old[1] < task.revision or old[3] != self.revision(owner))
            uploading = task.capability_id in {"gallery.photo.add", "library.pdf.add"}
            if not (
                task.state == "ready_for_review"
                or task.state == "awaiting_confirmation"
                and stale
                or uploading
                and task.state == "collecting"
            ):
                raise StaleVersionError("Prepare a fresh current media selection")
            if uploading:
                if values.source_attachment_id is None and len(task.attachment_ids) == 1:
                    values = values.model_copy(update={"source_attachment_id": task.attachment_ids[0]})
                    task = task.model_copy(update={"fields": values.model_dump(mode="json", exclude_none=True)})
                self._upload_original(owner, task, values)
            else:
                preparation = self._drafts.collect(context, values)
                if preparation.workflow_state != "ready_for_review":
                    raise ValidationError("Complete the current selected media draft")
            with self._transaction():
                if (owner, b.action_key) in self._state.actions:
                    raise DuplicateEventError("Media technical action already used")
                self._state.actions[owner, b.action_key] = ActionReceipt(
                    owner=owner,
                    action_key=b.action_key,
                    task_id=task.id,
                    capability_id=task.capability_id,
                    binding_revision=task.revision,
                    state="pending",
                    business_ref=b.prepared_ref,
                    safe_reason="media_prepared",
                    updated_at=self._clock.now(),
                )
                receipt = self._advance(owner, task, b, b.prepared_ref, preparing=True)
                self._state.media_commands[owner, b.action_key] = digest
                self._state.media_preparations[owner, b.prepared_ref.id] = (
                    task.id,
                    task.revision + 1,
                    task.capability_id,
                    receipt.domain_revision,
                )
                return NativeWriteResult(receipt=receipt, result=None)

    def _read_native(self, owner, command, receipt):
        ref = receipt.business_ref
        photo = command.kind.endswith("photo")
        row = (self._gallery if photo else self._library).metadata(owner, ref.id, include_deleted=True)
        if (
            self._drafts.version(row) != ref.version
            or row.medication_id != command.values.medication_id
            or (command.kind in ("delete_photo", "tombstone_pdf")) != (row.deleted_at is not None)
        ):
            raise StaleVersionError("Native media advanced; retain the original receipt")
        if command.kind in {"register_photo", "register_pdf"}:
            from ..contracts.library_files import LibraryFileUploadResult
            from ..contracts.medication_evidence import GalleryUploadResult

            ticket = self._copies.read_verified(owner, command.copy_proof)
            if (
                row.checksum != ticket.target.checksum
                or row.storage_path != ticket.target.object_ref
                or (photo and row.gallery_removed)
            ):
                raise StaleVersionError("Actual registered media differs from its verified native copy")
            duplicate = self._state.media_registration_duplicates[owner, command.binding.action_key]
            native = (
                GalleryUploadResult(photo=row, duplicate=duplicate)
                if photo
                else LibraryFileUploadResult(file=row, duplicate=duplicate)
            )
            return NativeWriteResult(receipt=receipt, result=native)
        if command.kind == "edit_photo" and (
            row.image_kind != command.values.image_kind or row.source_description != command.values.source_description
        ):
            raise StaleVersionError("Actual photo differs from the saved result")
        if command.kind == "edit_pdf" and (
            row.display_title != command.values.title
            or row.category != command.values.category
            or row.description != (command.values.description or "").strip()
        ):
            raise StaleVersionError("Actual PDF differs from the saved result")
        if command.kind == "remove_photo" and not row.gallery_removed:
            raise StaleVersionError("Actual photo has not been removed")
        if command.kind == "retire_photo" and (
            row.eligibility != "ineligible" or row.eligibility_reason != "patient_retired_reference"
        ):
            raise StaleVersionError("Actual photo has not been retired")
        return NativeWriteResult(receipt=receipt, result=row)

    def apply(self, owner, command):
        command = MEDIA_WRITE_COMMAND.validate_python(command.model_dump())
        b, digest = command.binding, media_digest(command)
        with (
            self._state.lock,
            self._store.clinical.lock,
            self._images.local_transaction(),
            self._files.local_transaction(),
        ):
            prior = self.lookup(owner, b.action_key)
            if prior is not None:
                if self._state.media_commands.get((owner, b.action_key)) != digest:
                    raise DuplicateEventError("Media action key already used for different patient inputs")
                return self._read_native(owner, command, prior)
            task, context, values = self._current(owner, b)
            if (
                task.state != "awaiting_confirmation"
                or b.prepared_ref.kind != "media_review"
                or b.prepared_ref not in task.business_refs
                or task.capability_id != CAPABILITIES[command.kind]
                or values != command.values
                or self._state.media_preparations.get((owner, b.prepared_ref.id))
                != (task.id, task.revision, task.capability_id, self.revision(owner))
            ):
                raise StaleVersionError("Media command differs from the current independent patient review")
            registering = command.kind in {"register_photo", "register_pdf"}
            if registering:
                original = self._upload_original(owner, task, values)
                ticket = self._copies.assert_current_copy(context, command.copy_proof)
                if ticket.attachment_id != original.id or ticket.target.medication_id != values.medication_id:
                    raise StaleVersionError("Native-copy proof differs from the reviewed owned original or medication")
            else:
                target = self._drafts.target(context, values)
                self._drafts.validate_target_action(context, target)
            with self._transaction():
                if registering:
                    native = (
                        self._gallery.register_verified_copy(
                            owner,
                            ticket.target,
                            image_kind=values.image_kind,
                            source_description=values.source_description,
                        )
                        if command.kind == "register_photo"
                        else self._library.register_verified_copy(
                            owner,
                            ticket.target,
                            filename=values.filename,
                            category=values.category,
                            description=values.description,
                        )
                    )
                    row = native.photo if command.kind == "register_photo" else native.file
                    ref = BusinessRef(kind="file", id=row.id, version=self._drafts.version(row))
                    if original.source_ref is None:
                        self._state.originals[owner, original.id] = original.model_copy(update={"source_ref": ref})
                    self._state.media_original_links[owner, original.id, command.kind, row.id] = ref
                    self._state.media_registration_duplicates[owner, b.action_key] = native.duplicate
                elif command.kind == "retire_photo":
                    row = self._gallery.retire(owner, target.id)
                elif command.kind.endswith("photo"):
                    row = self._gallery.apply_metadata(
                        owner,
                        target.id,
                        action=command.kind.removesuffix("_photo"),
                        expected_version=values.expected_version,
                        image_kind=values.image_kind,
                        source_description=values.source_description,
                        confirmed=True,
                    )
                elif command.kind == "edit_pdf":
                    row = self._library.update(
                        owner,
                        target.id,
                        expected_version=values.expected_version,
                        title=values.title,
                        category=values.category,
                        description=values.description or "",
                    )
                else:
                    row = self._library.tombstone(
                        owner, target.id, expected_version=values.expected_version, confirmed=True
                    )
                ref = BusinessRef(kind="file", id=row.id, version=self._drafts.version(row))
                receipt = self._advance(owner, task, b, ref, preparing=False, pending=row.cleanup_pending)
                self._state.media_commands[owner, b.action_key] = digest
                return NativeWriteResult(receipt=receipt, result=native if registering else row)


    def read(self, owner, command):
        command = MEDIA_WRITE_COMMAND.validate_python(command.model_dump())
        with (
            self._state.lock, self._store.clinical.lock,
            self._images.local_transaction(), self._files.local_transaction(),
        ):
            prior = self.lookup(owner, command.binding.action_key)
            if prior is None:
                raise NotFoundError("Actual owned media receipt unavailable")
            if self._state.media_commands.get((owner, command.binding.action_key)) != media_digest(command):
                raise DuplicateEventError("Media result belongs to different confirmed inputs")
            return self._read_native(owner, command, prior)


class SupabaseMediaWorkflowWrites:
    """Fixed same-owner RPCs; successful receipt recovery performs no new write."""

    def __init__(self, *, data, receipts, copies=None):
        self._data, self._receipts, self._copies = data, receipts, copies

    def revision(self, owner):
        self._data.check_patient(owner)
        raw = self._data.request("POST", "/rest/v1/rpc/assistant_media_revision", body={})
        if (
            not isinstance(raw, dict)
            or set(raw) != {"revision"}
            or type(raw["revision"]) is not int
            or raw["revision"] < 0
        ):
            raise ProviderUnavailableError("Current media revision unavailable")
        return raw["revision"]

    def lookup(self, owner, action_key):
        self._data.check_patient(owner)
        return self._receipts.read_receipt(owner, action_key)

    def _request(self, owner, command, preparing, *, read_only=False):
        b = command.binding
        prior = self.lookup(owner, b.action_key)
        if read_only and prior is None:
            raise NotFoundError("Actual owned media receipt unavailable")
        registering = not preparing and command.kind in {"register_photo", "register_pdf"}
        ticket = None
        if registering:
            if self._copies is None:
                raise ProviderUnavailableError("Independent media-copy proof port is not composed")
            ticket = self._copies.read_verified(owner, command.copy_proof)
            if (
                ticket.task_id != b.task_id
                or ticket.task_revision != b.task_revision
                or ticket.attachment_id != command.values.source_attachment_id
                or ticket.target.medication_id != command.values.medication_id
            ):
                raise StaleVersionError("Media copy belongs to another current patient review")
        endpoint = (
            "assistant_media_read"
            if prior is not None
            else ("assistant_media_prepare" if preparing else "assistant_media_write")
        )
        raw = self._data.request(
            "POST", "/rest/v1/rpc/" + endpoint, body={"p_command": command.model_dump(mode="json")}
        )
        if (
            not isinstance(raw, dict)
            or set(raw) not in ({"result"}, {"result", "replayed"}, {"error"})
            or ("replayed" in raw and type(raw["replayed"]) is not bool)
        ):
            raise ProviderUnavailableError("Media outcome unavailable; inspect its receipt")
        if "error" in raw:
            errors = {
                "stale": StaleVersionError,
                "duplicate": DuplicateEventError,
                "invalid": ValidationError,
                "not_found": NotFoundError,
            }
            kind = raw["error"] if isinstance(raw["error"], str) else "unavailable"
            raise errors.get(kind, ProviderUnavailableError)("Media review changed; inspect its current record")
        try:
            actual = NativeWriteResult[MediaNativeResult].model_validate(raw["result"])
            r = actual.receipt
            if (
                r.owner != owner
                or r.action_key != b.action_key
                or r.task_id != b.task_id
                or r.capability_id != b.capability_id
                or r.binding_revision != b.task_revision + 1
                or r.domain_revision < b.expected_domain_revision
                or r.outcome != ("prepared" if preparing else "applied")
                or (prior is not None and (r != prior or raw.get("replayed") is not True))
            ):
                raise ValueError
            if preparing:
                if actual.result is not None or r.business_ref != b.prepared_ref:
                    raise ValueError
            else:
                self._validate_native(owner, command, actual, ticket)
            return actual
        except (ValueError, TypeError, AttributeError):
            raise ProviderUnavailableError(
                "Media result binding unavailable; inspect its actual native receipt"
            ) from None

    @staticmethod
    def _validate_native(owner, command, actual, ticket):
        from ..contracts.library_files import LibraryFileDTO, LibraryFileUploadResult
        from ..contracts.medication_evidence import GalleryUploadResult, MedicationImage

        registering = command.kind in {"register_photo", "register_pdf"}
        photo = command.kind.endswith("photo")
        native = actual.result
        if registering:
            if not isinstance(native, GalleryUploadResult if photo else LibraryFileUploadResult):
                raise ValueError
            row = native.photo if photo else native.file
        else:
            row = native
        if not isinstance(row, MedicationImage if photo else LibraryFileDTO):
            raise ValueError
        version = row.metadata_version if photo else row.version
        ref = actual.receipt.business_ref
        if (
            row.patient_id != owner
            or row.medication_id != command.values.medication_id
            or ref != BusinessRef(kind="file", id=row.id, version=version)
        ):
            raise ValueError
        if registering:
            if (
                row.deleted_at is not None
                or row.storage_path != ticket.target.object_ref
                or row.checksum != ticket.target.checksum
                or (photo and row.gallery_removed)
            ):
                raise ValueError
            if not native.duplicate and (row.id != ticket.target.native_id or version != 1):
                raise ValueError
            if not native.duplicate:
                if photo:
                    if (
                        row.image_kind != command.values.image_kind
                        or row.source_description != command.values.source_description
                        or row.eligibility != "associated"
                        or not row.reviewed
                    ):
                        raise ValueError
                else:
                    from ..application.library_files import clean_filename

                    name = clean_filename(command.values.filename)
                    if (
                        row.original_filename != name
                        or row.display_title != (name[:-4][:160] or "Medication document")
                        or row.category != command.values.category
                        or row.description != command.values.description.strip()
                        or row.byte_size != ticket.target.byte_size
                    ):
                        raise ValueError
            return
        target = command.values.image_id if photo else command.values.file_id
        allowed_versions = {command.values.expected_version + 1}
        if command.kind == "retire_photo":
            allowed_versions.add(command.values.expected_version)
        if row.id != target or version not in allowed_versions:
            raise ValueError
        deleting = command.kind in {"delete_photo", "tombstone_pdf"}
        if deleting != (row.deleted_at is not None):
            raise ValueError
        if command.kind == "edit_photo" and (
            row.image_kind != command.values.image_kind or row.source_description != command.values.source_description
        ):
            raise ValueError
        if command.kind == "edit_pdf" and (
            row.display_title != command.values.title
            or row.category != command.values.category
            or row.description != (command.values.description or "").strip()
        ):
            raise ValueError
        if command.kind == "remove_photo" and not row.gallery_removed:
            raise ValueError
        if command.kind == "retire_photo" and (
            row.eligibility != "ineligible" or row.eligibility_reason != "patient_retired_reference"
        ):
            raise ValueError

    def prepare(self, owner, command):
        self._data.check_patient(owner)
        return self._request(owner, PrepareMediaReview.model_validate(command.model_dump()), True)

    def apply(self, owner, command):
        self._data.check_patient(owner)
        return self._request(owner, MEDIA_WRITE_COMMAND.validate_python(command.model_dump()), False)

    def read(self, owner, command):
        self._data.check_patient(owner)
        return self._request(owner, MEDIA_WRITE_COMMAND.validate_python(command.model_dump()), False, read_only=True)
