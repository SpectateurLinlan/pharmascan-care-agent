"""DEMO_ONLY unknown operations retain per-writer and deletion exclusion state."""

from uuid import uuid4

import pytest
from app.contracts.assistant_workflows import WorkflowUpdate
from app.contracts.workflow_attachments import ProtectionResult
from app.domain.errors import ProviderUnavailableError, StaleVersionError

from .test_verified_workflow_originals import harness


class Exclusive:
    def references(self, owner, attachment_id):
        return ProtectionResult(protected=False, reason="exclusive")


def saved_and_revoked():
    values = harness()
    service, port, _, _, _, _, controls, context, row, content = values
    service.save(context, row.id, row.upload_id, content)
    controls.revoke(row.owner, row.task_id, 2, uuid4())
    port._protection = Exclusive()
    return values


def test_one_unknown_writer_keeps_cleanup_pending_even_after_expiry_and_404():
    service, port, _, state, clock, originals, controls, context, row, content = harness()
    ticket = port.reserve_ticket(context, row.id, row.upload_id)
    port.claim_ticket(row.owner, ticket)
    # Another writer's matching bytes cannot acknowledge the older active attempt.
    second = uuid4()
    state.originals[(row.owner, row.id)] = row.model_copy(
        update={"operation_event_id": second, "pending_writer_ids": (row.upload_id, second), "multiple_writers": True}
    )
    other = port.reserve_ticket(context, row.id, second)
    port.claim_ticket(row.owner, other)
    proof = service.settle(service._observation(other, "bytes_verified", content=content))
    port.settle_writer(row.owner, proof)
    controls.revoke(row.owner, row.task_id, 1, uuid4())
    clock.advance(seconds=46)
    port._protection = Exclusive()
    pending = service.cleanup(row.owner, row.id)
    assert pending.state == "pending" and pending.pending_writer_ids == (row.upload_id,)
    assert (row.owner, row.id) not in state.deleting_originals


def test_deleting_blocks_native_reference_and_late_publish():
    service, port, _, state, _, originals, _, context, row, content = saved_and_revoked()
    port.start_deleting(row.owner, row.id)
    from app.contracts.assistant_workflows import WorkflowTask
    from app.infrastructure.memory_workflows import MemoryWorkflowRepository

    tasks = MemoryWorkflowRepository(port._clock, state=state)
    other = tasks.create(
        WorkflowTask(
            id=uuid4(),
            owner=row.owner,
            workspace_id=uuid4(),
            capability_id="medication.enroll",
            updated_at=port._clock.now(),
        )
    )
    with pytest.raises(StaleVersionError):
        tasks.cas(
            row.owner,
            other.id,
            1,
            uuid4(),
            WorkflowUpdate(
                state="collecting", save_mode="allowed", storage_state="saved", fields={}, attachment_ids=(row.id,)
            ),
        )
    with pytest.raises(StaleVersionError):
        service._storage.put_original(
            row.owner, row.task_id, uuid4(), content, row.content_type, object_ref=row.object_ref
        )


def test_unknown_delete_forbids_key_reuse_and_is_not_retried():
    service, port, _, state, _, _, _, _, row, content = saved_and_revoked()
    real = service._storage

    class UnknownDelete:
        calls = 0

        def delete(self, *args):
            self.calls += 1
            raise ProviderUnavailableError("DEMO network ended while delete may continue")

    unknown = UnknownDelete()
    service._storage = unknown
    with pytest.raises(ProviderUnavailableError):
        service.cleanup(row.owner, row.id)
    assert service.cleanup(row.owner, row.id).state == "pending" and unknown.calls == 1
    with pytest.raises(StaleVersionError):
        real.put_original(row.owner, row.task_id, uuid4(), content, row.content_type, object_ref=row.object_ref)
    assert state.cleanup[(row.owner, row.id)].state != "deleted"


def test_only_matching_completed_delete_settles_cleanup():
    service, port, _, state, _, _, _, _, row, _ = saved_and_revoked()
    deleted = service.cleanup(row.owner, row.id)
    assert deleted.state == "deleted" and (row.owner, row.object_ref) not in state.original_objects
    assert (row.owner, row.id) in state.deleting_originals
    assert service.cleanup(row.owner, row.id).state == "deleted"


def test_existing_cleanup_consumer_uses_verified_operation_and_rejects_legacy_ack():
    from app.application.workflow_cleanup import WorkflowCleanupService

    from .conftest import CountingIdGenerator

    service, port, _, state, _, originals, controls, _, row, _ = saved_and_revoked()
    cleanup = WorkflowCleanupService(
        controls=controls,
        repository=port._cleanup,
        originals=originals,
        storage=service._storage,
        protection=Exclusive(),
        ids=CountingIdGenerator(),
        verification=service,
    )
    with pytest.raises(ProviderUnavailableError):
        cleanup.written(row.owner, row.task_id, row.id, row.upload_id)
    result = cleanup.retry_cleanup(row.owner, row.task_id)
    assert result[0].state == "deleted"
    assert (row.owner, row.object_ref) not in state.original_objects


def test_formal_source_protection_is_not_lowered():
    service, port, _, state, _, _, _, _, row, _ = saved_and_revoked()

    class Protected:
        def references(self, owner, attachment_id):
            return ProtectionResult(protected=True, reason="formal_source")

    port._protection = Protected()
    result = service.cleanup(row.owner, row.id)
    assert result.state == "protected" and result.reason == "formal_source"
    assert (row.owner, row.object_ref) in state.original_objects
    assert (row.owner, row.id) not in state.deleting_originals
    port._protection = Exclusive()
    later = service.cleanup(row.owner, row.id)
    assert later.state == "protected" and (row.owner, row.id) not in state.deleting_originals
