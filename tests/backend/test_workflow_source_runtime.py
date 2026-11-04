"""Real local composition and deterministic source entry, no model/provider call."""

import pytest

from .test_workflow_enrollment import message


@pytest.mark.parametrize(
    "phrase,capability",
    [
        ("add a medication source", "medication.source.add"),
        ("添加药物来源", "medication.source.add"),
        ("review medication sources", "medication.source.review"),
        ("核对药物来源", "medication.source.review"),
    ],
)
def test_source_entry_uses_the_composed_chat_workflow_without_clinical_writes(workflow, phrase, capability):
    h = workflow
    response = message(h, phrase)
    assert response["reply"]["mode"] == "workflow" and response["workflow"]["capability_id"] == capability
    assert not h.snapshot()["sources"] and not h.snapshot()["medications"]


def test_local_capability_catalog_reports_sources_available_but_other_unimplemented_features_unavailable(workflow):
    result = workflow._request("GET", "/api/agent/workflows/capabilities")
    catalog = {row["id"]: row for row in result["capabilities"]}
    assert catalog["medication.source.add"]["available"] and catalog["medication.source.review"]["available"]
    assert catalog["medication.plan.change"]["available"] is True
    assert catalog["inventory.count"]["available"] is True
    assert catalog["gallery.photo.add"]["available"] is False


def test_source_review_returns_to_the_original_saved_source_task_instead_of_adopting_it():
    from uuid import uuid4

    from .test_workflow_photo_enrollment import label
    from .test_workflow_source_originals import original
    from .workflow_support import WorkflowHarness

    with WorkflowHarness(source_results=[label()]) as h:
        context, target, uploaded = original(h)
        saved = h.container.assistant_sources.save(context, target, uploaded.id, uuid4())
        original_view = h.event(str(context.task_id), "report_business_result", revision=context.revision)
        h.workspace_id = original_view["workspace_id"]
        review = h.start(
            "medication.source.review", {"source_task_id": str(saved.id), "expected_version": saved.version}
        )
        assert review["actions"][0]["kind"] == "resume_task"
        before = h.snapshot()
        resumed = h._request(
            "POST",
            f"/api/agent/workflows/tasks/{review['task_id']}/resume-draft",
            json={"expected_revision": review["revision"]},
        )
        assert resumed["task_id"] == original_view["task_id"] and resumed["result_ref"]["id"] == str(saved.id)
        assert h.snapshot()["sources"] == before["sources"] and h.snapshot()["regimens"] == before["regimens"]


def test_an_old_source_review_stays_readable_when_its_source_version_changes():
    from uuid import uuid4

    from .test_workflow_photo_enrollment import label
    from .test_workflow_source_originals import original
    from .test_workflow_source_transport import source_review
    from .workflow_support import WorkflowHarness

    with WorkflowHarness(source_results=[label()]) as h:
        context, target, uploaded = original(h)
        saved = h.container.assistant_sources.save(context, target, uploaded.id, uuid4())
        h.event(str(context.task_id), "report_business_result", revision=context.revision)
        other = h.start(
            "medication.source.review", {"source_task_id": str(saved.id), "expected_version": saved.version}
        )
        resumed = h._request(
            "POST",
            f"/api/agent/workflows/tasks/{other['task_id']}/resume-draft",
            json={"expected_revision": other["revision"]},
        )
        actual_context = h.container.assistant_attachments.context(context.owner, context.task_id, resumed["revision"])
        result = source_review(
            h,
            actual_context,
            saved,
            draft={
                "medication_name": saved.product.name,
                "dose_amount": 1,
                "dose_unit": "tablet",
                "frequency_rule": {"kind": "daily", "local_times": ["08:00", "20:00"]},
            },
        )
        assert result.status_code == 200, result.text
        rows = h._request("GET", "/api/agent/workflows/tasks")
        previous = next(row for row in rows if row["task_id"] == other["task_id"])
        assert previous["state"] == "suspended" and not previous["actions"]
