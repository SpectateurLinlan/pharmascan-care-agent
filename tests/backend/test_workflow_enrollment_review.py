"""P05 review regressions through real owned DEMO services and HTTP boundaries."""

from uuid import UUID, uuid4

import pytest

from .test_workflow_enrollment import message
from .test_workflow_originals import original_png
from .test_workflow_photo_enrollment import label
from .workflow_support import WorkflowHarness


@pytest.mark.parametrize(
    "changes,answer,field,expected",
    [
        ({"dose_unit": None}, "tablet", "dose_unit", "tablet"),
        ({"dose_unit": None}, "片", "dose_unit", "tablet"),
        ({"dose_amount": None}, "2", "dose_amount", 2),
        (
            {"frequency_rule": {"kind": "interval", "every_hours": 6}},
            "2026-11-01",
            "course_start_date",
            "2026-11-01",
        ),
    ],
)
def test_reply_to_requested_single_slot_advances_without_requiring_a_field_label(
    workflow, changes, answer, field, expected
):
    h = workflow
    first = h.start(
        "medication.enroll",
        {
            "method": "manual",
            "medication_name": "DEMO prompted slot",
            "dose_amount": 1,
            "dose_unit": "tablet",
            "frequency_rule": {"kind": "daily", "local_times": ["08:00"]},
            **changes,
        },
    )
    assert field in first["missing_fields"]
    reply = message(h, answer, first)["workflow"]
    assert reply["visible_fields"].get(field) == expected
    assert field not in reply["missing_fields"] and not h.snapshot()["regimens"]


def test_unrelated_prepared_edit_preserves_default_interval_time_provenance(workflow):
    h = workflow
    first = h.start(
        "medication.enroll",
        {
            "method": "manual",
            "medication_name": "DEMO default interval",
            "dose_amount": 1,
            "dose_unit": "tablet",
            "frequency_rule": {"kind": "interval", "every_hours": 6},
            "course_start_date": "2026-11-01",
        },
    )
    before = h.event(first["task_id"], "prepare_confirmation")
    prior = h.container.enrollment.get_regimen(h.owner_ids["A"], UUID(before["result_ref"]["id"]))
    assert prior.frequency_rule["interval_anchor"]["time_source"] == "default_0800"
    revised = h.event(first["task_id"], "provide_fields", {"dose_amount": 2})
    assert revised["prompt_key"] == "assistant.enrollment.interval_default"
    after = h.event(first["task_id"], "prepare_confirmation")
    current = h.container.enrollment.get_regimen(h.owner_ids["A"], UUID(after["result_ref"]["id"]))
    assert current.frequency_rule["interval_anchor"]["time_source"] == "default_0800"
    assert current.dose_amount == 2 and prior.dose_amount == 1


def test_additional_original_retains_current_prepared_review_and_raw_bytes():
    with WorkflowHarness(source_results=[label(), label()]) as h:
        first = h.start("medication.enroll", {"method": "photo"})
        uploaded = h.upload(first["task_id"], original_png())
        message(h, "08:00, 20:00", uploaded["workflow"])
        prepared = h.event(first["task_id"], "prepare_confirmation")
        extra = h.upload(first["task_id"], original_png())
        assert extra["workflow"]["state"] == "awaiting_confirmation"
        saved = h._request("GET", f"/api/medications/drafts/{prepared['result_ref']['id']}")
        h._request("POST", f"/api/medications/drafts/{saved['source_id']}/review", json={"field_ids": None})
        assert h.read_original(extra["attachment"]["id"]) == original_png()
        assert h.view(first["task_id"])["result_ref"] == prepared["result_ref"]
        assert len(h.snapshot()["regimens"]) == 1


def test_excess_photo_products_fail_recoverably_without_silently_hiding_candidates():
    extraction = label()
    item = extraction.candidates[0]
    extraction = extraction.model_copy(
        update={
            "candidates": [
                item.model_copy(update={"product": item.product.model_copy(update={"name": f"DEMO product {i + 1}"})})
                for i in range(21)
            ]
        }
    )
    with WorkflowHarness(source_results=[extraction]) as h:
        first = h.start("medication.enroll", {"method": "photo"})
        result = h.upload(first["task_id"], original_png())
        assert result["workflow"]["state"] == "failed_recoverable"
        assert result["workflow"]["prompt_key"] == "assistant.enrollment.too_many_products"
        assert not any(action["kind"] == "choice" for action in result["workflow"]["actions"])
        assert h.read_original(result["attachment"]["id"]) == original_png()
        assert not h.snapshot()["regimens"]


def test_twice_daily_printed_instructions_cannot_be_prepared_as_a_weekly_plan():
    with WorkflowHarness(source_results=[label()]) as h:
        first = h.start("medication.enroll", {"method": "photo"})
        uploaded = h.upload(first["task_id"], original_png())
        changed = h.event(
            first["task_id"],
            "provide_fields",
            {
                "frequency_rule": {"kind": "weekly", "days_of_week": [1], "local_times": ["08:00", "20:00"]},
                "times_per_day": None,
            },
        )
        response = h.client.post(
            f"/api/agent/workflows/tasks/{first['task_id']}/events",
            params={"client_id": "DEMO-workflow-A"},
            json={
                "event_id": str(uuid4()),
                "expected_revision": changed["revision"],
                "kind": "prepare_confirmation",
                "values": {},
            },
        )
        assert response.status_code == 422
        assert h.read_original(uploaded["attachment"]["id"]) == original_png()
        assert not h.snapshot()["regimens"]
