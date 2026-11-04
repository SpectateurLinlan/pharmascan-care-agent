"""Actual memory/CAS and owned service effects; external timing only is controlled."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from app.agent.capabilities import build_capability_registry
from app.application.assistant_capabilities.enrollment import EnrollmentAdapter
from app.application.assistant_workflows import WorkflowService
from app.contracts.assistant_workflows import BusinessRef, OperationResult, WorkflowContext, WorkflowEvent
from app.contracts.long_term import StockInput
from app.domain.errors import DuplicateEventError, NotFoundError, StaleVersionError
from app.infrastructure.memory_workflows import MemoryWorkflowRepository


def start(h):
    return h.container.assistant_workflows.start(
        h.owner_ids["A"], "medication.enroll", UUID(h.workspace_id), None, {}, "allowed",
    )


def test_saved_event_replay_returns_the_same_applied_revision(workflow):
    h = workflow
    service = h.container.assistant_workflows
    first = start(h)
    event = WorkflowEvent(event_id=uuid4(), expected_revision=first.revision, kind="choose_method",
                          values={"method": "manual"})
    applied = service.advance(h.owner_ids["A"], first.task_id, event)
    replay = service.advance(h.owner_ids["A"], first.task_id, event)
    assert replay == applied
    assert service.view(h.owner_ids["A"], first.task_id).revision == applied.revision


def test_saved_event_id_cannot_be_rebound_to_different_input(workflow):
    h = workflow
    service = h.container.assistant_workflows
    first = start(h)
    event = WorkflowEvent(event_id=uuid4(), expected_revision=first.revision, kind="choose_method",
                          values={"method": "manual"})
    service.advance(h.owner_ids["A"], first.task_id, event)
    with pytest.raises(DuplicateEventError):
        service.advance(h.owner_ids["A"], first.task_id, event.model_copy(update={"values": {"method": "photo"}}))
    assert service.view(h.owner_ids["A"], first.task_id).visible_fields["method"] == "manual"


def test_simultaneous_duplicate_delivery_returns_one_applied_result_to_both_requests(workflow):
    h = workflow
    barrier = Barrier(2)

    class SimultaneousCAS(MemoryWorkflowRepository):
        def cas(self, *args, **kwargs):
            barrier.wait(timeout=5)
            return super().cas(*args, **kwargs)

    service = WorkflowService(
        repository=SimultaneousCAS(h.clock), registry=build_capability_registry(),
        adapters={"medication.enroll": EnrollmentAdapter(h.container.enrollment)}, clock=h.clock, ids=h.container.ids,
        conversations=h.container.conversation_threads, preferences=h.container.preferences,
    )
    first = service.start(h.owner_ids["A"], "medication.enroll", uuid4(), None, {}, "allowed")
    event = WorkflowEvent(event_id=uuid4(), expected_revision=first.revision, kind="choose_method",
                          values={"method": "manual"})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: service.advance(h.owner_ids["A"], first.task_id, event), range(2)))
    assert results[0] == results[1] and results[0].revision == first.revision + 1


def test_two_events_for_the_same_revision_accept_only_one(workflow):
    h = workflow
    service = h.container.assistant_workflows
    first = start(h)
    barrier = Barrier(2)

    def submit(method):
        barrier.wait(timeout=5)
        try:
            service.advance(h.owner_ids["A"], first.task_id, WorkflowEvent(
                event_id=uuid4(), expected_revision=first.revision, kind="choose_method", values={"method": method},
            ))
            return "accepted"
        except StaleVersionError:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, ("manual", "photo")))
    assert sorted(results) == ["accepted", "stale"]
    assert service.view(h.owner_ids["A"], first.task_id).revision == first.revision + 1


def test_concurrent_starts_have_only_one_foreground_task(workflow):
    h = workflow
    barrier = Barrier(2)

    class SimultaneousCreate(MemoryWorkflowRepository):
        def create(self, task, **kwargs):
            barrier.wait(timeout=5)
            return super().create(task, **kwargs)

    repository = SimultaneousCreate(h.clock)
    service = WorkflowService(
        repository=repository, registry=build_capability_registry(),
        adapters={"medication.enroll": EnrollmentAdapter(h.container.enrollment)}, clock=h.clock, ids=h.container.ids,
        conversations=h.container.conversation_threads, preferences=h.container.preferences,
    )
    workspace = uuid4()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: service.start(h.owner_ids["A"], "medication.enroll", workspace, None, {}, "allowed"),
                      range(2)))
    rows = repository.list(h.owner_ids["A"], workspace)
    assert len(rows) == 2 and sum(row.state == "suspended" for row in rows) == 1


def test_unknown_operation_is_observed_without_creating_or_replaying_business_records(workflow):
    from app.application.workflow_operations import WorkflowOperationService
    from app.infrastructure.memory_workflows import MemoryActionRepository

    h = workflow
    context = WorkflowContext(owner=h.owner_ids["A"], task_id=uuid4(), revision=1,
                              capability_id="inventory.count")
    operations = WorkflowOperationService(repository=MemoryActionRepository(h.clock), observers={}, clock=h.clock)
    key = uuid4()
    operations.reserve(context, key)
    before = h.snapshot()
    assert operations.reconcile(context.owner, key).state == "outcome_unknown"
    assert operations.reconcile(context.owner, key).state == "outcome_unknown"
    assert h.snapshot() == before
    with pytest.raises(NotFoundError):
        operations.read(h.owner_ids["B"], key)


def test_lost_business_response_is_recovered_from_an_owned_stock_transaction(workflow):
    from app.application.workflow_operations import WorkflowOperationService
    from app.infrastructure.memory_workflows import MemoryActionRepository

    h = workflow
    medication_id = UUID(h.seed_reviewed_medication()["medication_id"])
    context = WorkflowContext(owner=h.owner_ids["A"], task_id=uuid4(), revision=1,
                              capability_id="inventory.count")

    class OwnedStockObserver:
        def observe(self, current, result_ref):
            stock = h.container.long_term.inventory(current.owner, medication_id)
            found = any(row.id == result_ref.id for row in stock.transactions)
            return OperationResult(
                state="succeeded" if found else "pending", business_ref=result_ref if found else None,
            )

    operations = WorkflowOperationService(repository=MemoryActionRepository(h.clock),
                                          observers={"inventory.count": OwnedStockObserver()}, clock=h.clock)
    key = uuid4()
    target = BusinessRef(kind="stock", id=key)
    operations.reserve(context, key, target=target)
    confirmed = StockInput(id=key, kind="count", quantity=12, unit="tablet", confirmed=True)
    # This is the original patient-confirmed application service, not an Agent write tool.
    h.container.long_term.record_stock(context.owner, medication_id, confirmed, context.timezone)
    # Drop the successful response; retain only the pre-write action receipt.
    observed = operations.reconcile(context.owner, key)
    assert observed.state == "succeeded" and observed.business_ref == target
    replay = operations.reserve(context, key, target=target)
    assert replay.state == "succeeded" and replay.business_ref == target
    h.container.long_term.record_stock(context.owner, medication_id, confirmed, context.timezone)
    assert len(h.container.long_term.inventory(context.owner, medication_id).transactions) == 1


def test_operation_key_is_stable_and_bound_to_the_prepared_revision(workflow):
    from app.application.workflow_operations import WorkflowOperationService
    from app.infrastructure.memory_workflows import MemoryActionRepository

    h = workflow
    context = WorkflowContext(owner=h.owner_ids["A"], task_id=uuid4(), revision=1, capability_id="inventory.count")
    operations = WorkflowOperationService(repository=MemoryActionRepository(h.clock), observers={}, clock=h.clock)
    first = operations.reserve(context)
    assert operations.reserve(context).action_key == first.action_key
    changed = context.model_copy(update={"revision": 2})
    assert operations.reserve(changed).action_key != first.action_key
    with pytest.raises(StaleVersionError):
        operations.reserve(changed, first.action_key)


def test_content_free_lease_expires_without_automatic_takeover_and_revocation_blocks_late_finish(workflow):
    from app.contracts.assistant_workflows import ControlReceipt
    from app.domain.errors import ValidationError
    from app.infrastructure.memory_workflows import MemoryControlRepository

    h = workflow
    controls = MemoryControlRepository(h.clock)
    owner, task_id, event_id = h.owner_ids["A"], uuid4(), uuid4()
    controls.create(ControlReceipt(owner=owner, task_id=task_id, revision=1,
                                   capability_id="medication.enroll", mode="ephemeral"))
    claim = controls.claim(owner, task_id, 1, event_id, "medication.enroll", "ephemeral")
    assert claim.processing_event_id == event_id and claim.lease_until > h.clock.now()
    with pytest.raises(ValidationError):
        controls.claim(owner, task_id, 1, uuid4(), "medication.enroll", "ephemeral")
    h.clock.advance(seconds=46)
    with pytest.raises(StaleVersionError):
        controls.claim(owner, task_id, 1, uuid4(), "medication.enroll", "ephemeral")
    revoked = controls.revoke(owner, task_id, 1)
    assert revoked.revoked and revoked.revision == 2
    with pytest.raises(StaleVersionError):
        controls.finish(owner, task_id, 1, event_id)
    with pytest.raises(NotFoundError):
        controls.get(h.owner_ids["B"], task_id)
    assert set(revoked.model_dump()) <= {"task_id", "owner", "revision", "capability_id", "mode", "revoked",
                                        "processing_event_id", "lease_until", "workspace_id", "conversation_id", "status"}
