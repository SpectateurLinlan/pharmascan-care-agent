"""DEMO_ONLY patient HTTP source saves through real original/service boundaries."""

from uuid import uuid4

import pytest

from .test_workflow_originals import original_png
from .test_workflow_photo_enrollment import label
from .test_workflow_source_originals import original
from .workflow_support import WorkflowHarness


def review_context(h, source_task):
    from app.contracts.assistant_workflows import BusinessRef, WorkflowContext, WorkflowTask

    task = h.container.assistant_workflows._repository.create(
        WorkflowTask(
            id=uuid4(),
            owner=h.owner_ids["A"],
            workspace_id=uuid4(),
            capability_id="medication.source.review",
            state="awaiting_confirmation",
            save_mode="allowed",
            storage_state="saved",
            updated_at=h.clock.now(),
            business_refs=(BusinessRef(kind="enrollment_task", id=source_task.id, version=source_task.version),),
        )
    )
    return WorkflowContext(owner=task.owner, task_id=task.id, revision=task.revision, capability_id=task.capability_id)


def source_review(h, context, target, **changes):
    payload = {
        "draft": {
            "medication_name": target.product.name,
            "dose_amount": 1,
            "dose_unit": "tablet",
            "frequency_rule": {"kind": "daily", "local_times": ["08:00"]},
        },
        "patient_reviewed": True,
    }
    payload.update(changes)
    return h.client.post(
        f"/api/evidence/tasks/{target.id}/review",
        params={"client_id": "DEMO-workflow-A"},
        headers={"X-Assistant-Task": str(context.task_id), "X-Assistant-Revision": str(context.revision)},
        json=payload,
    )


def test_source_review_binds_the_actual_unactivated_plan_to_its_current_workflow(workflow, monkeypatch):
    from .test_workflow_enrollment_operations import services
    from .test_workflow_sources import inputs, provider

    h = workflow
    provider(h, monkeypatch)
    target = h.container.evidence_enrollment.attach(**inputs(h))
    context = review_context(h, target)
    result = source_review(h, context, target)
    assert result.status_code == 200, result.text
    operation, _ = services(h)
    from uuid import UUID

    binding = operation.binding(context.owner, UUID(result.json()["draft_regimen_id"]))
    assert binding is not None and binding.workflow_task_id == context.task_id
    replay = source_review(h, context, target)
    assert replay.status_code == 200 and replay.json() == result.json()
    assert len(h.snapshot()["regimens"]) == 1 and h.snapshot()["regimens"][0]["state"] == "draft"
    assert not h.snapshot()["dose_events"]


@pytest.mark.parametrize("failure", ["stale", "revoked", "target"])
def test_source_review_rechecks_workflow_authority_before_reviewing_evidence(workflow, monkeypatch, failure):
    from .test_workflow_sources import inputs, provider

    h = workflow
    provider(h, monkeypatch)
    target = h.container.evidence_enrollment.attach(**inputs(h))
    context = review_context(h, target)
    if failure == "stale":
        context = context.model_copy(update={"revision": context.revision + 1})
    if failure == "target":
        target = h.container.evidence_enrollment.attach(**inputs(h))
    if failure == "revoked":
        h.container.assistant_cleanup.cancel_save(context.owner, context.task_id, context.revision)
    before = h.snapshot()
    response = source_review(h, context, target)
    assert response.status_code in {400, 403, 404, 409}, response.text
    assert h.snapshot()["sources"] == before["sources"] and h.snapshot()["regimens"] == before["regimens"]


def test_source_review_binding_failure_rolls_back_review_and_new_plan(workflow, monkeypatch):
    from .test_workflow_sources import inputs, provider

    h = workflow
    provider(h, monkeypatch)
    target = h.container.evidence_enrollment.attach(**inputs(h))
    context = review_context(h, target)

    def failed(*args, **kwargs):
        raise OSError("DEMO source binding failure")

    from app.application.enrollment_operations import EnrollmentOperationService

    monkeypatch.setattr(EnrollmentOperationService, "bind_existing_once", failed)
    before = h.snapshot()
    with pytest.raises(OSError, match="DEMO source binding failure"):
        source_review(h, context, target)
    assert h.snapshot()["sources"] == before["sources"] and h.snapshot()["regimens"] == before["regimens"]


def test_source_review_binds_the_actual_next_plan_version_without_assuming_version_one(workflow, monkeypatch):
    from uuid import UUID

    from app.contracts.dto import FrequencyRuleDTO, RegimenDraftInput

    from .test_workflow_enrollment_operations import services
    from .test_workflow_sources import inputs, provider

    h = workflow
    provider(h, monkeypatch)
    target = h.container.evidence_enrollment.attach(**inputs(h))
    h.container.enrollment.enroll_draft(
        patient_id=h.owner_ids["A"],
        existing_medication_id=target.medication_id,
        draft=RegimenDraftInput(
            medication_name=target.product.name,
            dose_amount=1,
            dose_unit="tablet",
            frequency_rule=FrequencyRuleDTO(kind="daily", local_times=["08:00"]),
        ),
    )
    context = review_context(h, target)
    response = source_review(h, context, target)
    assert response.status_code == 200, response.text
    operation, _ = services(h)
    assert operation.binding(context.owner, UUID(response.json()["draft_regimen_id"])).version_no == 2


def save(h, context, target, attachment, *, owner="A", revision=None, body=None):
    return h.client.post(
        f"/api/evidence/tasks/{target}/saved-original",
        params={"client_id": "DEMO-workflow-" + owner},
        headers={
            "X-Assistant-Task": str(context.task_id),
            "X-Assistant-Revision": str(revision or context.revision),
        },
        json=body or {"attachment_id": str(attachment), "confirmed": True},
    )


def test_patient_source_save_replays_actual_result_without_recognition_or_duplicate_rows():
    with WorkflowHarness(source_results=[label()]) as h:
        context, target, uploaded = original(h)
        first = save(h, context, target, uploaded.id)
        assert first.status_code == 200, first.text
        second = save(h, context, target, uploaded.id)
        assert second.status_code == 200 and second.json() == first.json()
        assert first.json()["id"] == str(target)
        assert len(h.snapshot()["sources"]) == len(h.snapshot()["medications"]) == 1
        assert len(h.source_calls) == 1
        assert h.container.assistant_attachments.read(context.owner, context.task_id, uploaded.id)[0] == original_png()


@pytest.mark.parametrize("failure", ["owner", "stale", "target", "attachment", "revoked", "unconfirmed", "forged"])
def test_patient_source_save_refuses_invalid_authority_without_clinical_writes(failure):
    with WorkflowHarness(source_results=[label()]) as h:
        context, target, uploaded = original(h)
        kwargs = {}
        if failure == "owner":
            kwargs["owner"] = "B"
        if failure == "stale":
            kwargs["revision"] = context.revision + 1
        if failure == "target":
            target = uuid4()
        attachment = uuid4() if failure == "attachment" else uploaded.id
        if failure == "revoked":
            h.container.assistant_cleanup.cancel_save(context.owner, context.task_id, context.revision)
        if failure in {"unconfirmed", "forged"}:
            kwargs["body"] = {"attachment_id": str(attachment), "confirmed": failure != "unconfirmed"}
            if failure == "forged":
                kwargs["body"]["extraction"] = label().model_dump(mode="json")
        result = save(h, context, target, attachment, **kwargs)
        assert result.status_code in {400, 403, 404, 409, 422}, result.text
        assert result.json().get("detail") != "Not Found"
        assert not h.snapshot()["sources"] and not h.snapshot()["medications"]


def test_patient_source_save_requires_current_assistant_binding_and_independent_confirmation():
    with WorkflowHarness(source_results=[label()]) as h:
        context, target, uploaded = original(h)
        response = h.client.post(
            f"/api/evidence/tasks/{target}/saved-original",
            params={"client_id": "DEMO-workflow-A"},
            json={"attachment_id": str(uploaded.id), "confirmed": True},
        )
        assert response.status_code == 422, response.text
        assert not h.snapshot()["sources"]


@pytest.mark.parametrize("mode", ["ordinary", "other_workflow"])
def test_saved_source_review_cannot_bypass_the_original_workflow_authority(mode):
    with WorkflowHarness(source_results=[label()]) as h:
        context, target, uploaded = original(h)
        saved = save(h, context, target, uploaded.id)
        assert saved.status_code == 200, saved.text
        actual = h.container.evidence_enrollment.get(context.owner, target)
        before = h.snapshot()
        if mode == "ordinary":
            response = h.client.post(
                f"/api/evidence/tasks/{target}/review",
                params={"client_id": "DEMO-workflow-A"},
                json={
                    "patient_reviewed": True,
                    "draft": {
                        "medication_name": actual.product.name,
                        "dose_amount": 1,
                        "dose_unit": "tablet",
                        "frequency_rule": {"kind": "daily", "local_times": ["08:00", "20:00"]},
                    },
                },
            )
        else:
            response = source_review(
                h,
                review_context(h, actual),
                actual,
                draft={
                    "medication_name": actual.product.name,
                    "dose_amount": 1,
                    "dose_unit": "tablet",
                    "frequency_rule": {"kind": "daily", "local_times": ["08:00", "20:00"]},
                },
            )
        assert response.status_code in {400, 403, 409}, response.text
        assert h.snapshot()["sources"] == before["sources"] and h.snapshot()["regimens"] == before["regimens"]


def test_ordinary_source_upload_cannot_mutate_a_workflow_registration_without_its_current_binding(monkeypatch):
    from .test_workflow_sources import provider

    with WorkflowHarness(source_results=[label()]) as h:
        context, target, uploaded = original(h)
        assert save(h, context, target, uploaded.id).status_code == 200
        provider(h, monkeypatch)
        before = h.snapshot()
        response = h.client.post(
            f"/api/evidence/tasks/{target}/sources?source_kind=pharmacy_label&client_id=DEMO-workflow-A",
            content=original_png(),
            headers={"Content-Type": "image/png", "X-Stage2-Consent": "true"},
        )
        assert response.status_code == 409, response.text
        assert h.snapshot()["sources"] == before["sources"]


def test_source_changed_between_patient_binding_check_and_transaction_requires_new_review(workflow, monkeypatch):
    from io import BytesIO

    from PIL import Image

    from .test_workflow_sources import inputs, provider

    h = workflow
    provider(h, monkeypatch)
    evidence = h.container.evidence_enrollment
    target = evidence.attach(**inputs(h))
    context = review_context(h, target)
    original_prepare = evidence.prepare_review
    extra = BytesIO()
    Image.new("RGB", (80, 80), "yellow").save(extra, format="PNG")

    def concurrent_change(**kwargs):
        values = inputs(h)
        values.update(task_id=target.id, medication_id=target.medication_id, image=extra.getvalue())
        evidence.attach(**values)
        return original_prepare(**kwargs)

    monkeypatch.setattr(evidence, "prepare_review", concurrent_change)
    response = source_review(h, context, target)
    assert response.status_code == 409, response.text
    assert not h.snapshot()["regimens"]
    assert all(row["review_status"] == "extracted" for row in h.snapshot()["sources"])


def test_ordinary_upload_must_not_ignore_an_assistant_binding_for_a_pending_target(monkeypatch):
    from .test_workflow_sources import provider

    with WorkflowHarness(source_results=[label()]) as h:
        context, target, _uploaded = original(h)
        provider(h, monkeypatch)
        response = h.client.post(
            f"/api/evidence/tasks/{target}/sources?source_kind=pharmacy_label&client_id=DEMO-workflow-A",
            content=original_png(),
            headers={
                "Content-Type": "image/png",
                "X-Stage2-Consent": "true",
                "X-Assistant-Task": str(context.task_id),
                "X-Assistant-Revision": str(context.revision),
            },
        )
        assert response.status_code == 422, response.text
        assert not h.snapshot()["sources"] and not h.snapshot()["medications"]
