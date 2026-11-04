"""DEMO_ONLY public native medication services share the coupled memory boundary."""

import importlib
from uuid import UUID, uuid4

import pytest
from app.contracts.assistant_workflows import BusinessRef
from app.contracts.workflow_persistence import WorkflowWriteBinding
from app.domain.errors import DuplicateEventError, StaleVersionError
from app.infrastructure.enrollment_operations import InMemoryEnrollmentWritePort

from .test_workflow_enrollment_operations import ready, values


def api(name):
    return getattr(importlib.import_module("app.contracts.workflow_medication_writes"), name)


def harness(h):
    from app.application.enrollment_operations import EnrollmentOperationService

    cls = importlib.import_module("app.infrastructure.workflow_medication_writes").MemoryMedicationWorkflowWrites
    attachments = h.container.assistant_attachments
    enrollments = InMemoryEnrollmentWritePort(h.container.store)
    return cls(
        state=attachments._repository._state,
        store=h.container.store,
        clock=h.clock,
        tasks=attachments._tasks,
        controls=attachments._controls,
        originals=attachments._repository,
        enrollment=h.container.enrollment,
        enrollments=enrollments,
        operations=EnrollmentOperationService(h.container.enrollment, enrollments),
        deletions=h.container.draft_deletion._repository,
        source_operations=h.container.assistant_sources,
        source_transactions=h.container.evidence_enrollment._source_writer,
        evidence=h.container.evidence_enrollment,
        source_adapter=h.container.assistant_workflows._adapters["medication.source.add"],
    )


def prepare(h, port):
    view = ready(h)
    owner, task_id = h.owner_ids["A"], UUID(view["task_id"])
    prepared = h.container.enrollment.prepare_draft(patient_id=owner, draft=values().fields.draft)
    prepared = prepared.model_copy(update={"workflow_task_id": task_id, "workflow_revision": view["revision"]})
    binding = WorkflowWriteBinding(
        task_id=task_id,
        task_revision=view["revision"],
        capability_id="medication.enroll",
        action_key=uuid4(),
        prepared_ref=BusinessRef(
            kind="regimen", id=prepared.result.regimen.id, version=prepared.result.regimen.version_no
        ),
        expected_domain_revision=port.revision(owner),
    )
    command = api("PrepareMedication")(binding=binding, prepared=prepared, binding_digest="a" * 64)
    return owner, command


def test_manual_prepare_has_owned_atomic_receipt_and_task_association(workflow):
    port = harness(workflow)
    owner, command = prepare(workflow, port)
    result = port.apply(owner, command)
    task = workflow.container.assistant_attachments._tasks.get(owner, command.binding.task_id)
    assert result.result.regimen_id == command.prepared.result.regimen.id
    assert result.receipt.outcome == "prepared" and result.receipt.business_ref == command.binding.prepared_ref
    assert task.state == "awaiting_confirmation" and task.business_refs == (result.receipt.business_ref,)
    assert workflow.container.enrollment.get_regimen(owner, result.result.regimen_id).state.value == "draft"
    assert port.lookup(uuid4(), command.binding.action_key) is None


def test_lost_response_reconciles_without_rewriting(workflow):
    port = harness(workflow)
    owner, command = prepare(workflow, port)
    first = port.apply(owner, command)
    before = workflow.snapshot()
    assert port.lookup(owner, command.binding.action_key) == first.receipt
    assert port.apply(owner, command) == first
    assert workflow.snapshot() == before
    altered = command.model_copy(update={"binding_digest": "b" * 64})
    with pytest.raises(DuplicateEventError):
        port.apply(owner, altered)


def test_equivalent_source_maps_reconcile_the_same_preparation(workflow):
    h, port = workflow, harness(workflow)
    owner, command = prepare(h, port)
    original = port.apply(owner, command)
    rows = [
        row.model_copy(update={"field_value": dict(reversed(list(row.field_value.items())))})
        if isinstance(row.field_value, dict)
        else row
        for row in command.prepared.result.source_fields
    ]
    same = command.model_copy(
        update={
            "prepared": command.prepared.model_copy(
                update={"result": command.prepared.result.model_copy(update={"source_fields": rows})}
            )
        }
    )
    before = h.snapshot()
    assert port.apply(owner, same).receipt == original.receipt
    assert h.snapshot() == before


def test_task_failure_rolls_back_native_draft_and_receipt(workflow, monkeypatch):
    port = harness(workflow)
    owner, command = prepare(workflow, port)
    before = workflow.snapshot()

    def reject(*args, **kwargs):
        raise StaleVersionError("DEMO task update failed after native preparation")

    monkeypatch.setattr(port._tasks, "cas", reject)
    with pytest.raises(StaleVersionError):
        port.apply(owner, command)
    assert workflow.snapshot() == before
    assert port.lookup(owner, command.binding.action_key) is None
    assert InMemoryEnrollmentWritePort(workflow.container.store).lookup(owner, command.binding.action_key) is None


def test_old_task_or_domain_revision_cannot_create_native_draft(workflow):
    port = harness(workflow)
    owner, command = prepare(workflow, port)
    stale = command.model_copy(update={"binding": command.binding.model_copy(update={"expected_domain_revision": 999})})
    with pytest.raises(StaleVersionError):
        port.apply(owner, stale)
    assert not workflow.snapshot()["regimens"] and port.lookup(owner, command.binding.action_key) is None


@pytest.mark.parametrize("changed", ["dose", "source_fields"])
def test_prepared_rows_must_match_the_current_saved_patient_inputs(workflow, changed):
    from app.domain.errors import ValidationError

    h, port = workflow, harness(workflow)
    owner, command = prepare(h, port)
    proposal = command.prepared
    if changed == "dose":
        result = proposal.result.model_copy(
            update={"regimen": proposal.result.regimen.model_copy(update={"dose_amount": 2})}
        )
    else:
        rows = proposal.result.source_fields
        result = proposal.result.model_copy(
            update={"source_fields": [rows[0].model_copy(update={"field_value": "DEMO different value"}), *rows[1:]]}
        )
    altered = command.model_copy(update={"prepared": proposal.model_copy(update={"result": result})})
    before = h.snapshot()
    with pytest.raises(ValidationError):
        port.apply(owner, altered)
    assert h.snapshot() == before and port.lookup(owner, command.binding.action_key) is None


def test_source_quantity_cannot_use_boolean_numeric_equality(workflow):
    from app.domain.errors import ValidationError

    h, port = workflow, harness(workflow)
    owner, command = prepare(h, port)
    rows = command.prepared.result.source_fields
    changed = [
        row.model_copy(update={"field_value": True}) if row.field_name.value == "dose_amount" else row for row in rows
    ]
    bad = command.model_copy(
        update={
            "prepared": command.prepared.model_copy(
                update={"result": command.prepared.result.model_copy(update={"source_fields": changed})}
            )
        }
    )
    with pytest.raises(ValidationError):
        port.apply(owner, bad)


def native_action(h, port, owner, original, name, **values):
    task = h.container.assistant_attachments._tasks.get(owner, original.binding.task_id)
    binding = WorkflowWriteBinding(
        task_id=task.id,
        task_revision=task.revision,
        capability_id=task.capability_id,
        action_key=uuid4(),
        prepared_ref=original.binding.prepared_ref,
        expected_domain_revision=port.revision(owner),
    )
    return api(name)(binding=binding, **values)


def test_review_and_activation_keep_independent_current_patient_confirmation(workflow):
    h, port = workflow, harness(workflow)
    owner, command = prepare(h, port)
    result = port.apply(owner, command)
    review = native_action(
        h, port, owner, command, "ReviewMedicationSource", source_id=result.result.source_id, confirmed=True
    )
    reviewed = port.apply(owner, review)
    assert reviewed.result.reviewed_at is not None
    assert h.container.enrollment.get_regimen(owner, result.result.regimen_id).state.value == "draft"
    session = h.container.orchestrator.start_session(patient_id=owner)
    session = h.container.orchestrator.await_confirmation(patient_id=owner, session_id=session.id)
    issue = native_action(
        h,
        port,
        owner,
        command,
        "RequestMedicationChallenge",
        session_id=session.id,
        session_state_version=session.state_version,
    )
    challenge = port.apply(owner, issue).result
    assert challenge.confirmed_at is None and challenge.consumed_at is None
    assert h.container.enrollment.get_regimen(owner, result.result.regimen_id).state.value == "draft"
    # A later independent confirmation survives an expired45-second chat run.
    h.clock.advance(seconds=46)
    activate = native_action(
        h,
        port,
        owner,
        command,
        "ActivateMedication",
        challenge_id=challenge.id,
        session_state_version=session.state_version,
        confirmed=True,
    )
    activated = port.apply(owner, activate)
    assert activated.result.regimen.state.value == "active"
    assert activated.receipt.outcome == "applied"
    assert port.apply(owner, activate).receipt == activated.receipt


def test_activation_rejects_wrong_session_version_without_confirming_any_challenge(workflow):
    h, port = workflow, harness(workflow)
    owner, command = prepare(h, port)
    prepared = port.apply(owner, command)
    port.apply(
        owner,
        native_action(
            h, port, owner, command, "ReviewMedicationSource", source_id=prepared.result.source_id, confirmed=True
        ),
    )
    session = h.container.orchestrator.start_session(patient_id=owner)
    session = h.container.orchestrator.await_confirmation(patient_id=owner, session_id=session.id)
    challenge = port.apply(
        owner,
        native_action(
            h,
            port,
            owner,
            command,
            "RequestMedicationChallenge",
            session_id=session.id,
            session_state_version=session.state_version,
        ),
    ).result
    before = h.snapshot()
    with pytest.raises(StaleVersionError):
        port.apply(
            owner,
            native_action(
                h,
                port,
                owner,
                command,
                "ActivateMedication",
                challenge_id=challenge.id,
                session_state_version=session.state_version + 1,
                confirmed=True,
            ),
        )
    assert h.snapshot() == before
    assert h.container.store.challenges[(owner, challenge.id)].confirmed_at is None


def test_public_enrollment_operation_uses_the_coupled_port(workflow):
    from app.application.enrollment_operations import EnrollmentOperationService
    from app.infrastructure.workflow_medication_writes import CoupledEnrollmentWritePort

    h, port = workflow, harness(workflow)
    view = ready(h)
    writer = CoupledEnrollmentWritePort(
        native=InMemoryEnrollmentWritePort(h.container.store),
        writes=port,
        tasks=h.container.assistant_attachments._tasks,
    )
    service = EnrollmentOperationService(h.container.enrollment, writer)
    request = values().model_copy(
        update={"workflow_task_id": UUID(view["task_id"]), "workflow_revision": view["revision"]}
    )
    result = service.prepare_once(h.owner_ids["A"], request)
    receipt = port.lookup(h.owner_ids["A"], request.action_key)
    assert receipt.business_ref.id == result.regimen.id
    assert (
        h.container.assistant_attachments._tasks.get(h.owner_ids["A"], UUID(view["task_id"])).state
        == "awaiting_confirmation"
    )


def test_review_rejects_a_different_capability_even_with_an_attached_regimen(workflow):
    from app.domain.errors import ValidationError

    h, port = workflow, harness(workflow)
    owner, command = prepare(h, port)
    result = port.apply(owner, command)
    state = h.container.assistant_attachments._repository._state
    key = (owner, command.binding.task_id)
    state.tasks[key] = state.tasks[key].model_copy(update={"capability_id": "stock.adjust"})
    state.controls[key] = state.controls[key].model_copy(update={"capability_id": "stock.adjust"})
    review = native_action(
        h, port, owner, command, "ReviewMedicationSource", source_id=result.result.source_id, confirmed=True
    )
    with pytest.raises(ValidationError):
        port.apply(owner, review)


@pytest.mark.parametrize("confirmed", [False, 1, "true"])
def test_medication_confirmation_accepts_only_an_independent_true_boolean(workflow, confirmed):
    from pydantic import ValidationError

    h, port = workflow, harness(workflow)
    owner, command = prepare(h, port)
    with pytest.raises(ValidationError):
        native_action(
            h,
            port,
            owner,
            command,
            "ActivateMedication",
            challenge_id=uuid4(),
            session_state_version=1,
            confirmed=confirmed,
        )


def test_photo_prepare_binds_owned_original_and_preserves_the_unreviewed_source():
    from app.application.enrollment_operations import EnrollmentOperationService
    from app.application.workflow_verification import WorkflowVerificationService
    from app.contracts.enrollment_operations import EnrollmentOperationInput
    from app.contracts.enrollment_workflow import EnrollmentFields
    from app.infrastructure.verified_original_repos import MemoryStorageVerifier, MemoryVerifiedOriginals
    from app.infrastructure.workflow_medication_writes import CoupledEnrollmentWritePort

    from .test_workflow_enrollment import message
    from .test_workflow_originals import original_png
    from .test_workflow_photo_enrollment import label
    from .workflow_support import WorkflowHarness

    with WorkflowHarness(source_results=[label()]) as h:
        attachments = h.container.assistant_attachments
        state = attachments._repository._state
        proof_port = MemoryVerifiedOriginals(
            state=state,
            clock=h.clock,
            originals=attachments._repository,
            controls=attachments._controls,
            cleanup=h.container.assistant_cleanup._repository,
        )
        attachments._verification = WorkflowVerificationService(
            repository=proof_port,
            storage=attachments._storage,
            verifier=MemoryStorageVerifier(state=state, clock=h.clock),
            clock=h.clock,
        )
        first = h.start("medication.enroll", {"method": "photo"})
        uploaded = h.upload(first["task_id"], original_png())
        view = message(h, "08:00, 20:00", uploaded["workflow"])["workflow"]
        owner, task_id, attachment_id = h.owner_ids["A"], UUID(first["task_id"]), UUID(uploaded["attachment"]["id"])
        port = harness(h)
        writer = CoupledEnrollmentWritePort(
            native=InMemoryEnrollmentWritePort(h.container.store), writes=port, tasks=attachments._tasks
        )
        service = EnrollmentOperationService(h.container.enrollment, writer)
        request = EnrollmentOperationInput(
            action_key=uuid4(),
            fields=EnrollmentFields.model_validate(view["visible_fields"]),
            workflow_task_id=task_id,
            workflow_revision=view["revision"],
        )
        source = attachments.enrollment_source(owner, task_id, attachment_id, verify_original=True)
        from app.contracts.enums import SourceKind
        from app.domain.errors import ValidationError

        changed = h.container.enrollment.prepare_draft(
            patient_id=owner,
            draft=request.fields.draft,
            source_kind=SourceKind.PHARMACY_LABEL,
            extraction_evidence=source.extraction.model_copy(update={"extraction_model": "DEMO unrelated capture"}),
        )
        changed = changed.model_copy(
            update={
                "workflow_task_id": task_id,
                "workflow_revision": view["revision"],
                "attachment_ids": (attachment_id,),
                "source_candidate_index": 0,
            }
        )
        fake = api("PrepareMedication")(
            prepared=changed,
            binding_digest="f" * 64,
            binding=WorkflowWriteBinding(
                task_id=task_id,
                task_revision=view["revision"],
                capability_id="medication.enroll",
                action_key=uuid4(),
                prepared_ref=BusinessRef(kind="regimen", id=changed.result.regimen.id, version=1),
                expected_domain_revision=port.revision(owner),
            ),
        )
        with pytest.raises(ValidationError):
            port.apply(owner, fake)
        result = service.prepare_from_attachment(owner, request, source)
        assert port.lookup(owner, request.action_key).business_ref.id == result.regimen.id
        assert writer.for_attachment(owner, attachment_id).source_id == result.regimen.source_id
        assert h.read_original(str(attachment_id)) == original_png()
        original = attachments._repository.get(owner, task_id, attachment_id)
        assert original.source_ref == BusinessRef(kind="source", id=result.regimen.source_id)
        assert h.container.enrollment.get_source(owner, result.regimen.source_id).reviewed_at is None
        changed_view = h.event(
            first["task_id"], "provide_fields", {"frequency_rule": {"kind": "daily", "local_times": ["09:00", "21:00"]}}
        )
        later_request = EnrollmentOperationInput(
            action_key=uuid4(),
            fields=EnrollmentFields.model_validate(changed_view["visible_fields"]),
            workflow_task_id=task_id,
            workflow_revision=changed_view["revision"],
        )
        later = service.prepare_from_attachment(owner, later_request, source)
        assert later.regimen.id != result.regimen.id
        assert later.regimen.frequency_rule["local_times"] == ["09:00", "21:00"]
        assert attachments._repository.get(owner, task_id, attachment_id).source_ref == original.source_ref
        assert writer.for_attachment(owner, attachment_id).source_id == result.regimen.source_id
        assert writer.lookup(owner, later_request.action_key).attachment_ids == (attachment_id,)
        assert h.container.enrollment.get_source(owner, result.regimen.source_id).reviewed_at is None


def test_confirmed_end_keeps_instructions_and_report_history(workflow):
    from .test_workflow_medication_management import active_plan

    h, port = workflow, harness(workflow)
    old = active_plan(h)
    view = h.start("medication.plan.end", {"regimen_id": old["regimen_id"], "expected_version": 1})
    view = h.event(view["task_id"], "prepare_confirmation")
    owner = h.owner_ids["A"]
    before = h.snapshot()
    command = api("EndMedicationPlan")(
        confirmed=True,
        binding=WorkflowWriteBinding(
            task_id=UUID(view["task_id"]),
            task_revision=view["revision"],
            capability_id="medication.plan.end",
            action_key=uuid4(),
            prepared_ref=BusinessRef.model_validate(view["result_ref"]),
            expected_domain_revision=port.revision(owner),
        ),
    )
    result = port.apply(owner, command)
    assert result.result.state.value == "ended" and result.receipt.outcome == "applied"
    after = h.snapshot()
    assert after["sources"] == before["sources"] and after["dose_events"] == before["dose_events"]
    assert result.result.frequency_rule == before["regimens"][0]["frequency_rule"]
    assert port.apply(owner, command).receipt == result.receipt


def test_change_plan_prepares_a_separate_version_and_keeps_active_predecessor(workflow):
    from app.contracts.enrollment_operations import PlanChangeOperationInput

    from .test_workflow_medication_management import active_plan

    h, port = workflow, harness(workflow)
    old = active_plan(h)
    view = h.start(
        "medication.plan.change",
        {
            "regimen_id": old["regimen_id"],
            "expected_version": 1,
            "expected_state": "active",
            "details": {"dose_amount": 2},
        },
    )
    owner, action = h.owner_ids["A"], uuid4()
    native = PlanChangeOperationInput(
        action_key=action,
        workflow_task_id=UUID(view["task_id"]),
        workflow_revision=view["revision"],
        predecessor_id=UUID(old["regimen_id"]),
        expected_version=1,
        expected_state="active",
        fields={"dose_amount": 2},
    )
    command = api("ChangeMedicationPlan")(
        values=native,
        binding=WorkflowWriteBinding(
            task_id=native.workflow_task_id,
            task_revision=native.workflow_revision,
            capability_id="medication.plan.change",
            action_key=action,
            prepared_ref=BusinessRef(kind="regimen", id=native.predecessor_id, version=1),
            expected_domain_revision=port.revision(owner),
        ),
    )
    result = port.apply(owner, command)
    assert result.result.state.value == "draft" and result.result.version_no == 2
    assert result.result.supersedes_id == native.predecessor_id
    assert h.container.enrollment.get_regimen(owner, native.predecessor_id).state.value == "active"
    assert result.receipt.outcome == "prepared" and result.receipt.business_ref.id == result.result.id


def test_draft_delete_keeps_unknown_cleanup_honest_and_performs_no_storage_io(workflow, monkeypatch):
    from .test_workflow_draft_deletion import source_task

    h = workflow
    saved = source_task(h, monkeypatch)
    view = h.start(
        "medication.draft.delete", {"kind": "source", "target_id": saved["id"], "expected_version": saved["version"]}
    )
    view = h.event(view["task_id"], "prepare_confirmation")
    native = h.container.draft_deletion._repository
    calls = []

    class NoStorageIo:
        def delete(self, path):
            calls.append(path)
            raise AssertionError("Metadata transaction must not perform Storage I/O")

    monkeypatch.setattr(native, "_storage", NoStorageIo())
    port, owner = harness(h), h.owner_ids["A"]
    command = api("DeleteMedicationDraft")(
        confirmed=True,
        draft_kind="source",
        binding=WorkflowWriteBinding(
            task_id=UUID(view["task_id"]),
            task_revision=view["revision"],
            capability_id="medication.draft.delete",
            action_key=uuid4(),
            prepared_ref=BusinessRef.model_validate(view["result_ref"]),
            expected_domain_revision=port.revision(owner),
        ),
    )
    result = port.apply(owner, command)
    assert result.result.deleted and result.result.cleanup_pending and calls == []
    assert port.apply(owner, command).result.cleanup_pending and calls == []
    assert port.lookup(owner, command.binding.action_key).outcome == "applied"


def test_new_source_review_uses_a_real_preparation_marker_until_patient_saves():
    from app.application.workflow_verification import WorkflowVerificationService
    from app.infrastructure.verified_original_repos import MemoryStorageVerifier, MemoryVerifiedOriginals

    from .test_workflow_originals import original_png
    from .test_workflow_photo_enrollment import label
    from .workflow_support import WorkflowHarness

    with WorkflowHarness(source_results=[label(), label()]) as h:
        attachments = h.container.assistant_attachments
        state = attachments._repository._state
        proof_port = MemoryVerifiedOriginals(
            state=state,
            clock=h.clock,
            originals=attachments._repository,
            controls=attachments._controls,
            cleanup=h.container.assistant_cleanup._repository,
        )
        attachments._verification = WorkflowVerificationService(
            repository=proof_port,
            storage=attachments._storage,
            verifier=MemoryStorageVerifier(state=state, clock=h.clock),
            clock=h.clock,
        )
        view = h.start("medication.source.add", {})
        uploaded = h.upload(view["task_id"], original_png())
        view = uploaded["workflow"]
        port, owner = harness(h), h.owner_ids["A"]
        marker = BusinessRef(kind="media_review", id=UUID(view["task_id"]), version=view["revision"] + 1)
        prepare_source = api("PrepareSourceReview")(
            binding=WorkflowWriteBinding(
                task_id=UUID(view["task_id"]),
                task_revision=view["revision"],
                capability_id="medication.source.add",
                action_key=uuid4(),
                prepared_ref=marker,
                expected_domain_revision=port.revision(owner),
            )
        )
        prepared = port.apply(owner, prepare_source)
        assert prepared.result is None and prepared.receipt.business_ref == marker
        assert h.container.evidence_enrollment.list(owner) == [] and not h.snapshot()["medications"]
        review = h.view(view["task_id"])
        assert review["result_ref"]["kind"] == "media_review" and review["visible_fields"]["source_saved"] is False
        h.event(view["task_id"], "pause")
        assert h.view(view["task_id"])["state"] == "suspended"
        h.event(view["task_id"], "resume")
        resumed = h.view(view["task_id"])
        assert resumed["state"] == "ready_for_review" and resumed["result_ref"] is None
        assert port.lookup(owner, prepare_source.binding.action_key) == prepared.receipt
        marker = marker.model_copy(update={"version": resumed["revision"] + 1})
        prepare_source = prepare_source.model_copy(
            update={
                "binding": prepare_source.binding.model_copy(
                    update={"task_revision": resumed["revision"], "action_key": uuid4(), "prepared_ref": marker}
                )
            }
        )
        port.apply(owner, prepare_source)
        review = h.view(view["task_id"])
        h.upload(view["task_id"], original_png())
        additional = h.view(view["task_id"])
        assert additional["state"] == "ready_for_review" and additional["result_ref"] is None
        marker = marker.model_copy(update={"version": additional["revision"] + 1})
        prepare_source = prepare_source.model_copy(
            update={
                "binding": prepare_source.binding.model_copy(
                    update={"task_revision": additional["revision"], "action_key": uuid4(), "prepared_ref": marker}
                )
            }
        )
        port.apply(owner, prepare_source)
        review = h.view(view["task_id"])
        binding = prepare_source.binding.model_copy(
            update={
                "task_revision": review["revision"],
                "action_key": uuid4(),
                "expected_domain_revision": port.revision(owner),
            }
        )
        save = api("SaveSourceRegistration")(
            binding=binding, attachment_id=UUID(uploaded["attachment"]["id"]), confirmed=True
        )
        result = port.apply(owner, save)
        assert result.result.id != marker.id and result.receipt.business_ref.kind == "enrollment_task"
        assert h.view(view["task_id"])["visible_fields"]["source_saved"] is True
        assert h.read_original(uploaded["attachment"]["id"]) == original_png()
        from app.contracts.dto import RegimenDraftInput

        current = h.view(view["task_id"])
        review_binding = binding.model_copy(
            update={
                "task_revision": current["revision"],
                "action_key": uuid4(),
                "prepared_ref": result.receipt.business_ref,
                "expected_domain_revision": port.revision(owner),
            }
        )
        review_command = api("ReviewSourceRegistration")(
            binding=review_binding,
            confirmed=True,
            draft=RegimenDraftInput(
                medication_name=result.result.product.name,
                dose_amount=1,
                dose_unit="tablet",
                frequency_rule={"kind": "daily", "local_times": ["08:00", "20:00"]},
            ),
            distinct_product_confirmed=False,
        )
        reviewed = port.apply(owner, review_command)
        assert reviewed.result.draft_regimen_id is not None and reviewed.receipt.business_ref.kind == "regimen"
        regimen = h.container.enrollment.get_regimen(owner, reviewed.result.draft_regimen_id)
        assert regimen.state.value == "draft" and regimen.confirmation_challenge_id is None
        # Lost responses must read the committed result before stale-version
        # preparation or any further native image copy is attempted.
        import httpx
        from app.infrastructure.supabase_data import SupabaseDataClient
        from app.infrastructure.workflow_medication_writes import SupabaseMedicationWorkflowWrites
        from app.infrastructure.workflow_repos import SupabaseWorkflowMutations

        class NoNewPreparation:
            def prepare(self, actual_owner, actual_command):
                raise AssertionError("An applied source command must not prepare or copy again")

        before = h.snapshot()
        for original_command in (save, review_command):
            committed = port.apply(owner, original_command)
            calls = []

            def read_only(request, calls=calls, committed=committed):
                calls.append((request.method, request.url.path))
                if request.method == "GET" and request.url.path == "/rest/v1/assistant_business_receipts":
                    return httpx.Response(200, json=[committed.receipt.model_dump(mode="json")])
                assert request.method == "POST" and request.url.path == "/rest/v1/rpc/assistant_medication_read"
                return httpx.Response(200, json={"result": committed.model_dump(mode="json"), "replayed": True})

            data = SupabaseDataClient(
                base_url="https://example.invalid",
                publishable_key="sb_publishable_DEMO",
                access_token="DEMO-token",
                patient_id=owner,
                client=httpx.Client(transport=httpx.MockTransport(read_only)),
            )
            remote = SupabaseMedicationWorkflowWrites(
                data=data,
                reads=InMemoryEnrollmentWritePort(h.container.store),
                receipts=SupabaseWorkflowMutations(data),
                preparations=NoNewPreparation(),
            )
            assert remote.apply(owner, original_command) == committed
            assert len(calls) == 2 and h.snapshot() == before


def test_source_review_proposal_runs_native_policy_without_publishing_anything(workflow, monkeypatch):
    from app.contracts.dto import RegimenDraftInput
    from app.contracts.enrollment_operations import PreparedEnrollment

    from .test_workflow_sources import inputs, provider

    h = workflow
    provider(h, monkeypatch)
    task = h.container.evidence_enrollment.attach(**inputs(h))
    before = h.snapshot()
    proposed = h.container.evidence_enrollment.prepare_review_proposal(
        patient_id=h.owner_ids["A"],
        task_id=task.id,
        draft=RegimenDraftInput(
            medication_name=task.product.name,
            dose_amount=1,
            dose_unit="tablet",
            frequency_rule={"kind": "daily", "local_times": ["08:00"]},
        ),
        patient_reviewed=True,
        distinct_product_confirmed=False,
    )
    assert isinstance(proposed, PreparedEnrollment) and proposed.result.regimen.state.value == "draft"
    assert proposed.source.reviewed_at is None and proposed.result.medication.id == task.medication_id
    assert h.snapshot() == before


def test_remote_medication_write_uses_a_fixed_rpc_and_validates_its_owned_receipt(workflow):
    import json

    import httpx
    from app.infrastructure.supabase_data import SupabaseDataClient
    from app.infrastructure.workflow_medication_writes import SupabaseMedicationWorkflowWrites
    from app.infrastructure.workflow_repos import SupabaseWorkflowMutations

    h, memory = workflow, harness(workflow)
    owner, command = prepare(h, memory)
    expected = memory.apply(owner, command)
    calls = []

    def respond(request):
        calls.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"result": expected.model_dump(mode="json")})

    data = SupabaseDataClient(
        base_url="https://example.invalid",
        publishable_key="sb_publishable_DEMO",
        access_token="DEMO-token",
        patient_id=owner,
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    remote = SupabaseMedicationWorkflowWrites(
        data=data, reads=InMemoryEnrollmentWritePort(h.container.store), receipts=SupabaseWorkflowMutations(data)
    )
    assert remote.apply(owner, command) == expected
    assert calls[0][0] == "/rest/v1/rpc/assistant_medication_write"
    assert calls[0][1]["p_request"]["command"]["kind"] == "prepare"
    assert "owner" not in calls[0][1]["p_request"]
    from app.domain.errors import ProviderUnavailableError

    for changed in ({"version_no": 2}, {"attachment_ids": (uuid4(),)}, {"source_candidate_index": 1}):
        invalid = expected.model_copy(update={"result": expected.result.model_copy(update=changed)})
        invalid_data = SupabaseDataClient(
            base_url="https://example.invalid",
            publishable_key="sb_publishable_DEMO",
            access_token="DEMO-token",
            patient_id=owner,
            client=httpx.Client(
                transport=httpx.MockTransport(
                    lambda request, invalid=invalid: httpx.Response(
                        200, json={"result": invalid.model_dump(mode="json")}
                    )
                )
            ),
        )
        invalid_remote = SupabaseMedicationWorkflowWrites(
            data=invalid_data,
            reads=InMemoryEnrollmentWritePort(h.container.store),
            receipts=SupabaseWorkflowMutations(invalid_data),
        )
        with pytest.raises(ProviderUnavailableError):
            invalid_remote.apply(owner, command)


def test_remote_medication_write_rejects_foreign_identity_before_transport(workflow):
    import httpx
    from app.domain.errors import AuthenticationRequiredError
    from app.infrastructure.supabase_data import SupabaseDataClient
    from app.infrastructure.workflow_medication_writes import SupabaseMedicationWorkflowWrites
    from app.infrastructure.workflow_repos import SupabaseWorkflowMutations

    h, memory = workflow, harness(workflow)
    owner, command = prepare(h, memory)
    calls = []

    def unexpected(request):
        calls.append(request)
        raise AssertionError("A foreign owner must be rejected before I/O")

    data = SupabaseDataClient(
        base_url="https://example.invalid",
        publishable_key="sb_publishable_DEMO",
        access_token="DEMO-token",
        patient_id=owner,
        client=httpx.Client(transport=httpx.MockTransport(unexpected)),
    )
    remote = SupabaseMedicationWorkflowWrites(
        data=data, reads=InMemoryEnrollmentWritePort(h.container.store), receipts=SupabaseWorkflowMutations(data)
    )
    with pytest.raises(AuthenticationRequiredError):
        remote.apply(uuid4(), command)
    assert calls == []


def test_remote_medication_error_is_a_safe_typed_domain_rejection(workflow):
    import httpx
    from app.domain.errors import NotFoundError
    from app.infrastructure.supabase_data import SupabaseDataClient
    from app.infrastructure.workflow_medication_writes import SupabaseMedicationWorkflowWrites
    from app.infrastructure.workflow_repos import SupabaseWorkflowMutations

    h, memory = workflow, harness(workflow)
    owner, command = prepare(h, memory)
    data = SupabaseDataClient(
        base_url="https://example.invalid",
        publishable_key="sb_publishable_DEMO",
        access_token="DEMO-token",
        patient_id=owner,
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"error": "not_found"}))
        ),
    )
    remote = SupabaseMedicationWorkflowWrites(
        data=data, reads=InMemoryEnrollmentWritePort(h.container.store), receipts=SupabaseWorkflowMutations(data)
    )
    with pytest.raises(NotFoundError):
        remote.apply(owner, command)


def test_remote_change_rejects_an_unrelated_owned_native_result(workflow):
    import httpx
    from app.contracts.enrollment_operations import PlanChangeOperationInput
    from app.contracts.workflow_medication_writes import ChangeMedicationPlan, MedicationWriteRequest
    from app.contracts.workflow_persistence import BusinessWriteReceipt, NativeWriteResult
    from app.domain.errors import ProviderUnavailableError
    from app.infrastructure.supabase_data import SupabaseDataClient
    from app.infrastructure.workflow_medication_writes import SupabaseMedicationWorkflowWrites
    from app.infrastructure.workflow_repos import SupabaseWorkflowMutations

    h = workflow
    owner = h.owner_ids["A"]
    proposal = h.container.enrollment.prepare_draft(patient_id=owner, draft=values().fields.draft)
    task_id, action_key = uuid4(), uuid4()
    operation = PlanChangeOperationInput(
        action_key=action_key,
        workflow_task_id=task_id,
        workflow_revision=1,
        predecessor_id=uuid4(),
        expected_version=1,
        expected_state="active",
        fields={"dose_amount": 2},
    )
    binding = WorkflowWriteBinding(
        task_id=task_id,
        task_revision=1,
        capability_id="medication.plan.change",
        action_key=action_key,
        prepared_ref=BusinessRef(kind="regimen", id=operation.predecessor_id, version=1),
        expected_domain_revision=0,
    )
    command = ChangeMedicationPlan(binding=binding, values=operation)

    class Prepared:
        def prepare(self, actual_owner, actual_command):
            assert actual_owner == owner and actual_command == command
            return MedicationWriteRequest(command=command, prepared=proposal)

    unrelated = proposal.result.regimen.model_copy(update={"id": uuid4()})
    receipt = BusinessWriteReceipt(
        owner=owner,
        task_id=task_id,
        action_key=action_key,
        capability_id=binding.capability_id,
        binding_revision=2,
        business_ref=BusinessRef(kind="regimen", id=unrelated.id, version=unrelated.version_no),
        domain_revision=1,
        outcome="prepared",
        recorded_at=h.clock.now(),
    )
    response = NativeWriteResult(receipt=receipt, result=unrelated).model_dump(mode="json")
    data = SupabaseDataClient(
        base_url="https://example.invalid",
        publishable_key="sb_publishable_DEMO",
        access_token="DEMO-token",
        patient_id=owner,
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=[] if request.method == "GET" else {"result": response})
            )
        ),
    )
    remote = SupabaseMedicationWorkflowWrites(
        data=data,
        reads=InMemoryEnrollmentWritePort(h.container.store),
        receipts=SupabaseWorkflowMutations(data),
        preparations=Prepared(),
    )
    with pytest.raises(ProviderUnavailableError):
        remote.apply(owner, command)


def test_remote_preparation_reuses_native_source_policy_without_a_write(workflow, monkeypatch):
    from app.application.enrollment_operations import EnrollmentOperationService
    from app.application.workflow_medication_preparation import MedicationWritePreparationService
    from app.contracts.dto import RegimenDraftInput
    from app.contracts.workflow_medication_writes import ReviewSourceRegistration

    from .test_workflow_sources import inputs, provider

    h, owner = workflow, workflow.owner_ids["A"]
    provider(h, monkeypatch)
    native = h.container.evidence_enrollment.attach(**inputs(h))
    binding = WorkflowWriteBinding(
        task_id=uuid4(),
        task_revision=2,
        capability_id="medication.source.review",
        action_key=uuid4(),
        prepared_ref=BusinessRef(kind="enrollment_task", id=native.id, version=native.version),
        expected_domain_revision=InMemoryEnrollmentWritePort(h.container.store).revision(owner),
    )
    command = ReviewSourceRegistration(
        binding=binding,
        confirmed=True,
        distinct_product_confirmed=False,
        draft=RegimenDraftInput(
            medication_name=native.product.name,
            dose_amount=1,
            dose_unit="tablet",
            frequency_rule={"kind": "daily", "local_times": ["08:00"]},
        ),
    )
    service = MedicationWritePreparationService(
        enrollment=h.container.enrollment,
        operations=EnrollmentOperationService(h.container.enrollment, InMemoryEnrollmentWritePort(h.container.store)),
        evidence=h.container.evidence_enrollment,
    )
    before = h.snapshot()
    request = service.prepare(owner, command)
    assert (
        request.prepared.workflow_task_id == binding.task_id
        and request.prepared.workflow_revision == binding.task_revision
    )
    assert request.prepared.result.regimen.state.value == "draft" and h.snapshot() == before


def test_remote_plan_preparation_does_not_replace_the_active_version(workflow):
    import hashlib
    import json

    from app.application.enrollment_operations import EnrollmentOperationService
    from app.application.workflow_medication_preparation import MedicationWritePreparationService
    from app.contracts.workflow_medication_writes import ChangeMedicationPlan

    from .test_workflow_medication_management import active_plan
    from .test_workflow_plan_changes import update_input

    h, owner = workflow, workflow.owner_ids["A"]
    old = active_plan(h)
    values = update_input(h, old, dose_amount=2)
    binding = WorkflowWriteBinding(
        task_id=values.workflow_task_id,
        task_revision=values.workflow_revision,
        capability_id="medication.plan.change",
        action_key=values.action_key,
        prepared_ref=BusinessRef(kind="regimen", id=values.predecessor_id, version=values.expected_version),
        expected_domain_revision=InMemoryEnrollmentWritePort(h.container.store).revision(owner),
    )
    service = MedicationWritePreparationService(
        enrollment=h.container.enrollment,
        operations=EnrollmentOperationService(h.container.enrollment, InMemoryEnrollmentWritePort(h.container.store)),
        evidence=h.container.evidence_enrollment,
    )
    before = h.snapshot()
    request = service.prepare(owner, ChangeMedicationPlan(binding=binding, values=values))
    assert (
        request.prepared_digest
        == hashlib.sha256(json.dumps(values.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
    )
    assert request.prepared.result.regimen.supersedes_id == values.predecessor_id
    assert request.prepared.result.regimen.version_no == 2 and request.prepared.result.regimen.dose_amount == 2
    assert h.snapshot() == before


def test_remote_response_loss_reads_original_ids_instead_of_a_fresh_proposal(workflow):
    import httpx
    from app.application.enrollment_operations import EnrollmentOperationService
    from app.application.workflow_medication_preparation import MedicationWritePreparationService
    from app.contracts.enrollment_operations import PlanChangeOperationInput
    from app.contracts.workflow_medication_writes import ChangeMedicationPlan
    from app.infrastructure.supabase_data import SupabaseDataClient
    from app.infrastructure.workflow_medication_writes import SupabaseMedicationWorkflowWrites
    from app.infrastructure.workflow_repos import SupabaseWorkflowMutations

    from .test_workflow_medication_management import active_plan

    h, owner = workflow, workflow.owner_ids["A"]
    old = active_plan(h)
    view = h.start(
        "medication.plan.change",
        {
            "regimen_id": old["regimen_id"],
            "expected_version": 1,
            "expected_state": "active",
            "details": {"dose_amount": 2},
        },
    )
    memory = harness(h)
    operation = PlanChangeOperationInput(
        action_key=uuid4(),
        workflow_task_id=UUID(view["task_id"]),
        workflow_revision=view["revision"],
        predecessor_id=UUID(old["regimen_id"]),
        expected_version=1,
        expected_state="active",
        fields={"dose_amount": 2},
    )
    command = ChangeMedicationPlan(
        values=operation,
        binding=WorkflowWriteBinding(
            task_id=operation.workflow_task_id,
            task_revision=operation.workflow_revision,
            capability_id="medication.plan.change",
            action_key=operation.action_key,
            prepared_ref=BusinessRef(kind="regimen", id=operation.predecessor_id, version=1),
            expected_domain_revision=memory.revision(owner),
        ),
    )
    committed = memory.apply(owner, command)
    before = h.snapshot()
    data = SupabaseDataClient(
        base_url="https://example.invalid",
        publishable_key="sb_publishable_DEMO",
        access_token="DEMO-token",
        patient_id=owner,
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json=[committed.receipt.model_dump(mode="json")]
                    if request.method == "GET"
                    else {"result": committed.model_dump(mode="json"), "replayed": True},
                )
            )
        ),
    )
    preparations = MedicationWritePreparationService(
        enrollment=h.container.enrollment,
        operations=EnrollmentOperationService(h.container.enrollment, InMemoryEnrollmentWritePort(h.container.store)),
        evidence=h.container.evidence_enrollment,
    )
    remote = SupabaseMedicationWorkflowWrites(
        data=data,
        reads=InMemoryEnrollmentWritePort(h.container.store),
        receipts=SupabaseWorkflowMutations(data),
        preparations=preparations,
    )
    replayed = remote.apply(owner, command)
    assert replayed.receipt == committed.receipt and replayed.result.id == committed.result.id
    assert h.snapshot() == before


def test_original_identity_review_uses_the_existing_patient_only_native_step(workflow):
    h, owner = workflow, workflow.owner_ids["A"]
    old = h._request("POST", "/api/medications/drafts", json={"medication_name": values().fields.medication_name})
    fields = values().fields.model_dump(mode="json", exclude_none=True)
    view = h.start("medication.enroll", fields)
    view = h.event(view["task_id"], "select_candidate", {"existing_medication_id": old["medication_id"]})
    port = harness(h)
    proposal = h.container.enrollment.prepare_draft(
        patient_id=owner, draft=values().fields.draft, existing_medication_id=UUID(old["medication_id"])
    )
    proposal = proposal.model_copy(
        update={"workflow_task_id": UUID(view["task_id"]), "workflow_revision": view["revision"]}
    )
    command = api("PrepareMedication")(
        prepared=proposal,
        binding_digest="a" * 64,
        binding=WorkflowWriteBinding(
            task_id=UUID(view["task_id"]),
            task_revision=view["revision"],
            capability_id="medication.enroll",
            action_key=uuid4(),
            prepared_ref=BusinessRef(
                kind="regimen", id=proposal.result.regimen.id, version=proposal.result.regimen.version_no
            ),
            expected_domain_revision=port.revision(owner),
        ),
    )
    port.apply(owner, command)
    port.apply(
        owner,
        native_action(h, port, owner, command, "ReviewMedicationSource", source_id=proposal.source.id, confirmed=True),
    )
    assert h.container.enrollment.original_identity_review(owner, proposal.result.regimen.id).source_id == UUID(
        old["source_id"]
    )
    result = port.apply(owner, native_action(h, port, owner, command, "ReviewMedicationIdentity", confirmed=True))
    assert result.result is None and result.receipt.outcome == "prepared"
    assert h.container.enrollment.original_identity_review(owner, proposal.result.regimen.id) is None
    assert h.container.enrollment.get_source(owner, UUID(old["source_id"])).reviewed_at is None


def test_medication_sql_review_pair_has_native_transaction_and_confirmation_boundaries():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "supabase/review/assistant_workflows"
    up, down = root / "medication.up.sql", root / "medication.down.sql"
    assert up.is_file() and down.is_file(), "Medication SQL review pair is missing"
    sql = up.read_text(encoding="utf-8")
    for required in (
        "assistant_medication_write",
        "assistant_medication_read",
        "assistant_medication_commands",
        "assistant_business_receipts",
        "assistant_medication_owner_fence",
        "FOR EACH STATEMENT",
        "assistant_run_assert_current",
        "activate_medication_regimen_version",
        "confirmed",
        "command_digest",
        "replayed",
        "assistant_medication_assert_original",
        "assistant_medication_native_source",
        "assistant_medication_registration",
        "assistant_workflow_command_legacy_035",
    ):
        assert required in sql
    assert "TO assistant_evidence_login" not in sql and "DELETE FROM storage.objects" not in sql
    assert sql.rstrip().endswith("COMMIT;")
    recovery = down.read_text(encoding="utf-8")
    assert "RAISE EXCEPTION" in recovery and recovery.rstrip().endswith("COMMIT;")


def test_run_expiry_after_native_preparation_rolls_back_before_publication(workflow,monkeypatch):
    from app.contracts.workflow_persistence import RunWriteBinding
    from app.infrastructure.durable_agent_runs import MemoryDurableRunControl

    from .test_durable_agent_runs import claimed

    h,port=workflow,harness(workflow)
    owner,command=prepare(h,port)
    state=h.container.assistant_workflows._repository._state
    run=claimed(MemoryDurableRunControl(clock=h.clock,state=state),owner)
    command=command.model_copy(update={'binding':command.binding.model_copy(update={
        'run_binding':RunWriteBinding(run_id=run.run_id,epoch=run.epoch)})})
    create=port._enrollments.create_once
    def slow_create(*args,**kwargs):
        result=create(*args,**kwargs)
        h.clock.advance(seconds=46)
        return result
    monkeypatch.setattr(port._enrollments,'create_once',slow_create)
    before=h.snapshot()
    with pytest.raises(StaleVersionError):
        port.apply(owner,command)
    assert h.snapshot()==before and port.lookup(owner,command.binding.action_key) is None
