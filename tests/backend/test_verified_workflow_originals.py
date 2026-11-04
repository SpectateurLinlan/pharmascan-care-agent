"""DEMO_ONLY byte proofs use real memory state and independently observed bytes."""

import hashlib
import importlib
from uuid import uuid4

import pytest
from app.contracts.assistant_workflows import WorkflowContext, WorkflowTask
from app.contracts.workflow_attachments import OriginalAttachment, StoredObject
from app.domain.errors import ProviderUnavailableError, StaleVersionError
from app.infrastructure.memory_workflows import (
    MemoryCleanupRepository,
    MemoryControlRepository,
    MemoryOriginalRepository,
    MemoryWorkflowObjects,
    MemoryWorkflowRepository,
    MemoryWorkflowState,
)

from .conftest import FixedClock
from .test_workflow_originals import original_png


def harness(kind="pharmacy_label", mime="image/png", content=None):
    module = importlib.import_module("app.infrastructure.verified_original_repos")
    service_module = importlib.import_module("app.application.workflow_verification")
    state, clock = MemoryWorkflowState(), FixedClock()
    tasks = MemoryWorkflowRepository(clock, state=state)
    controls = MemoryControlRepository(clock, state=state)
    originals = MemoryOriginalRepository(state=state, tasks=tasks, controls=controls)
    cleanup = MemoryCleanupRepository(state=state)
    store = MemoryWorkflowObjects(state=state)
    owner, task_id, attachment_id, upload_id = (uuid4() for _ in range(4))
    capability = {
        "reference_photo": "gallery.photo.add",
        "library_pdf": "library.pdf.add",
        "comparison_photo": "image.compare",
        "source_preview_photo": "source.preview",
    }.get(kind, "medication.enroll")
    tasks.create(
        WorkflowTask(id=task_id, owner=owner, workspace_id=uuid4(), capability_id=capability, updated_at=clock.now())
    )
    context = WorkflowContext(
        owner=owner,
        task_id=task_id,
        revision=1,
        capability_id=capability,
        save_mode="allowed",
        language="en",
        timezone="UTC",
    )
    content = content if content is not None else original_png()
    row = originals.reserve(
        context,
        OriginalAttachment(
            id=attachment_id,
            owner=owner,
            task_id=task_id,
            upload_id=upload_id,
            binding_revision=1,
            object_ref=f"{owner}/workflow-originals/{task_id}/{attachment_id}",
            original_checksum=hashlib.sha256(content).hexdigest(),
            content_type=mime,
            source_kind=kind,
            byte_size=len(content),
            extraction_status="not_requested"
            if kind not in {"pharmacy_label", "package", "prescription"}
            else "pending",
        ),
    )
    port = module.MemoryVerifiedOriginals(
        state=state, clock=clock, originals=originals, controls=controls, cleanup=cleanup
    )
    verifier = module.MemoryStorageVerifier(state=state, clock=clock)
    service = service_module.WorkflowVerificationService(repository=port, storage=store, verifier=verifier, clock=clock)
    return service, port, verifier, state, clock, originals, controls, context, row, content


def test_ack_without_matching_bytes_is_not_saved():
    service, _, _, state, _, originals, _, context, row, content = harness()

    class FalseAck:
        def put_original(self, *args, **kwargs):
            return StoredObject(object_ref=row.object_ref, checksum=row.original_checksum, byte_size=row.byte_size)

        def read(self, *args):
            return b"DEMO wrong object bytes"

    service._storage = FalseAck()
    with pytest.raises(ProviderUnavailableError):
        service.save(context, row.id, row.upload_id, content)
    assert originals.get(row.owner, row.task_id, row.id).state == "reserved"
    assert not state.original_objects


@pytest.mark.parametrize(
    "kind",
    [
        "package",
        "pharmacy_label",
        "prescription",
        "reference_photo",
        "library_pdf",
        "comparison_photo",
        "source_preview_photo",
    ],
)
def test_all_original_purposes_preserve_native_limits(kind):
    content = b"%PDF-1.7\nDEMO\n%%EOF" if kind == "library_pdf" else original_png()
    mime = "application/pdf" if kind == "library_pdf" else "image/png"
    service, _, _, state, _, _, _, context, row, _ = harness(kind, mime, content)
    result = service.save(context, row.id, row.upload_id, content)
    assert result.state == "saved"
    assert state.original_objects[(row.owner, row.object_ref)] == content
    assert result.extraction_status == (
        "pending" if kind in {"package", "pharmacy_label", "prescription"} else "not_requested"
    )


def test_storage_failure_never_claims_retention():
    service, _, _, _, _, originals, _, context, row, content = harness()

    class FailedStore:
        def put_original(self, *args, **kwargs):
            raise ProviderUnavailableError("DEMO timeout: upload may still be running")

    service._storage = FailedStore()
    with pytest.raises(ProviderUnavailableError):
        service.save(context, row.id, row.upload_id, content)
    current = originals.get(row.owner, row.task_id, row.id)
    assert current.state == "reserved" and row.upload_id in current.pending_writer_ids


def test_revoke_between_proof_and_publish_cannot_recreate_saved_content():
    service, _, verifier, state, _, _, controls, context, row, content = harness()
    record = verifier.record_storage

    def revoke(observation, **kwargs):
        proof = record(observation, **kwargs)
        controls.revoke(row.owner, row.task_id, 1, uuid4())
        return proof

    verifier.record_storage = revoke
    with pytest.raises((StaleVersionError, ProviderUnavailableError)):
        service.save(context, row.id, row.upload_id, content)
    assert (row.owner, row.task_id) not in state.tasks
    assert state.cleanup[(row.owner, row.id)].writer_pending is False
    assert state.original_objects[(row.owner, row.object_ref)] == content


def test_patient_reference_cannot_forge_a_verified_operation():
    from app.contracts.workflow_verification import VerifiedOperationRef

    service, port, _, _, _, _, _, context, row, _ = harness()
    forged = VerifiedOperationRef(ticket_id=uuid4(), verification_id=uuid4(), generation=1, result="bytes_verified")
    with pytest.raises((ProviderUnavailableError, StaleVersionError)):
        port.publish_verified(context, row.id, forged)


def test_ticket_cannot_start_upload_after_its_bound_run_is_cancelled():
    from app.contracts.workflow_persistence import RunWriteBinding
    from app.infrastructure.durable_agent_runs import MemoryDurableRunControl

    from .test_durable_agent_runs import claimed

    _, port, _, state, clock, _, _, context, row, _ = harness()
    runs = MemoryDurableRunControl(state=state, clock=clock)
    run = claimed(runs, row.owner, uuid4())
    ticket = port.reserve_ticket(
        context, row.id, row.upload_id, run_binding=RunWriteBinding(run_id=run.run_id, epoch=run.epoch)
    )
    runs.request_cancel(row.owner, run.run_id)
    with pytest.raises(StaleVersionError):
        port.claim_ticket(row.owner, ticket)


def test_extraction_failure_keeps_original_bytes_on_the_actual_verified_upload_flow(workflow):
    from app.application.workflow_attachments import WorkflowAttachmentService
    from app.application.workflow_verification import WorkflowVerificationService
    from app.infrastructure.verified_original_repos import MemoryStorageVerifier, MemoryVerifiedOriginals

    h = workflow
    current = h.container.assistant_attachments
    state = current._repository._state
    port = MemoryVerifiedOriginals(
        state=state,
        clock=h.clock,
        originals=current._repository,
        controls=current._controls,
        cleanup=h.container.assistant_cleanup._repository,
    )
    verification = WorkflowVerificationService(
        repository=port,
        storage=current._storage,
        verifier=MemoryStorageVerifier(state=state, clock=h.clock),
        clock=h.clock,
    )
    h.container.assistant_attachments = WorkflowAttachmentService(
        repository=current._repository,
        storage=current._storage,
        tasks=current._tasks,
        controls=current._controls,
        preferences=current._preferences,
        ids=current._ids,
        normalize=current._normalize,
        preview=current._preview,
        cleanup=current._cleanup,
        enrollment=current._enrollment,
        verification=verification,
    )
    first = h.start("medication.enroll", {"method": "photo"})
    content = original_png()
    result = h.upload(first["task_id"], content)
    assert result["attachment"]["state"] == "saved" and result["attachment"]["extraction_status"] == "failed"
    assert h.read_original(result["attachment"]["id"]) == content
    assert len(state.storage_verifications) == 1


def test_patient_wire_uses_fixed_original_command_without_forged_owner():
    import json

    import httpx
    from app.infrastructure.supabase_data import SupabaseDataClient
    from app.infrastructure.verified_original_repos import SupabaseVerifiedOriginals

    _, port, _, _, _, _, _, context, row, _ = harness()
    ticket = port.reserve_ticket(context, row.id, row.upload_id)
    calls = []

    def respond(request):
        calls.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"result": ticket.model_dump(mode="json")})

    data = SupabaseDataClient(
        base_url="https://example.invalid",
        publishable_key="sb_publishable_DEMO",
        access_token="DEMO-token",
        patient_id=context.owner,
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    remote = SupabaseVerifiedOriginals(data)
    result = remote.reserve_ticket(context, row.id, row.upload_id)
    assert result == ticket
    path, body = calls[0]
    assert path == "/rest/v1/rpc/assistant_original_command"
    assert body["p_command"]["kind"] == "reserve_ticket"
    assert "owner" not in body["p_command"] and "owner" not in body["p_command"]["context"]


def test_storage_adapter_preserves_pdf_native_size_limit():
    import base64
    import json

    import httpx
    from app.infrastructure.workflow_objects import SupabaseWorkflowObjects, WorkflowObjectAccess

    owner, task, attachment = uuid4(), uuid4(), uuid4()
    content = b"%PDF-1.7\n" + b"x" * 8_100_000 + b"\n%%EOF"
    claims = (
        base64.urlsafe_b64encode(json.dumps({"sub": str(owner), "role": "authenticated"}).encode()).decode().rstrip("=")
    )
    token = "DEMO." + claims + ".DEMO"
    stored = {}

    def respond(request):
        if request.method == "POST":
            stored["body"] = request.content
            return httpx.Response(200, json={})
        return httpx.Response(200, content=stored["body"])

    objects = SupabaseWorkflowObjects(
        owner=owner,
        base_url="https://example.invalid",
        bucket="medication-sources",
        publishable_key="sb_publishable_DEMO",
        access_token=token,
        client=httpx.Client(transport=httpx.MockTransport(respond)),
        access=WorkflowObjectAccess(lambda *args: True),
    )
    result = objects.put_original(
        owner, task, uuid4(), content, "application/pdf", object_ref=f"{owner}/workflow-originals/{task}/{attachment}"
    )
    assert result.byte_size == len(content) and stored["body"] == content


def test_original_sql_candidates_include_proof_and_reference_fences():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "supabase/review/assistant_workflows"
    up, down = root / "originals.up.sql", root / "originals.down.sql"
    assert up.is_file() and down.is_file(), "Missing original verification SQL review candidates"
    sql = up.read_text(encoding="utf-8")
    for required in (
        "publish_verified",
        "start_deleting",
        "settle_writer",
        "settle_cleanup",
        "assistant_verified_operations",
        "assistant_original_reference_guard",
        "pg_advisory_xact_lock",
    ):
        assert required in sql
    assert "DELETE FROM storage.objects" not in sql
    assert "RAISE EXCEPTION" in down.read_text(encoding="utf-8")
