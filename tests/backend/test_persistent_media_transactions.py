"""DEMO_ONLY native media writes; no provider, cloud or live database."""

import importlib
from uuid import UUID, uuid4

import pytest
from app.contracts.assistant_workflows import BusinessRef
from app.contracts.workflow_persistence import WorkflowWriteBinding
from app.domain.errors import StaleVersionError

from .test_workflow_media import seed_media
from .test_workflow_media_lifecycle import fields


def api(name):
    return getattr(importlib.import_module("app.contracts.workflow_media_writes"), name)


def harness(h, copies=None):
    cls = importlib.import_module("app.infrastructure.workflow_media_writes").MemoryMediaWorkflowWrites
    workflows = h.container.assistant_workflows
    return cls(
        state=workflows._repository._state,
        store=h.container.store,
        clock=h.clock,
        tasks=workflows._repository,
        controls=workflows._controls,
        gallery=h.container.gallery,
        images=h.container.gallery._repo,
        library=h.container.library_files,
        files=h.container.library_files._repo,
        drafts=workflows._adapters["gallery.photo.edit"].drafts,
        preferences=h.container.preferences,
        copies=copies,
        originals=h.container.assistant_attachments._repository if copies else None,
        enrollment=h.container.enrollment if copies else None,
    )


def command(h, capability):
    owner = h.owner_ids["A"]
    med, photo, pdf = seed_media(h)
    view = h.start(capability, fields(capability, med, photo, pdf))
    port = harness(h)
    action = uuid4()
    b = WorkflowWriteBinding(
        task_id=UUID(view["task_id"]),
        task_revision=view["revision"],
        capability_id=capability,
        action_key=action,
        prepared_ref=BusinessRef(kind="media_review", id=action, version=1),
        expected_domain_revision=port.revision(owner),
    )
    prepared = port.prepare(owner, api("PrepareMediaReview")(binding=b))
    assert prepared.receipt.outcome == "prepared" and prepared.result is None
    task = h.container.assistant_workflows._repository.get(owner, b.task_id)
    value_model = api("PhotoChangeFields") if capability.startswith("gallery.") else api("PdfChangeFields")
    value = value_model.model_validate(task.fields)
    kind = {
        "gallery.photo.edit": "EditPhoto",
        "gallery.photo.remove": "RemovePhoto",
        "gallery.photo.delete": "DeletePhoto",
        "gallery.photo.retire": "RetirePhoto",
        "library.pdf.edit": "EditPdf",
        "library.pdf.delete": "TombstonePdf",
    }[capability]
    b = b.model_copy(
        update={"action_key": uuid4(), "task_revision": task.revision, "expected_domain_revision": port.revision(owner)}
    )
    return port, api(kind)(binding=b, values=value, confirmed=True)


@pytest.mark.parametrize(
    "capability", ["gallery.photo.edit", "gallery.photo.remove", "gallery.photo.retire", "library.pdf.edit"]
)
def test_media_change_is_atomic_with_actual_native_version_and_receipt(workflow, capability):
    h, owner = workflow, workflow.owner_ids["A"]
    port, cmd = command(h, capability)
    applied = port.apply(owner, cmd)
    row = applied.result
    version = getattr(row, "metadata_version", None) or row.version
    assert version == 2 and applied.receipt.business_ref == BusinessRef(kind="file", id=row.id, version=2)
    assert port.apply(owner, cmd) == applied
    assert h.container.assistant_workflows._repository.get(owner, cmd.binding.task_id).state == "completed"


@pytest.mark.parametrize("capability", ["gallery.photo.delete", "library.pdf.delete"])
def test_tombstone_receipt_does_not_claim_physical_deletion(workflow, monkeypatch, capability):
    h, owner = workflow, workflow.owner_ids["A"]
    port, cmd = command(h, capability)
    service = h.container.gallery if capability.startswith("gallery.") else h.container.library_files
    target = cmd.values.image_id if capability.startswith("gallery.") else cmd.values.file_id
    original = service.metadata(owner, target)
    before_bytes = service._storage.get(original.storage_path)

    def no_io(*args, **kwargs):
        raise AssertionError("Native metadata transaction cannot perform Storage DELETE")

    monkeypatch.setattr(service._storage, "delete", no_io)
    result = port.apply(owner, cmd)
    assert result.result.deleted_at is not None and result.result.cleanup_pending
    assert service._storage.get(original.storage_path) == before_bytes
    assert port.lookup(owner, cmd.binding.action_key) == result.receipt
    assert h.container.assistant_workflows._repository.get(owner, cmd.binding.task_id).state == "outcome_unknown"


def test_stale_media_selection_keeps_inputs_and_refuses_a_new_native_write(workflow):
    h, owner = workflow, workflow.owner_ids["A"]
    port, cmd = command(h, "library.pdf.edit")
    h.container.library_files.update(
        owner,
        cmd.values.file_id,
        expected_version=1,
        title="DEMO independent edit",
        category="other",
        description="DEMO native change",
    )
    task = h.container.assistant_workflows._repository.get(owner, cmd.binding.task_id)
    with pytest.raises(StaleVersionError):
        port.apply(owner, cmd)
    assert h.container.assistant_workflows._repository.get(owner, cmd.binding.task_id) == task
    assert h.container.library_files.metadata(owner, cmd.values.file_id).display_title == "DEMO independent edit"
    assert port.lookup(owner, cmd.binding.action_key) is None


@pytest.mark.parametrize("capability", ["gallery.photo.edit", "library.pdf.edit"])
def test_failed_task_advance_restores_native_media_and_native_audit(workflow, monkeypatch, capability):
    h, owner = workflow, workflow.owner_ids["A"]
    port, cmd = command(h, capability)
    service = h.container.gallery if capability.startswith("gallery.") else h.container.library_files
    target = cmd.values.image_id if capability.startswith("gallery.") else cmd.values.file_id
    before = service.metadata(owner, target)
    audit = service._repo.audit_records if capability.startswith("gallery.") else service._repo.audit
    before_audit = list(audit)
    before_revision = port.revision(owner)

    def fail(*args, **kwargs):
        assert service.metadata(owner, target) != before
        raise StaleVersionError("DEMO failed task publication")

    monkeypatch.setattr(port._tasks, "cas", fail)
    with pytest.raises(StaleVersionError):
        port.apply(owner, cmd)
    assert service.metadata(owner, target) == before and audit == before_audit
    assert port.revision(owner) == before_revision and port.lookup(owner, cmd.binding.action_key) is None


def test_media_run_deadline_rechecks_after_the_actual_native_change(workflow, monkeypatch):
    from app.contracts.workflow_persistence import RunWriteBinding
    from app.infrastructure.durable_agent_runs import MemoryDurableRunControl

    from .test_durable_agent_runs import claimed

    h, owner = workflow, workflow.owner_ids["A"]
    port, cmd = command(h, "library.pdf.edit")
    state = h.container.assistant_workflows._repository._state
    run = claimed(MemoryDurableRunControl(clock=h.clock, state=state), owner)
    cmd = cmd.model_copy(
        update={
            "binding": cmd.binding.model_copy(
                update={"run_binding": RunWriteBinding(run_id=run.run_id, epoch=run.epoch)}
            )
        }
    )
    before = h.container.library_files.metadata(owner, cmd.values.file_id)
    update = h.container.library_files.update

    def slow_update(*args, **kwargs):
        row = update(*args, **kwargs)
        h.clock.advance(seconds=46)
        return row

    monkeypatch.setattr(h.container.library_files, "update", slow_update)
    with pytest.raises(StaleVersionError):
        port.apply(owner, cmd)
    assert h.container.library_files.metadata(owner, cmd.values.file_id) == before
    assert port.lookup(owner, cmd.binding.action_key) is None


def test_pdf_download_is_owned_and_read_only(workflow):
    h, owner = workflow, workflow.owner_ids["A"]
    med, _photo, pdf = seed_media(h)
    file_id = UUID(pdf["id"])
    files = h.container.library_files
    before = list(files._repo.audit)
    revision = files._repo.revision(owner)
    row, data = files.content(owner, file_id)
    assert row.medication_id == UUID(med) and data.startswith(b"%PDF-")
    from app.domain.errors import NotFoundError

    with pytest.raises(NotFoundError):
        files.content(h.owner_ids["B"], file_id)
    assert files._repo.audit == before and files._repo.revision(owner) == revision


def registration(h, kind):
    import hashlib
    from uuid import uuid5

    from app.application.workflow_media_storage import MediaCopyVerificationService
    from app.contracts.assistant_workflows import WorkflowContext
    from app.contracts.workflow_media_storage import MediaCopyTarget
    from app.infrastructure.evidence_images import patient_reference_image
    from app.infrastructure.workflow_media_storage import MemoryMediaCopyTickets, MemoryMediaCopyVerifier

    from . import test_workflow_pdf_upload as pdfs
    from . import test_workflow_reference_upload as photos

    fixture = photos if kind == "photo" else pdfs
    view = fixture.start(h)
    response = fixture.original(h, view)
    uploaded = response if kind == "photo" else response.json()
    view = uploaded["workflow"]
    source_id = UUID(uploaded["attachment"]["id"])
    owner = h.owner_ids["A"]
    originals = h.container.assistant_attachments
    state = originals._repository._state
    copies = MemoryMediaCopyTickets(
        state=state, clock=h.clock, originals=originals._repository, controls=originals._controls
    )
    port = harness(h, copies=copies)
    task = h.container.assistant_workflows._repository.get(owner, UUID(view["task_id"]))
    action = uuid4()
    b = WorkflowWriteBinding(
        task_id=task.id,
        task_revision=task.revision,
        capability_id=task.capability_id,
        action_key=action,
        prepared_ref=BusinessRef(kind="media_review", id=action, version=1),
        expected_domain_revision=port.revision(owner),
    )
    assert port.prepare(owner, api("PrepareMediaReview")(binding=b)).receipt.outcome == "prepared"
    task = h.container.assistant_workflows._repository.get(owner, task.id)
    values = api("PhotoUploadFields" if kind == "photo" else "PdfUploadFields").model_validate(task.fields)
    original = originals._repository.get(owner, task.id, source_id)
    content = originals._storage.read(owner, original.object_ref)
    native = patient_reference_image(content) if kind == "photo" else content
    digest = hashlib.sha256(native).hexdigest()
    target = MediaCopyTarget(
        owner=owner,
        medication_id=values.medication_id,
        native_id=uuid5(values.medication_id, digest)
        if kind == "photo"
        else uuid5(owner, f"medication-library-pdf:{values.medication_id}:{digest}"),
        media_kind=kind,
        content_type="image/png" if kind == "photo" else "application/pdf",
        checksum=digest,
        byte_size=len(native),
    )
    store = h.container.gallery._storage if kind == "photo" else h.container.library_files._storage
    copier = MediaCopyVerificationService(
        tickets=copies,
        originals=originals._repository,
        source_storage=originals._storage,
        target_storage=store,
        verifier=MemoryMediaCopyVerifier(state=state, clock=h.clock),
        clock=h.clock,
        normalize=patient_reference_image,
    )
    context = WorkflowContext(
        owner=owner,
        task_id=task.id,
        revision=task.revision,
        capability_id=task.capability_id,
        save_mode="allowed",
        timezone="UTC",
        language="en",
    )
    proof = copier.copy(context, source_id, target)
    b = b.model_copy(
        update={"task_revision": task.revision, "action_key": uuid4(), "expected_domain_revision": port.revision(owner)}
    )
    kwargs = {"processing_consent": True, "reviewed": True} if kind == "photo" else {}
    cmd = api("RegisterPhoto" if kind == "photo" else "RegisterPdf")(
        binding=b, values=values, copy_proof=proof, confirmed=True, **kwargs
    )
    return port, cmd, original, target


@pytest.mark.parametrize("kind", ["photo", "pdf"])
def test_verified_copy_does_not_register_media_until_independent_native_confirmation(workflow, monkeypatch, kind):
    h, owner = workflow, workflow.owner_ids["A"]
    port, cmd, original, target = registration(h, kind)
    if kind == "photo":
        assert h.container.gallery.list(owner)[0]["images"] == []
    else:
        assert h.container.library_files.list(owner, target.medication_id) == []

    def no_storage_write(*args, **kwargs):
        raise AssertionError("Formal metadata transaction must not write Storage")

    service = h.container.gallery if kind == "photo" else h.container.library_files
    monkeypatch.setattr(service._storage, "put", no_storage_write)
    result = port.apply(owner, cmd)
    row = result.result.photo if kind == "photo" else result.result.file
    assert row.id == target.native_id and result.result.duplicate is False
    assert result.receipt.business_ref == BusinessRef(kind="file", id=row.id, version=1)
    assert port.apply(owner, cmd) == result
    actual = h.container.assistant_attachments._repository.get(owner, original.task_id, original.id)
    assert actual.source_ref.id == row.id and actual.state == "saved"


@pytest.mark.parametrize("kind", ["photo", "pdf"])
def test_native_registration_excludes_deleting_original(workflow, kind):
    h, owner = workflow, workflow.owner_ids["A"]
    port, cmd, original, target = registration(h, kind)
    state = h.container.assistant_attachments._repository._state
    state.deleting_originals.add((owner, original.id))
    with pytest.raises(StaleVersionError):
        port.apply(owner, cmd)
    assert port.lookup(owner, cmd.binding.action_key) is None


@pytest.mark.parametrize("kind", ["photo", "pdf"])
def test_failed_registration_restores_formal_metadata_and_protection_but_keeps_exact_bytes(workflow, monkeypatch, kind):
    h, owner = workflow, workflow.owner_ids["A"]
    port, cmd, original, target = registration(h, kind)
    service = h.container.gallery if kind == "photo" else h.container.library_files
    source_storage = h.container.assistant_attachments._storage
    original_content = source_storage.read(owner, original.object_ref)
    native_content = service._storage.get(target.object_ref)
    state = h.container.assistant_attachments._repository._state
    before_links = dict(state.media_original_links)
    before_generation = port.revision(owner)

    def fail(*args, **kwargs):
        assert service.metadata(owner, target.native_id).id == target.native_id
        raise StaleVersionError("DEMO task publication failed after native registration")

    monkeypatch.setattr(port._tasks, "cas", fail)
    with pytest.raises(StaleVersionError):
        port.apply(owner, cmd)
    from app.domain.errors import NotFoundError

    with pytest.raises(NotFoundError):
        service.metadata(owner, target.native_id)
    assert state.media_original_links == before_links
    assert h.container.assistant_attachments._repository.get(owner, original.task_id, original.id).source_ref is None
    assert port.revision(owner) == before_generation and port.lookup(owner, cmd.binding.action_key) is None
    assert source_storage.read(owner, original.object_ref) == original_content
    assert service._storage.get(target.object_ref) == native_content


def test_native_registration_excludes_a_key_with_an_unresolved_delete(workflow):
    h, owner = workflow, workflow.owner_ids["A"]
    port, cmd, _original, target = registration(h, "pdf")
    state = h.container.assistant_attachments._repository._state
    state.deleting_media_objects.add((owner, target.object_ref))
    with pytest.raises(StaleVersionError):
        port.apply(owner, cmd)
    assert port.lookup(owner, cmd.binding.action_key) is None


@pytest.mark.parametrize("recovery", [False, True])
def test_remote_media_uses_fixed_native_write_or_read_only_recovery(workflow, recovery):
    import httpx
    from app.domain.errors import AuthenticationRequiredError
    from app.infrastructure.supabase_data import SupabaseDataClient
    from app.infrastructure.workflow_repos import SupabaseWorkflowMutations

    h, owner = workflow, workflow.owner_ids["A"]
    local, cmd = command(h, "library.pdf.edit")
    applied = local.apply(owner, cmd)
    calls = []

    def respond(request):
        calls.append(request.url.path)
        if request.method == "GET":
            return httpx.Response(200, json=[applied.receipt.model_dump(mode="json")] if recovery else [])
        return httpx.Response(200, json={"result": applied.model_dump(mode="json"), "replayed": recovery})

    data = SupabaseDataClient(
        base_url="https://example.invalid",
        publishable_key="sb_publishable_DEMO",
        access_token="DEMO-token",
        patient_id=owner,
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    cls = importlib.import_module("app.infrastructure.workflow_media_writes").SupabaseMediaWorkflowWrites
    remote = cls(data=data, receipts=SupabaseWorkflowMutations(data))
    assert remote.apply(owner, cmd) == applied
    assert calls == [
        "/rest/v1/assistant_business_receipts",
        "/rest/v1/rpc/assistant_media_" + ("read" if recovery else "write"),
    ]
    calls.clear()
    with pytest.raises(AuthenticationRequiredError):
        remote.apply(h.owner_ids["B"], cmd)
    assert calls == []


@pytest.mark.parametrize("kind", ["photo", "pdf"])
@pytest.mark.parametrize("mismatch", [False, True])
def test_remote_new_registration_rejects_metadata_different_from_patient_review(workflow, kind, mismatch):
    import httpx
    from app.domain.errors import ProviderUnavailableError
    from app.infrastructure.supabase_data import SupabaseDataClient
    from app.infrastructure.workflow_repos import SupabaseWorkflowMutations

    h, owner = workflow, workflow.owner_ids["A"]
    local, cmd, _original, _target = registration(h, kind)
    applied = local.apply(owner, cmd)
    key = "photo" if kind == "photo" else "file"
    row = getattr(applied.result, key)
    wrong = row.model_copy(
        update={"source_description": "DEMO unrelated photo"}
        if kind == "photo"
        else {"display_title": "DEMO unrelated document"}
    )
    if mismatch:
        applied = applied.model_copy(update={"result": applied.result.model_copy(update={key: wrong})})

    def respond(request):
        return httpx.Response(200, json=[] if request.method == "GET" else {"result": applied.model_dump(mode="json")})

    data = SupabaseDataClient(
        base_url="https://example.invalid",
        publishable_key="sb_publishable_DEMO",
        access_token="DEMO-token",
        patient_id=owner,
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    cls = importlib.import_module("app.infrastructure.workflow_media_writes").SupabaseMediaWorkflowWrites
    remote = cls(data=data, receipts=SupabaseWorkflowMutations(data), copies=local._copies)
    if mismatch:
        with pytest.raises(ProviderUnavailableError):
            remote.apply(owner, cmd)
    else:
        assert remote.apply(owner, cmd) == applied
