"""DEMO_ONLY independently confirmed upload bridges and exact-original retention."""

import importlib
from uuid import UUID

import pytest

from . import test_workflow_pdf_upload as pdfs
from . import test_workflow_reference_upload as photos
from .test_persistent_media_transactions import harness


def wire(h):
    from app.application.workflow_media_storage import MediaCopyVerificationService
    from app.infrastructure.evidence_images import patient_reference_image
    from app.infrastructure.memory_workflows import MemoryWorkflowMutations
    from app.infrastructure.workflow_media_storage import MemoryMediaCopyTickets, MemoryMediaCopyVerifier

    cls = importlib.import_module("app.application.workflow_media_upload_transactions").MediaUploadWorkflowTransactions
    originals = h.container.assistant_attachments
    w = h.container.assistant_workflows
    state = w._repository._state
    copies = MemoryMediaCopyTickets(state=state, clock=h.clock, originals=originals._repository, controls=w._controls)
    copiers = {
        cap: MediaCopyVerificationService(
            tickets=copies,
            originals=originals._repository,
            source_storage=originals._storage,
            target_storage=storage,
            verifier=MemoryMediaCopyVerifier(state=state, clock=h.clock),
            clock=h.clock,
            normalize=patient_reference_image,
        )
        for cap, storage in (
            ("gallery.photo.add", h.container.gallery._storage),
            ("library.pdf.add", h.container.library_files._storage),
        )
    }
    port = harness(h, copies=copies)
    coordinator = cls(
        writes=port,
        tasks=w._repository,
        receipts=MemoryWorkflowMutations(h.clock, state=state),
        originals=originals._repository,
        source_storage=originals._storage,
        copies=copies,
        copiers=copiers,
        normalize=patient_reference_image,
        preferences=h.container.preferences,
        enrollment=h.container.enrollment,
    )
    w._business_transactions = dict.fromkeys(coordinator.capability_ids, coordinator)
    h.container.assistant_photo_upload.transactions = coordinator
    h.container.assistant_pdf_upload.transactions = coordinator
    return coordinator, port, copies


@pytest.mark.parametrize("fixture", [photos, pdfs], ids=["photo", "pdf"])
def test_typed_upload_native_http_saves_once_and_recovers_without_new_copy(workflow, monkeypatch, fixture):
    h = workflow
    coordinator, port, copies = wire(h)
    task, attachment = fixture.ready(h)
    state = h.container.assistant_workflows._repository._state
    assert not state.media_storage_tickets, "Preparing review must not copy or register native media"

    def forbidden(*args, **kwargs):
        raise AssertionError("Typed upload must not execute a generic callback or repeat physical copying")

    monkeypatch.setattr(h.container.assistant_workflows._controls, "guarded_write", forbidden)
    first = fixture.upload(h, task)
    assert first.status_code == 200, first.text
    assert len(state.media_storage_tickets) == 1
    monkeypatch.setattr(copies, "reserve", forbidden)
    monkeypatch.setattr(coordinator.copiers[task["capability_id"]], "copy", forbidden)
    assert fixture.upload(h, task).json() == first.json()
    monkeypatch.setattr(port, "apply", forbidden)
    completed = h.event(task["task_id"], "report_business_result")
    assert completed["state"] == "completed" and completed["revision"] == task["revision"] + 1
    assert completed["visible_fields"]["duplicate"] is False
    assert "storage_path" not in str(completed["visible_fields"])
    content = h.client.get(
        f"/api/agent/workflows/tasks/{task['task_id']}/attachments/{attachment['id']}",
        params={"client_id": "DEMO-workflow-A"},
    )
    assert content.content == (photos.PHOTO if fixture is photos else pdfs.PDF)


@pytest.mark.parametrize("fixture", [photos, pdfs], ids=["photo", "pdf"])
def test_registration_failure_retains_original_and_reuses_verified_copy(workflow, monkeypatch, fixture):
    from app.domain.errors import ProviderUnavailableError

    h = workflow
    coordinator, port, _ = wire(h)
    task, attachment = fixture.ready(h)
    apply = port.apply

    def fail(*args, **kwargs):
        raise ProviderUnavailableError("DEMO registration unavailable after actual copy")

    monkeypatch.setattr(port, "apply", fail)
    assert fixture.upload(h, task).status_code == 503
    pending = h.view(task["task_id"])
    assert pending["state"] == "awaiting_confirmation" and pending["input_fields"] == task["input_fields"]
    owner = h.owner_ids["A"]
    original = h.container.assistant_attachments._repository.get(owner, UUID(task["task_id"]), UUID(attachment["id"]))
    assert h.container.assistant_attachments._storage.read(owner, original.object_ref) == (
        photos.PHOTO if fixture is photos else pdfs.PDF
    )
    monkeypatch.setattr(port, "apply", apply)
    monkeypatch.setattr(coordinator.copiers[task["capability_id"]], "copy", fail)
    assert fixture.upload(h, task).status_code == 200


@pytest.mark.parametrize("fixture", [photos, pdfs], ids=["photo", "pdf"])
def test_unknown_copy_cannot_be_replayed_by_another_patient_upload(workflow, monkeypatch, fixture):
    h = workflow
    wire(h)
    task, _ = fixture.ready(h)
    storage = h.container.gallery._storage if fixture is photos else h.container.library_files._storage
    calls = []

    def false_ack(path, content):
        calls.append(path)

    monkeypatch.setattr(storage, "put", false_ack)
    assert fixture.upload(h, task).status_code == 503
    assert fixture.upload(h, task).status_code in {409, 503}
    assert len(calls) == 1


@pytest.mark.parametrize("fixture", [photos, pdfs], ids=["photo", "pdf"])
def test_replaced_raw_content_is_rejected_before_copy_io(workflow, fixture):
    h = workflow
    wire(h)
    task, _ = fixture.ready(h)
    response = fixture.upload(h, task, content=b"DEMO substituted bytes")
    assert response.status_code in {409, 422}, response.text
    assert not h.container.assistant_workflows._repository._state.media_storage_tickets


@pytest.mark.parametrize("change", ["bytes", "metadata", "confirmation", "consent", "comparison", "revision"])
def test_photo_typed_inputs_use_existing_patient_validation(workflow, change):
    wire(workflow)
    photos.test_bound_photo_upload_rejects_unreviewed_or_substituted_inputs(workflow, change)


@pytest.mark.parametrize(
    "change", ["bytes", "filename", "category", "description", "confirmation", "revision", "owner"]
)
def test_pdf_typed_inputs_use_existing_patient_validation(workflow, change):
    wire(workflow)
    pdfs.test_bound_pdf_rejects_substitution_or_missing_patient_authority(workflow, change)


def test_remote_copy_recovery_revalidates_owned_ticket_and_never_issues_a_writer():
    import json
    from uuid import uuid4

    import httpx
    from app.domain.errors import AuthenticationRequiredError
    from app.infrastructure.supabase_data import SupabaseDataClient
    from app.infrastructure.workflow_media_storage import SupabaseMediaCopyTickets

    from .test_verified_media_copies import setup_copy

    service, local, _, _, _, _, context, source, _, target, _, _ = setup_copy()
    assert local.recover(context, source.id, target) is None
    proof = service.copy(context, source.id, target)
    assert local.recover(context, source.id, target) == proof
    ticket = local.read_verified(context.owner, proof)
    calls = []

    def respond(request):
        cmd = json.loads(request.content)["p_command"]
        calls.append((request.url.path, cmd))
        return httpx.Response(
            200,
            json={
                "result": proof.model_dump(mode="json") if cmd["kind"] == "recover" else ticket.model_dump(mode="json")
            },
        )

    data = SupabaseDataClient(
        base_url="https://example.invalid",
        publishable_key="sb_publishable_DEMO",
        access_token="DEMO-token",
        patient_id=context.owner,
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    remote = SupabaseMediaCopyTickets(data=data)
    assert remote.recover(context, source.id, target) == proof
    assert [cmd["kind"] for _, cmd in calls] == ["recover", "read_verified"]
    assert all(path == "/rest/v1/rpc/assistant_media_copy_command" for path, _ in calls)
    with pytest.raises(AuthenticationRequiredError):
        remote.recover(context.model_copy(update={"owner": uuid4()}), source.id, target)
    assert len(calls) == 2


def test_review_sql_includes_scoped_read_only_copy_recovery():
    from pathlib import Path

    candidate = Path("supabase/review/assistant_workflows/media.up.sql").read_text(encoding="utf-8")
    assert "WHEN 'recover' THEN ARRAY['kind','context','attachment_id','target']" in candidate
    assert "Unresolved native-copy writer cannot be repeated" in candidate


def test_a_stale_copy_recovery_read_cannot_issue_a_second_upload_writer(workflow, monkeypatch):
    from app.domain.errors import ProviderUnavailableError

    h = workflow
    _, port, copies = wire(h)
    task, _ = pdfs.ready(h)

    def fail(*args, **kwargs):
        raise ProviderUnavailableError("DEMO native registration outage")

    monkeypatch.setattr(port, "apply", fail)
    assert pdfs.upload(h, task).status_code == 503
    state = h.container.assistant_workflows._repository._state
    assert len(state.media_storage_tickets) == 1
    monkeypatch.setattr(copies, "recover", lambda *args, **kwargs: None)
    calls = []
    storage = h.container.library_files._storage
    put = storage.put

    def counted(*args):
        calls.append(args)
        return put(*args)

    monkeypatch.setattr(storage, "put", counted)
    assert pdfs.upload(h, task).status_code in {409, 503}
    assert not calls and len(state.media_storage_tickets) == 1


@pytest.mark.parametrize("fixture", [photos, pdfs], ids=["photo", "pdf"])
def test_completed_upload_does_not_claim_a_later_native_change_was_verified(workflow, monkeypatch, fixture):
    from app.domain.errors import StaleVersionError

    h = workflow
    _, port, _ = wire(h)
    task, _ = fixture.ready(h)
    assert fixture.upload(h, task).status_code == 200

    def changed(*args, **kwargs):
        raise StaleVersionError("DEMO actual native file changed independently")

    monkeypatch.setattr(port, "read", changed)
    actual = h.view(task["task_id"])
    assert actual["state"] == "completed" and actual["visible_fields"]["actual_result_available"] is False
    assert actual["visible_fields"]["historical_result"] is True
