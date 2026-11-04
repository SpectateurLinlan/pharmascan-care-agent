"""Real workflow coordinator and memory repositories; no business-write stubs."""

from uuid import uuid4

import pytest
from app.agent.capabilities import build_capability_registry
from app.application.assistant_capabilities.enrollment import EnrollmentAdapter
from app.application.assistant_workflows import WorkflowService
from app.contracts.assistant_workflows import WorkflowEvent
from app.domain.errors import NotFoundError, StaleVersionError, ValidationError
from app.infrastructure.memory_workflows import MemoryWorkflowRepository


@pytest.fixture
def engine(workflow):
    repository = MemoryWorkflowRepository(workflow.clock)
    service = WorkflowService(
        repository=repository, registry=build_capability_registry(),
        adapters={"medication.enroll": EnrollmentAdapter(workflow.container.enrollment)},
        clock=workflow.clock, ids=workflow.container.ids, conversations=workflow.container.conversation_threads,
        preferences=workflow.container.preferences,
    )
    return service, repository, workflow


def advance(service, owner, view, kind, values=None):
    return service.advance(owner, view.task_id, WorkflowEvent(
        event_id=uuid4(), expected_revision=view.revision, kind=kind, values=values or {},
    ))


def start(engine, *, workspace=None, owner=None):
    service, _, h = engine
    return service.start(owner or h.owner_ids["A"], "medication.enroll", workspace or uuid4(), None, {}, "allowed")


def test_enrollment_begins_with_real_method_options_and_no_invented_medication(engine):
    first = start(engine)
    assert first.state == "choose_method"
    assert {option.value for option in first.actions[0].options} == {"manual", "photo"}
    assert first.storage_state == "saved"
    assert not engine[2].snapshot()["medications"] and not engine[2].snapshot()["regimens"]


def test_collection_keeps_supplied_fields_and_only_asks_for_missing_information(engine):
    service, _, h = engine
    view = advance(service, h.owner_ids["A"], start(engine), "choose_method", {"method": "manual"})
    view = advance(service, h.owner_ids["A"], view, "provide_fields", {
        "medication_name": "DEMO-only medicine", "frequency_rule": {"kind": "daily", "local_times": ["08:00"]},
    })
    assert "medication_name" not in view.missing_fields and "frequency_rule" not in view.missing_fields
    assert {"dose_amount", "dose_unit"} <= set(view.missing_fields)
    assert view.visible_fields["medication_name"] == "DEMO-only medicine"
    assert not h.snapshot()["medications"]


def test_new_foreground_task_suspends_previous_task_only_in_the_same_workspace(engine):
    service, _, h = engine
    workspace = uuid4()
    first = start(engine, workspace=workspace)
    second = start(engine, workspace=workspace)
    assert service.view(h.owner_ids["A"], first.task_id).state == "suspended"
    start(engine, workspace=uuid4())
    assert service.view(h.owner_ids["A"], second.task_id).state == "choose_method"


def test_pause_resume_and_owner_boundaries_do_not_rewrite_another_owners_task(engine):
    service, _, h = engine
    view = advance(service, h.owner_ids["A"], start(engine), "pause")
    assert view.state == "suspended"
    with pytest.raises(NotFoundError):
        service.view(h.owner_ids["B"], view.task_id)
    view = advance(service, h.owner_ids["A"], view, "resume")
    assert view.state == "choose_method"


def test_stale_fields_and_authority_injection_are_rejected_without_state_changes(engine):
    service, _, h = engine
    first = start(engine)
    current = advance(service, h.owner_ids["A"], first, "choose_method", {"method": "manual"})
    with pytest.raises(StaleVersionError):
        advance(service, h.owner_ids["A"], first, "provide_fields", {"medication_name": "DEMO-stale"})
    with pytest.raises((ValidationError, ValueError)):
        advance(service, h.owner_ids["A"], current, "provide_fields", {"confirmed": True, "patient_id": str(uuid4())})
    assert service.view(h.owner_ids["A"], current.task_id).revision == current.revision


def test_cancelled_task_is_read_only_and_returned_fields_cannot_mutate_saved_state(engine):
    service, _, h = engine
    first = advance(service, h.owner_ids["A"], start(engine), "choose_method", {"method": "manual"})
    first.visible_fields["method"] = "photo"
    assert service.view(h.owner_ids["A"], first.task_id).visible_fields["method"] == "manual"
    cancelled = advance(service, h.owner_ids["A"], first, "cancel_task")
    with pytest.raises(ValidationError):
        advance(service, h.owner_ids["A"], cancelled, "resume")
