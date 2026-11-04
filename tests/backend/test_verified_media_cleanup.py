"""DEMO_ONLY physical cleanup uses an ended delete plus independent absence."""

import importlib

import pytest
from app.domain.errors import ProviderUnavailableError, StaleVersionError

from .test_persistent_media_transactions import command


def setup_cleanup(h, kind, deletion=None):
    native, cmd = deletion or command(h, "gallery.photo.delete" if kind == "photo" else "library.pdf.delete")
    owner = h.owner_ids["A"]
    deleted = native.apply(owner, cmd)
    module = importlib.import_module("app.infrastructure.workflow_media_cleanup")
    service_module = importlib.import_module("app.application.workflow_media_cleanup")
    state = h.container.assistant_workflows._repository._state
    port = module.MemoryMediaCleanupTickets(
        state=state,
        store=h.container.store,
        clock=h.clock,
        tasks=native._tasks,
        controls=native._controls,
        gallery=h.container.gallery,
        library=h.container.library_files,
        images=h.container.gallery._repo,
        files=h.container.library_files._repo,
    )
    verifier = module.MemoryMediaDeleteVerifier(state=state, clock=h.clock)
    storage = h.container.gallery._storage if kind == "photo" else h.container.library_files._storage
    service = service_module.MediaCleanupVerificationService(
        tickets=port, storage=storage, verifier=verifier, clock=h.clock
    )
    return service, port, state, storage, cmd, deleted


@pytest.mark.parametrize("kind", ["photo", "pdf"])
def test_verified_media_cleanup_advances_actual_metadata_task_and_keeps_delete_receipt(workflow, monkeypatch, kind):
    h, owner = workflow, workflow.owner_ids["A"]
    service, port, state, storage, cmd, deleted = setup_cleanup(h, kind)
    delete = storage.delete
    calls = []

    def counted(path):
        calls.append(path)
        delete(path)

    monkeypatch.setattr(storage, "delete", counted)
    result = service.cleanup(owner, cmd.binding.action_key)
    assert not result.result.cleanup_pending and result.result.deleted_at == deleted.result.deleted_at
    assert storage.observe(deleted.result.storage_path) is None
    assert h.container.assistant_workflows._repository.get(owner, cmd.binding.task_id).state == "completed"
    assert state.business_receipts[owner, cmd.binding.action_key] == deleted.receipt
    assert service.cleanup(owner, cmd.binding.action_key) == result
    assert calls == [deleted.result.storage_path]
    assert (owner, deleted.result.storage_path) in state.deleting_media_objects


def test_native_delete_ack_without_absence_keeps_cleanup_pending_and_blocks_automatic_replay(workflow, monkeypatch):
    h, owner = workflow, workflow.owner_ids["A"]
    service, port, state, storage, cmd, deleted = setup_cleanup(h, "pdf")
    calls = []

    def false_ack(path):
        calls.append(path)

    monkeypatch.setattr(storage, "delete", false_ack)
    with pytest.raises(ProviderUnavailableError):
        service.cleanup(owner, cmd.binding.action_key)
    with pytest.raises(StaleVersionError):
        service.cleanup(owner, cmd.binding.action_key)
    assert calls == [deleted.result.storage_path]
    assert h.container.library_files.metadata(owner, deleted.result.id, include_deleted=True).cleanup_pending
    assert storage.get(deleted.result.storage_path)
    assert h.container.assistant_workflows._repository.get(owner, cmd.binding.task_id).state == "outcome_unknown"
    assert len(state.media_delete_verifications) == 1
    assert next(iter(state.media_delete_verifications.values())).result == "outcome_unknown"


def test_settlement_failure_retries_only_known_proof_without_a_second_physical_delete(workflow, monkeypatch):
    h, owner = workflow, workflow.owner_ids["A"]
    service, port, state, storage, cmd, deleted = setup_cleanup(h, "pdf")
    cas = port._tasks.cas

    def fail(*args, **kwargs):
        assert not h.container.library_files.metadata(owner, deleted.result.id, include_deleted=True).cleanup_pending
        raise StaleVersionError("DEMO failed task completion after native cleanup acknowledgement")

    monkeypatch.setattr(port._tasks, "cas", fail)
    with pytest.raises(StaleVersionError):
        service.cleanup(owner, cmd.binding.action_key)
    assert h.container.library_files.metadata(owner, deleted.result.id, include_deleted=True).cleanup_pending
    assert storage.observe(deleted.result.storage_path) is None
    assert next(iter(state.media_delete_verifications.values())).result == "absent_after_delete"
    monkeypatch.setattr(port._tasks, "cas", cas)

    def no_second_delete(path):
        raise AssertionError("A verified deletion settlement must not repeat Storage DELETE")

    monkeypatch.setattr(storage, "delete", no_second_delete)
    assert not service.cleanup(owner, cmd.binding.action_key).result.cleanup_pending
    assert h.container.assistant_workflows._repository.get(owner, cmd.binding.task_id).state == "completed"


def test_revocation_during_native_delete_settles_cleanup_without_recreating_task(workflow, monkeypatch):
    from app.domain.errors import NotFoundError

    h, owner = workflow, workflow.owner_ids["A"]
    service, port, state, storage, cmd, deleted = setup_cleanup(h, "pdf")
    delete = storage.delete

    def revoke_after_delete(path):
        delete(path)
        port._controls.revoke(owner, cmd.binding.task_id, deleted.receipt.binding_revision)

    monkeypatch.setattr(storage, "delete", revoke_after_delete)
    result = service.cleanup(owner, cmd.binding.action_key)
    assert not result.result.cleanup_pending
    with pytest.raises(NotFoundError):
        port._tasks.get(owner, cmd.binding.task_id)
    assert port._controls.get(owner, cmd.binding.task_id).revoked
    assert state.business_receipts[owner, cmd.binding.action_key] == deleted.receipt


def test_forged_native_absence_proof_never_acknowledges_cleanup(workflow):
    from uuid import uuid4

    from app.contracts.workflow_media_cleanup import VerifiedMediaDeleteRef

    h, owner = workflow, workflow.owner_ids["A"]
    _service, port, _state, _storage, cmd, deleted = setup_cleanup(h, "pdf")
    ticket = port.start(owner, cmd.binding.action_key)
    forged = VerifiedMediaDeleteRef(
        ticket_id=ticket.ticket_id, verification_id=uuid4(), generation=ticket.generation, result="absent_after_delete"
    )
    with pytest.raises(ProviderUnavailableError):
        port.settle(owner, forged)
    assert h.container.library_files.metadata(owner, deleted.result.id, include_deleted=True).cleanup_pending


@pytest.mark.parametrize("status", [200, 404, 403, 503])
def test_native_storage_observation_only_treats_actual_404_as_absence(status):
    from uuid import uuid4

    import httpx
    from app.infrastructure.evidence_repos import SupabaseImageStore

    owner = uuid4()
    calls = []

    def respond(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(status, content=b"DEMO remaining bytes" if status == 200 else b"")

    store = SupabaseImageStore(
        base_url="https://example.invalid",
        publishable_key="sb_publishable_DEMO",
        access_token="DEMO-token",
        patient_id=owner,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(respond)),
    )
    path = f"{owner}/library/DEMO.pdf"
    if status >= 400 and status != 404:
        with pytest.raises(ProviderUnavailableError):
            store.observe(path)
    else:
        assert store.observe(path) == (None if status == 404 else b"DEMO remaining bytes")
    assert calls == [("GET", f"/storage/v1/object/visual-references/{path}")]


@pytest.mark.parametrize("wrong_identity", [False, True])
def test_native_delete_observation_uses_only_its_fixed_restricted_command(wrong_identity):
    from datetime import UTC, datetime
    from uuid import uuid4

    from app.contracts.workflow_media_cleanup import MediaDeleteObservation
    from app.infrastructure.workflow_verification import (
        EvidenceConnectionSettings,
        PostgresEvidenceVerifier,
        RestrictedEvidenceConnection,
    )

    from .test_workflow_verification_transport import DSN, RecordingConnection, Row

    observation = MediaDeleteObservation(
        ticket_id=uuid4(),
        nonce=uuid4(),
        generation=1,
        result="absent_after_delete",
        observed_at=datetime(2026, 10, 29, tzinfo=UTC),
        bucket_id="medication-sources",
    )

    class DeleteConnection(RecordingConnection):
        def execute(self, sql, params=None):
            if "record_media_delete_observation" in sql:
                self.calls.append((sql, params))
                body = params[0].obj
                return Row(
                    {
                        "result": {
                            "family": "native_media_delete",
                            "ticket_id": body["ticket_id"],
                            "verification_id": str(uuid4()),
                            "generation": body["generation"],
                            "result": body["result"],
                        }
                    }
                )
            return super().execute(sql, params)

    db = DeleteConnection(identity={"login": "postgres"} if wrong_identity else None)
    verifier = PostgresEvidenceVerifier(
        RestrictedEvidenceConnection(EvidenceConnectionSettings(DSN), connect=lambda **kwargs: db)
    )
    if wrong_identity:
        with pytest.raises(ProviderUnavailableError):
            verifier.record_media_delete(observation, timeout_seconds=3)
        assert not any("record_media_delete_observation" in sql for sql, _params in db.calls)
    else:
        proof = verifier.record_media_delete(observation, timeout_seconds=3)
        assert proof.result == "absent_after_delete" and proof.ticket_id == observation.ticket_id
        assert [sql for sql, _params in db.calls if "record_" in sql] == [
            "SELECT assistant_evidence.record_media_delete_observation(%s) AS result"
        ]
    assert db.closed


def test_expired_unknown_copy_and_absent_object_cannot_enable_a_new_native_delete(workflow, monkeypatch):
    from uuid import UUID, uuid4

    from app.contracts.assistant_workflows import BusinessRef, WorkflowContext
    from app.contracts.workflow_persistence import WorkflowWriteBinding

    from .test_persistent_media_transactions import api, harness, registration

    h, owner = workflow, workflow.owner_ids["A"]
    native, upload, original, target = registration(h, "pdf")
    context = WorkflowContext(
        owner=owner,
        task_id=upload.binding.task_id,
        revision=upload.binding.task_revision,
        capability_id="library.pdf.add",
        save_mode="allowed",
        language="en",
        timezone="UTC",
    )
    pending = native._copies.reserve(context, original.id, uuid4(), target)
    native._copies.claim(owner, pending)
    native.apply(owner, upload)
    view = h.start(
        "library.pdf.delete",
        {"medication_id": str(target.medication_id), "file_id": str(target.native_id), "expected_version": 1},
    )
    delete_port = harness(h)
    action = uuid4()
    binding = WorkflowWriteBinding(
        task_id=UUID(view["task_id"]),
        task_revision=view["revision"],
        capability_id="library.pdf.delete",
        action_key=action,
        prepared_ref=BusinessRef(kind="media_review", id=action, version=1),
        expected_domain_revision=delete_port.revision(owner),
    )
    delete_port.prepare(owner, api("PrepareMediaReview")(binding=binding))
    task = delete_port._tasks.get(owner, binding.task_id)
    cmd = api("TombstonePdf")(
        binding=binding.model_copy(update={"action_key": uuid4(), "task_revision": task.revision}),
        values=api("PdfChangeFields").model_validate(task.fields),
        confirmed=True,
    )
    service, _port, state, storage, cmd, deleted = setup_cleanup(h, "pdf", deletion=(delete_port, cmd))
    h.clock.advance(days=2)
    storage.delete(deleted.result.storage_path)  # Absence alone does not settle the unrelated inflight writer.

    def forbidden(path):
        raise AssertionError("Unknown writers must block DELETE before any Storage call")

    monkeypatch.setattr(storage, "delete", forbidden)
    with pytest.raises(StaleVersionError):
        service.cleanup(owner, cmd.binding.action_key)
    assert not state.media_delete_tickets
    assert state.media_storage_tickets[pending.ticket_id].state == "inflight"
    assert h.container.library_files.metadata(owner, deleted.result.id, include_deleted=True).cleanup_pending


def test_media_sql_candidate_inventory_covers_native_cleanup_and_closed_rollback():
    """Packaging evidence only; this does not execute SQL, RLS or native RPCs."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "supabase/review/assistant_workflows"
    up = (root / "media.up.sql").read_text(encoding="utf-8")
    down = (root / "media.down.sql").read_text(encoding="utf-8")
    for entry in (
        "assistant_media_cleanup_command",
        "assistant_media_delete_projection",
        "assistant_media_delete_current",
        "assistant_media_reference_guard",
        "assistant_media_cleanup_settlements",
        "ack_personal_gallery_image_cleanup",
        "ack_medication_library_pdf_cleanup",
    ):
        assert entry in up, f"Missing native media candidate entry: {entry}"
    for entry in ("assistant_media_commands", "assistant_media_cleanup_settlements", "assistant_media_cleanup_command"):
        assert entry in down, f"Incomplete rollback inventory: {entry}"
    assert up.rstrip().endswith("COMMIT;") and down.rstrip().endswith("COMMIT;")
    assert "DELETE FROM storage.objects" not in up
    assert "TO assistant_evidence_login" not in up


def test_remote_cleanup_start_uses_actual_owned_receipt_and_fixed_rpc(workflow):
    import json

    import httpx
    from app.domain.errors import AuthenticationRequiredError
    from app.infrastructure.supabase_data import SupabaseDataClient
    from app.infrastructure.workflow_repos import SupabaseWorkflowMutations

    h, owner = workflow, workflow.owner_ids["A"]
    _service, local, _state, _storage, cmd, deleted = setup_cleanup(h, "pdf")
    ticket = local.start(owner, cmd.binding.action_key)
    calls = []

    def respond(request):
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json=[deleted.receipt.model_dump(mode="json")])
        assert json.loads(request.content) == {
            "p_command": {"kind": "start", "action_key": str(cmd.binding.action_key)}
        }
        return httpx.Response(200, json={"result": {"kind": "ticket", "ticket": ticket.model_dump(mode="json")}})

    data = SupabaseDataClient(
        base_url="https://example.invalid",
        publishable_key="sb_publishable_DEMO",
        access_token="DEMO-token",
        patient_id=owner,
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    cls = importlib.import_module("app.infrastructure.workflow_media_cleanup").SupabaseMediaCleanupTickets
    remote = cls(data=data, receipts=SupabaseWorkflowMutations(data))
    assert remote.start(owner, cmd.binding.action_key) == ticket
    assert calls == [
        ("GET", "/rest/v1/assistant_business_receipts"),
        ("POST", "/rest/v1/rpc/assistant_media_cleanup_command"),
    ]
    calls.clear()
    with pytest.raises(AuthenticationRequiredError):
        remote.start(h.owner_ids["B"], cmd.binding.action_key)
    assert calls == []


@pytest.mark.parametrize("foreign_result", [False, True])
def test_remote_cleanup_settlement_validates_actual_native_owner_and_kept_receipt(workflow, foreign_result):
    import httpx
    from app.infrastructure.supabase_data import SupabaseDataClient
    from app.infrastructure.workflow_repos import SupabaseWorkflowMutations

    h, owner = workflow, workflow.owner_ids["A"]
    service, _local, state, _storage, cmd, deleted = setup_cleanup(h, "pdf")
    actual = service.cleanup(owner, cmd.binding.action_key)
    proof = next(iter(state.media_delete_verifications.values()))
    if foreign_result:
        actual = actual.model_copy(update={"result": actual.result.model_copy(update={"patient_id": h.owner_ids["B"]})})
    calls = []

    def respond(request):
        calls.append(request.url.path)
        return httpx.Response(
            200,
            json=[deleted.receipt.model_dump(mode="json")]
            if request.method == "GET"
            else {"result": actual.model_dump(mode="json")},
        )

    data = SupabaseDataClient(
        base_url="https://example.invalid",
        publishable_key="sb_publishable_DEMO",
        access_token="DEMO-token",
        patient_id=owner,
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    cls = importlib.import_module("app.infrastructure.workflow_media_cleanup").SupabaseMediaCleanupTickets
    remote = cls(data=data, receipts=SupabaseWorkflowMutations(data))
    if foreign_result:
        with pytest.raises(ProviderUnavailableError):
            remote.settle(owner, proof)
    else:
        assert remote.settle(owner, proof) == actual
        assert calls == ["/rest/v1/rpc/assistant_media_cleanup_command", "/rest/v1/assistant_business_receipts"]


def test_cleanup_cannot_use_absence_in_another_storage_bucket(workflow):
    h, owner = workflow, workflow.owner_ids["A"]
    service, _port, _state, storage, cmd, deleted = setup_cleanup(h, "pdf")

    class WrongBucket:
        bucket_id = "visual-references"

        def delete(self, path):
            pass

        def observe(self, path):
            return None

    service._storage = WrongBucket()
    with pytest.raises(ProviderUnavailableError):
        service.cleanup(owner, cmd.binding.action_key)
    assert storage.get(deleted.result.storage_path)
    assert h.container.library_files.metadata(owner, deleted.result.id, include_deleted=True).cleanup_pending
