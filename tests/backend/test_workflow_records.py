"""DEMO records use actual public reads, never generate clinical rows."""

from uuid import UUID, uuid4

import pytest

from .test_workflow_medication_management import active_plan


def records_engine(h):
    from app.application.assistant_capabilities.records import RecordAdapter
    from app.application.assistant_workflows import WorkflowService

    old = h.container.assistant_workflows
    adapter = RecordAdapter(
        enrollment=h.container.enrollment,
        schedule=h.container.schedule,
        reports=h.container.self_report,
        history=h.container.record_history,
        summary=h.container.review_summary,
        understanding=h.container.medication_understanding,
        clock=h.clock,
        preferences=h.container.preferences,
    )
    return WorkflowService(
        repository=old._repository,
        registry=old._registry,
        adapters={**old._adapters, **dict.fromkeys(adapter.capability_ids, adapter)},
        clock=h.clock,
        ids=h.container.ids,
        conversations=h.container.conversation_threads,
        preferences=h.container.preferences,
        controls=old._controls,
    )


def clinical(h):
    store = h.container.store
    return {
        name: dict(getattr(store, name).items())
        for name in (
            "medications",
            "regimens",
            "sources",
            "source_fields",
            "dose_rules",
            "occurrences",
            "events",
            "challenges",
        )
    }


@pytest.mark.parametrize(
    "capability,key",
    [
        ("medication.today", "today"),
        ("medication.due", "today"),
        ("medication.status", "history"),
        ("medication.history", "history"),
        ("medication.source.view", "sources"),
        ("record.catalogue", "catalogue"),
        ("record.history", "history"),
        ("record.summary", "summary"),
        ("record.visit.prepare", "summary"),
        ("medication.instructions", "understanding"),
    ],
)
def test_each_record_read_returns_real_owned_data_without_clinical_side_effects(workflow, capability, key):
    h = workflow
    old = active_plan(h)
    service = records_engine(h)
    before = clinical(h)
    inputs = {"medication_id": old["medication_id"]} if capability.startswith("medication.") else {}
    view = service.start(h.owner_ids["A"], capability, uuid4(), None, inputs, "allowed")
    assert key in view.visible_fields and not view.result_ref
    assert not any(action.kind == "existing_review" for action in view.actions)
    assert clinical(h) == before and not h.knowledge_requests
    if capability.startswith("medication."):
        assert view.visible_fields["medication_name"] == "DEMO-workflow-medicine"


def test_status_and_history_keep_patient_day_and_stored_record_coverage_without_backfill(workflow):
    h = workflow
    old = active_plan(h)
    service = records_engine(h)
    before = clinical(h)
    view = service.start(
        h.owner_ids["A"],
        "medication.status",
        uuid4(),
        None,
        {"medication_id": old["medication_id"], "day": "2026-10-12"},
        "allowed",
    )
    history = view.visible_fields["history"]
    assert history["scope"] == "stored_records_only" and history["entries"] == []
    assert history["window_start"] == "2026-10-11T16:00:00Z"
    assert history["window_end"] == "2026-10-12T16:00:00Z"
    assert clinical(h) == before


@pytest.mark.parametrize(
    "capability", ["medication.status", "medication.history", "medication.source.view", "medication.instructions"]
)
def test_owned_record_read_refuses_another_patients_medication(workflow, capability):
    from app.domain.errors import NotFoundError

    h = workflow
    old = active_plan(h)
    service = records_engine(h)
    before = clinical(h)
    with pytest.raises(NotFoundError):
        service.start(h.owner_ids["B"], capability, uuid4(), None, {"medication_id": old["medication_id"]}, "allowed")
    assert clinical(h) == before


def test_future_status_is_refused_instead_of_becoming_today(workflow):
    from app.domain.errors import ValidationError

    h = workflow
    old = active_plan(h)
    service = records_engine(h)
    with pytest.raises(ValidationError):
        service.start(
            h.owner_ids["A"],
            "medication.status",
            uuid4(),
            None,
            {"medication_id": old["medication_id"], "day": "2026-10-14"},
            "allowed",
        )


def test_no_save_read_exposes_closed_inputs_and_no_saved_task_or_patient_rows(workflow):
    from app.contracts.assistant_workflows import validate_workflow_values

    h = workflow
    old = active_plan(h)
    service = records_engine(h)
    before = clinical(h)
    view = service.start(
        h.owner_ids["A"], "medication.status", uuid4(), None, {"medication_id": old["medication_id"]}, "ephemeral"
    )
    validate_workflow_values(view.capability_id, view.input_fields)
    assert "history" not in view.input_fields and "medication_name" not in view.input_fields
    assert not service.saved_tasks(h.owner_ids["A"]) and clinical(h) == before


def test_summary_uses_existing_calendar_week_scope_and_coverage_limit(workflow):
    h = workflow
    active_plan(h)
    service = records_engine(h)
    view = service.start(h.owner_ids["A"], "record.visit.prepare", uuid4(), None, {}, "allowed")
    assert view.visible_fields["summary"]["period"] == "week"
    assert view.visible_fields["summary"]["window_start"] == "2026-10-11T16:00:00Z"
    assert "not reconstructed" in view.visible_fields["summary"]["coverage_note"]
    assert view.visible_fields["summary"]["reported_taken"] == 0


def test_status_day_uses_the_patients_dst_boundary_without_creating_history(workflow):
    h = workflow
    old = active_plan(h)
    h.clock.advance(days=20, hours=13)
    h._request("PUT", "/api/me/preferences", json={"timezone": "America/New_York"})
    before = clinical(h)
    service = records_engine(h)
    view = service.start(
        h.owner_ids["A"],
        "medication.status",
        uuid4(),
        None,
        {"medication_id": old["medication_id"], "day": "2026-11-01"},
        "allowed",
    )
    assert view.visible_fields["history"]["window_start"] == "2026-11-01T04:00:00Z"
    assert view.visible_fields["history"]["window_end"] == "2026-11-02T05:00:00Z"
    assert clinical(h) == before


def test_history_cursor_reads_next_real_stored_record_and_refuses_rebound_filters(workflow):
    from app.domain.errors import ValidationError

    h = workflow
    old = active_plan(h)
    h.container.schedule.materialize(patient_id=h.owner_ids["A"], regimen_id=UUID(old["regimen_id"]), days=7)
    h.clock.advance(days=2, hours=14)
    before = clinical(h)
    service = records_engine(h)
    fields = {"medication_id": old["medication_id"], "limit": 1, "range_kind": "7"}
    first = service.start(h.owner_ids["A"], "record.history", uuid4(), None, fields, "allowed")
    cursor = first.visible_fields["history"]["next_cursor"]
    assert cursor and len(first.visible_fields["history"]["entries"]) == 1
    second = service.start(h.owner_ids["A"], "record.history", uuid4(), None, {**fields, "cursor": cursor}, "allowed")
    assert second.visible_fields["history"]["entries"][0]["id"] != first.visible_fields["history"]["entries"][0]["id"]
    with pytest.raises(ValidationError):
        service.start(
            h.owner_ids["A"],
            "record.history",
            uuid4(),
            None,
            {**fields, "range_kind": "30", "cursor": cursor},
            "allowed",
        )
    assert clinical(h) == before


@pytest.mark.parametrize("capability", ["medication.source.view", "record.history"])
def test_mismatched_owned_medicine_and_plan_are_refused(workflow, capability):
    from app.domain.errors import ValidationError

    h = workflow
    first = active_plan(h)
    second = active_plan(h, "DEMO other medicine")
    service = records_engine(h)
    before = clinical(h)
    with pytest.raises(ValidationError):
        service.start(
            h.owner_ids["A"],
            capability,
            uuid4(),
            None,
            {"medication_id": first["medication_id"], "regimen_id": second["regimen_id"]},
            "allowed",
        )
    assert clinical(h) == before


def test_history_query_rejects_confirmation_and_owner_fields():
    from app.contracts.assistant_workflows import validate_workflow_values
    from pydantic import ValidationError

    for key in ("confirmed", "patient_id", "action_key", "challenge_id"):
        with pytest.raises(ValidationError):
            validate_workflow_values("record.history", {key: str(uuid4())})


def test_source_read_pages_originals_without_losing_the_selected_medicine(workflow):
    from app.contracts.assistant_workflows import WorkflowEvent

    from .test_workflow_enrollment_operations import services
    from .test_workflow_plan_changes import update_input

    h = workflow
    old = active_plan(h)
    operation, _ = services(h)
    for amount in range(2, 13):
        operation.prepare_plan_change_once(h.owner_ids["A"], update_input(h, old, dose_amount=amount))
    service = records_engine(h)
    before = clinical(h)
    first = service.start(
        h.owner_ids["A"], "medication.source.view", uuid4(), None, {"medication_id": old["medication_id"]}, "allowed"
    )
    assert len(first.visible_fields["sources"]) == 10
    second = service.advance(
        h.owner_ids["A"],
        first.task_id,
        WorkflowEvent(event_id=uuid4(), expected_revision=first.revision, kind="provide_fields", values={"page": 1}),
    )
    assert len(second.visible_fields["sources"]) == 2
    assert second.input_fields["medication_id"] == old["medication_id"] and clinical(h) == before


def test_due_query_exposes_actual_recorded_times_without_materialization(workflow):
    h = workflow
    old = active_plan(h)
    h.clock.advance(hours=13)
    service = records_engine(h)
    before = clinical(h)
    view = service.start(h.owner_ids["A"], "medication.due", uuid4(), None, {}, "allowed")
    row = view.visible_fields["today"]["plans"][0]
    assert row["regimen_id"] == old["regimen_id"] and row["scheduled_times"] == ["2026-10-13T12:00:00Z"]
    assert clinical(h) == before


def test_saved_source_query_stays_readable_after_the_patient_deletes_its_unfinished_medication(workflow):
    h = workflow
    draft = h._request("POST", "/api/medications/drafts", json={"medication_name": "DEMO temporary source"})
    service = records_engine(h)
    view = service.start(
        h.owner_ids["A"], "medication.source.view", uuid4(), None, {"medication_id": draft["medication_id"]}, "allowed"
    )
    result = h.container.draft_deletion.delete(h.owner_ids["A"], "draft", UUID(draft["regimen_id"]), True)
    assert result.deleted and result.medication_deleted
    saved = service.view(h.owner_ids["A"], view.task_id)
    assert saved.state == "failed_recoverable" and not saved.actions
    assert any(row.task_id == view.task_id for row in service.list_views(h.owner_ids["A"]))


@pytest.mark.parametrize(
    "phrase,capability",
    [
        ("show today's medicines", "medication.today"),
        ("查看今日用药", "medication.today"),
        ("show due doses", "medication.due"),
        ("查看待自述剂次", "medication.due"),
        ("check medication status", "medication.status"),
        ("查看服药状态", "medication.status"),
        ("show medication history", "medication.history"),
        ("查看用药历史", "medication.history"),
        ("view medication sources", "medication.source.view"),
        ("查看药物原始来源", "medication.source.view"),
        ("show record catalogue", "record.catalogue"),
        ("查看记录目录", "record.catalogue"),
        ("show medication records", "record.history"),
        ("查看服药记录", "record.history"),
        ("show weekly medication summary", "record.summary"),
        ("查看本周用药统计", "record.summary"),
        ("prepare for my visit", "record.visit.prepare"),
        ("准备复诊", "record.visit.prepare"),
        ("show my medication instructions", "medication.instructions"),
        ("查看我的服药说明", "medication.instructions"),
    ],
)
def test_record_chat_entry_uses_actual_composed_read_without_patient_writes(workflow, phrase, capability):
    from .test_workflow_enrollment import message

    h = workflow
    active_plan(h)
    before = clinical(h)
    response = message(h, phrase)
    assert response["reply"]["mode"] == "workflow" and response["workflow"]["capability_id"] == capability
    assert clinical(h) == before


def test_record_catalog_reports_actual_read_availability_but_no_model_report_execution(workflow):
    catalog = {row["id"]: row for row in workflow._request("GET", "/api/agent/workflows/capabilities")["capabilities"]}
    for capability in ("medication.today", "medication.instructions", "record.history", "record.visit.prepare"):
        assert catalog[capability]["available"]
    assert catalog["dose.report"]["available"] and catalog["dose.report"]["mode"] == "patient_ui"
    from app.agent.capabilities import build_capability_registry
    from app.contracts.assistant_capabilities import CapabilityAvailability

    model = build_capability_registry().model_catalog(
        CapabilityAvailability(
            workflows_enabled=True,
            services=frozenset({"self_report"}),
            adapters=frozenset({"records"}),
            implemented_capabilities=workflow.container.assistant_workflows.implemented_capabilities(),
        )
    )
    assert not any(row.id in {"dose.report", "dose.prn.report"} for row in model)
    assert not catalog["medication.knowledge"]["available"]
