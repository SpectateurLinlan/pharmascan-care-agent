"""DEMO_ONLY source normalization/proof preparation never publishes clinical rows."""

import importlib
from contextlib import contextmanager
from uuid import UUID, uuid4

import pytest
from app.contracts.assistant_workflows import BusinessRef
from app.contracts.workflow_persistence import WorkflowWriteBinding
from app.domain.errors import ProviderUnavailableError, StaleVersionError


@contextmanager
def scenario():
    from app.application.workflow_media_storage import MediaCopyVerificationService
    from app.application.workflow_verification import WorkflowVerificationService
    from app.infrastructure.enrollment_operations import InMemoryEnrollmentWritePort
    from app.infrastructure.evidence_images import patient_reference_image, patient_source_image
    from app.infrastructure.verified_original_repos import MemoryStorageVerifier, MemoryVerifiedOriginals
    from app.infrastructure.workflow_media_storage import MemoryMediaCopyTickets, MemoryMediaCopyVerifier

    from .test_persistent_medication_transactions import api, harness
    from .test_workflow_originals import original_png
    from .test_workflow_photo_enrollment import label
    from .workflow_support import WorkflowHarness

    with WorkflowHarness(source_results=[label()]) as h:
        originals = h.container.assistant_attachments
        state = originals._repository._state
        raw = MemoryVerifiedOriginals(
            state=state,
            clock=h.clock,
            originals=originals._repository,
            controls=originals._controls,
            cleanup=h.container.assistant_cleanup._repository,
        )
        originals._verification = WorkflowVerificationService(
            repository=raw,
            storage=originals._storage,
            verifier=MemoryStorageVerifier(state=state, clock=h.clock),
            clock=h.clock,
        )
        view = h.start("medication.source.add", {})
        uploaded = h.upload(view["task_id"], original_png())
        view = uploaded["workflow"]
        native = harness(h)
        owner = h.owner_ids["A"]
        binding = WorkflowWriteBinding(
            task_id=UUID(view["task_id"]),
            task_revision=view["revision"],
            capability_id="medication.source.add",
            action_key=uuid4(),
            prepared_ref=BusinessRef(kind="media_review", id=UUID(view["task_id"]), version=view["revision"] + 1),
            expected_domain_revision=native.revision(owner),
        )
        native.apply(owner, api("PrepareSourceReview")(binding=binding))
        current = originals._tasks.get(owner, binding.task_id)
        command = api("SaveSourceRegistration")(
            binding=binding.model_copy(
                update={
                    "task_revision": current.revision,
                    "action_key": uuid4(),
                    "expected_domain_revision": native.revision(owner),
                }
            ),
            attachment_id=UUID(uploaded["attachment"]["id"]),
            confirmed=True,
        )
        copies = MemoryMediaCopyTickets(state=state, clock=h.clock, originals=raw, controls=originals._controls)
        copier = MediaCopyVerificationService(
            tickets=copies,
            originals=raw,
            source_storage=originals._storage,
            target_storage=h.container.gallery._storage,
            verifier=MemoryMediaCopyVerifier(state=state, clock=h.clock),
            clock=h.clock,
            normalize=patient_reference_image,
            source_normalize=patient_source_image,
        )
        cls = importlib.import_module("app.application.workflow_source_materialization").SourceMaterializationService
        service = cls(
            operations=h.container.assistant_sources,
            originals=raw,
            copies=copies,
            copier=copier,
            domain=InMemoryEnrollmentWritePort(h.container.store),
        )
        yield h, service, raw, copies, command, state


def test_source_materialization_uses_source_normalizer_without_callback_or_clinical_publication(monkeypatch):
    from app.infrastructure.evidence_images import patient_source_image

    with scenario() as (h, service, raw, copies, command, state):
        owner = h.owner_ids["A"]
        before = h.snapshot()
        calls = len(h.source_calls)
        h.container.evidence_enrollment._source_writer = None

        def forbidden(*args, **kwargs):
            raise AssertionError("Persistent source proposal cannot execute a generic guarded callback")

        monkeypatch.setattr(h.container.assistant_attachments._controls, "guarded_write", forbidden)
        result = service.materialize(owner, command)
        image = result.metadata.image
        ticket = copies.read_verified(owner, result.copy_verification)
        assert ticket.target.media_kind == "source_image" and ticket.target.source_kind == "pharmacy_label"
        assert ticket.target.native_id == image.id and ticket.target.object_ref == image.storage_path
        original = raw.get(owner, command.binding.task_id, command.attachment_id)
        content = h.container.assistant_attachments._storage.read(owner, original.object_ref)
        assert h.container.gallery._storage.get(image.storage_path) == patient_source_image(content)
        assert h.snapshot() == before and len(h.source_calls) == calls
        assert result.original_verification.verification_id in state.storage_verifications
        assert result.copy_verification.verification_id in state.media_storage_verifications
        assert original.source_ref is None and not result.duplicate


def test_unverified_raw_original_cannot_start_a_native_source_copy():
    with scenario() as (h, service, _raw, _copies, command, state):
        state.storage_verifications.clear()
        with pytest.raises(ProviderUnavailableError):
            service.materialize(h.owner_ids["A"], command)
        assert not state.media_storage_tickets and not h.snapshot()["sources"]


def test_deleting_original_cannot_be_materialized_as_a_native_source():
    with scenario() as (h, service, _raw, _copies, command, state):
        state.deleting_originals.add((h.owner_ids["A"], command.attachment_id))
        with pytest.raises(StaleVersionError):
            service.materialize(h.owner_ids["A"], command)
        assert not state.media_storage_tickets and not h.snapshot()["sources"]


def test_repreparing_the_same_source_action_reuses_native_identity_and_copy_key():
    with scenario() as (h, service, _raw, _copies, command, _state):
        first = service.materialize(h.owner_ids["A"], command)
        second = service.materialize(h.owner_ids["A"], command)
        assert first.metadata.medication.id == second.metadata.medication.id
        assert first.metadata.image.id == second.metadata.image.id
        assert first.metadata.image.storage_path == second.metadata.image.storage_path
        assert [field.id for field in first.metadata.fields] == [field.id for field in second.metadata.fields]


def test_duplicate_source_materialization_reads_existing_facts_without_rewriting_them():
    from .test_persistent_medication_transactions import harness

    with scenario() as (h, service, _raw, _copies, command, _state):
        owner = h.owner_ids["A"]
        native = harness(h)
        saved = native.apply(owner, command)
        task = native._tasks.get(owner, command.binding.task_id)
        duplicate = command.model_copy(
            update={
                "binding": command.binding.model_copy(
                    update={
                        "task_revision": task.revision,
                        "action_key": uuid4(),
                        "prepared_ref": saved.receipt.business_ref,
                        "expected_domain_revision": native.revision(owner),
                    }
                )
            }
        )
        before = h.snapshot()
        result = service.materialize(owner, duplicate)
        assert result.duplicate and result.metadata.task == saved.result
        assert result.metadata.source.id == saved.result.source_ids[0]
        assert result.metadata.prior_task == saved.result and not result.metadata.create_medication
        assert h.snapshot() == before


def test_remote_original_verification_lookup_rechecks_the_actual_owned_ticket():
    import httpx
    from app.infrastructure.supabase_data import SupabaseDataClient
    from app.infrastructure.verified_original_repos import SupabaseVerifiedOriginals

    with scenario() as (h, _service, raw, _copies, command, _state):
        owner = h.owner_ids["A"]
        proof = raw.verification_for(owner, command.binding.task_id, command.attachment_id)
        ticket = raw.read_verified(owner, proof)
        calls = []

        def respond(request):
            calls.append(request.url.path)
            value = proof if request.url.path.endswith("assistant_original_verification_ref") else ticket
            return httpx.Response(200, json={"result": value.model_dump(mode="json")})

        data = SupabaseDataClient(
            base_url="https://example.invalid",
            publishable_key="sb_publishable_DEMO",
            access_token="DEMO-token",
            patient_id=owner,
            client=httpx.Client(transport=httpx.MockTransport(respond)),
        )
        remote = SupabaseVerifiedOriginals(data)
        assert remote.verification_for(owner, command.binding.task_id, command.attachment_id) == proof
        assert calls == ["/rest/v1/rpc/assistant_original_verification_ref", "/rest/v1/rpc/assistant_original_command"]


def test_source_materialization_reuses_verified_copy_after_registration_failure(monkeypatch):
    with scenario() as (h, service, _raw, copies, command, state):
        first = service.materialize(h.owner_ids["A"], command)

        def forbidden(*args, **kwargs):
            raise AssertionError("A recovered source copy must not issue another writer")

        monkeypatch.setattr(copies, "reserve", forbidden)
        second = service.materialize(h.owner_ids["A"], command)
        assert second.copy_verification == first.copy_verification
        assert len(state.media_storage_tickets) == 1
