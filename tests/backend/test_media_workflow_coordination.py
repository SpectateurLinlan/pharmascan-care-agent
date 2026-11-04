"""DEMO_ONLY actual HTTP media bridges; no SQL, provider or cloud calls."""

import importlib
from uuid import UUID, uuid5

import pytest

from .test_persistent_media_transactions import harness
from .test_workflow_media import seed_media
from .test_workflow_media_lifecycle import CHANGE_IDS, fields, prepare, request


def wire(h):
    from app.infrastructure.memory_workflows import MemoryWorkflowMutations

    cls = importlib.import_module("app.application.workflow_media_transactions").MediaWorkflowTransactions
    w = h.container.assistant_workflows
    port = harness(h)
    coordinator = cls(
        writes=port,
        tasks=w._repository,
        receipts=MemoryWorkflowMutations(h.clock, state=w._repository._state),
        drafts=h.container.assistant_media.adapter.drafts,
        preferences=h.container.preferences,
    )
    w._business_transactions = dict.fromkeys(coordinator.capability_ids, coordinator)
    h.container.assistant_media.transactions = coordinator
    return coordinator, port


@pytest.mark.parametrize("capability", CHANGE_IDS)
def test_media_native_http_uses_typed_transaction_and_real_cleanup(workflow, monkeypatch, capability):
    from .test_verified_media_cleanup import setup_cleanup

    h, owner = workflow, workflow.owner_ids["A"]
    coordinator, port = wire(h)
    med, photo, pdf = seed_media(h)
    w = h.container.assistant_workflows
    cas = w._repository.cas
    changes = []

    def counted(*args, **kwargs):
        changes.append(args)
        return cas(*args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("Typed media cannot execute generic business callbacks")

    monkeypatch.setattr(w._repository, "cas", counted)
    monkeypatch.setattr(w._controls, "guarded_write", forbidden)
    task = prepare(h, capability, fields(capability, med, photo, pdf))
    assert port.lookup(owner, UUID(task["result_ref"]["id"])).outcome == "prepared"
    assert len(changes) == 1
    deleting = capability.endswith("delete")
    if deleting:
        pending = request(h, task)
        assert pending.status_code == 503, pending.text
        view = h.view(task["task_id"])
        assert view["state"] == "outcome_unknown" and view["storage_state"] == "cleanup_pending"
        assert view["input_fields"] == task["input_fields"] and len(changes) == 2
        assert view["visible_fields"]["media_review"]["cleanup_retry"] is True
        assert view["actions"][0]["owned_ref"] == view["result_ref"]
        cmd = coordinator.confirmation_command(owner, UUID(task["task_id"]), task["revision"])
        assert cmd.binding.action_key == uuid5(UUID(task["result_ref"]["id"]), "media-patient-confirmation")
        service, _, _, storage, _, deleted = setup_cleanup(
            h, "photo" if capability.startswith("gallery.") else "pdf", deletion=(port, cmd)
        )
        assert storage.get(deleted.result.storage_path)
        coordinator.cleanup_services[capability] = service
    saved = request(h, task)
    assert saved.status_code == 200, saved.text
    assert request(h, task).json() == saved.json()
    assert len(changes) == (3 if deleting else 2)
    monkeypatch.setattr(port, "apply", forbidden)
    final = h.event(task["task_id"], "report_business_result")
    assert final["state"] == "completed"
    assert final["visible_fields"]["saved_record"]["version"] == 2
    assert not final["visible_fields"]["saved_record"]["cleanup_pending"]
    assert "storage_path" not in str(final["visible_fields"])
    assert len(changes) == (3 if deleting else 2)


@pytest.mark.parametrize("guard", ["paused", "revoked", "target", "payload", "confirmation", "revision"])
def test_media_typed_boundary_refuses_changed_patient_review(workflow, guard):
    from uuid import uuid4

    h = workflow
    wire(h)
    med, photo, pdf = seed_media(h)
    task = prepare(h, "gallery.photo.edit", fields("gallery.photo.edit", med, photo, pdf))
    kwargs = {}
    if guard == "paused":
        h.event(task["task_id"], "pause")
    elif guard == "revoked":
        h.event(task["task_id"], "cancel_save")
    elif guard == "target":
        kwargs["target"] = str(uuid4())
    elif guard == "payload":
        kwargs["body"] = {**task["visible_fields"]["media_review"]["payload"], "source_description": "DEMO tampered"}
    elif guard == "confirmation":
        kwargs["confirmed"] = False
        kwargs["body"] = {**task["visible_fields"]["media_review"]["payload"], "confirmed": False}
    else:
        kwargs["headers"] = {"X-Assistant-Task": task["task_id"], "X-Assistant-Revision": "1"}
    denied = request(h, task, **kwargs)
    assert denied.status_code in {404, 409, 422}, denied.text
    actual = h.container.gallery.metadata(h.owner_ids["A"], UUID(photo["id"]))
    assert actual.metadata_version == 1


def test_bound_cleanup_unknown_response_never_repeats_physical_delete(workflow, monkeypatch):
    from .test_verified_media_cleanup import setup_cleanup

    h = workflow
    coordinator, port = wire(h)
    med, photo, pdf = seed_media(h)
    task = prepare(h, "library.pdf.delete", fields("library.pdf.delete", med, photo, pdf))
    assert request(h, task).status_code == 503
    cmd = coordinator.confirmation_command(h.owner_ids["A"], UUID(task["task_id"]), task["revision"])
    service, _, _, storage, _, deleted = setup_cleanup(h, "pdf", deletion=(port, cmd))
    coordinator.cleanup_services[task["capability_id"]] = service
    calls = []
    monkeypatch.setattr(storage, "delete", lambda path: calls.append(path))
    assert request(h, task).status_code == 503
    assert request(h, task).status_code == 409
    assert calls == [deleted.result.storage_path]
    assert storage.get(deleted.result.storage_path)
    pending = h.view(task["task_id"])
    assert pending["state"] == "outcome_unknown" and pending["visible_fields"]["saved_record"]["cleanup_pending"]


def test_remote_media_read_without_receipt_never_calls_a_mutation_rpc(workflow):
    from app.domain.errors import NotFoundError
    from app.infrastructure.workflow_media_writes import SupabaseMediaWorkflowWrites

    from .test_persistent_media_transactions import command

    h = workflow
    local, cmd = command(h, "library.pdf.edit")
    with pytest.raises(NotFoundError):
        local.read(h.owner_ids["A"], cmd)

    class Data:
        def check_patient(self, owner):
            assert owner == h.owner_ids["A"]

        def request(self, *args, **kwargs):
            raise AssertionError("Missing receipt must never fall through to a native mutation RPC")

    class Receipts:
        def read_receipt(self, owner, action):
            return None

    with pytest.raises(NotFoundError):
        SupabaseMediaWorkflowWrites(data=Data(), receipts=Receipts()).read(h.owner_ids["A"], cmd)
