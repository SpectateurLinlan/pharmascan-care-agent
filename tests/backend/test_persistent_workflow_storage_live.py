"""Default-SKIP real Auth/Storage/proof definitions. No providers, provisioning or policy changes."""

import hashlib
from uuid import UUID, uuid4

import pytest

from tests.backend.persistent_workflow_live_support import admitted_live_profile, reserve_claimed_original

from .test_persistent_workflow_sql_live import live_persistence_sql, seed  # noqa: F401


@pytest.fixture
def live_persistence_storage(request):
    profile, target = admitted_live_profile("storage_write")
    _, sql_target, connection = request.getfixturevalue("live_persistence_sql")
    assert target == sql_target, "SQL/Storage profile snapshots differ"
    import httpx
    from app.config import Settings
    from app.infrastructure.supabase_data import SupabaseDataClient
    from app.transport.auth import AuthenticatedPrincipal
    from app.transport.container import build_supabase_container

    v = profile.storage_values
    # Offline JWT claims are not authentication. Verify both against isolated Auth before any Storage write.
    with httpx.Client(timeout=5) as auth:
        for owner, key in ((target.owner_a, "ASSISTANT_TEST_JWT_A"), (target.owner_b, "ASSISTANT_TEST_JWT_B")):
            try:
                reply = auth.get(
                    v["ASSISTANT_TEST_SUPABASE_URL"] + "/auth/v1/user",
                    headers={"apikey": v["ASSISTANT_TEST_PUBLISHABLE_KEY"], "Authorization": "Bearer " + v[key]},
                )
                valid = reply.status_code == 200 and UUID(reply.json()["id"]) == owner
            except Exception:
                valid = False
            if not valid:
                pytest.fail("Isolated Auth identity verification failed; no Storage write attempted", pytrace=False)
    task = seed(connection, target.owner_a)
    data = SupabaseDataClient(
        base_url=v["ASSISTANT_TEST_SUPABASE_URL"],
        publishable_key=v["ASSISTANT_TEST_PUBLISHABLE_KEY"],
        access_token=v["ASSISTANT_TEST_JWT_A"],
        patient_id=target.owner_a,
    )
    # A fresh unpredictable SQL-created task must be visible through this project's patient Data API.
    rows = data.rows("assistant_workflow_tasks", owner="eq." + str(target.owner_a), id="eq." + str(task.id), limit="1")
    if len(rows) != 1 or rows[0]["id"] != str(task.id):
        pytest.fail("SQL and Data API target pairing failed before Storage write", pytrace=False)
    settings = Settings(
        database_url=None,
        supabase_url=v["ASSISTANT_TEST_SUPABASE_URL"],
        supabase_publishable_key=v["ASSISTANT_TEST_PUBLISHABLE_KEY"],
        supabase_secret_key=None,
        app_env="test",
        app_origin=None,
        vision_api_base_url=None,
        enable_demo_seed=False,
        persistence="supabase",
        auth_mode="supabase",
        source="EXPLICIT_ISOLATED_PERSISTENCE_TEST",
        assistant_workflows_enabled=True,
        assistant_native_media_enabled=True,
        enable_medication_library_files=True,
        assistant_evidence_dsn=profile.evidence_dsn,
    )
    root = build_supabase_container(settings=settings)
    scopes = []
    try:
        for owner, key in ((target.owner_a, "ASSISTANT_TEST_JWT_A"), (target.owner_b, "ASSISTANT_TEST_JWT_B")):
            scopes.append(
                root.patient_factory(
                    AuthenticatedPrincipal(
                        patient_id=owner,
                        subject=str(owner),
                        email=None,
                        authenticated=True,
                        mode="supabase",
                        access_token=v[key],
                    )
                )
            )
        yield target, task, scopes[0].assistant_candidate, scopes[1].assistant_candidate, data
    finally:
        for scoped in scopes:
            scoped.close_request()


def save_raw(fixture):
    from .test_workflow_originals import original_png

    target, task, graph, other, data = fixture
    context = graph.container.assistant_attachments.context(target.owner_a, task.id, task.revision)
    original = graph.container.assistant_attachments.accept(
        context, uuid4(), original_png(), "image/png", False, source_kind="source_preview_photo"
    )
    return original, original_png()


def test_live_original_exact_bytes_and_cross_owner_denial(live_persistence_storage):
    from app.domain.errors import DomainError

    target, task, graph, other, _ = live_persistence_storage
    original, raw = save_raw(live_persistence_storage)
    content, mime = graph.container.assistant_attachments.read(target.owner_a, task.id, original.id)
    assert content == raw and mime == "image/png"
    assert hashlib.sha256(content).hexdigest() == original.original_checksum
    with pytest.raises(DomainError):
        other.container.assistant_attachments.read(target.owner_b, task.id, original.id)
    import httpx

    # Exercise actual Storage isolation as well as the earlier application metadata denial.
    profile, _ = admitted_live_profile("storage_read")
    v = profile.storage_values
    key = f"{target.owner_a}/workflow-originals/{task.id}/{original.id}"
    with httpx.Client(timeout=5) as http:
        response = http.get(
            v["ASSISTANT_TEST_SUPABASE_URL"] + "/storage/v1/object/medication-sources/" + key,
            headers={
                "apikey": v["ASSISTANT_TEST_PUBLISHABLE_KEY"],
                "Authorization": "Bearer " + v["ASSISTANT_TEST_JWT_B"],
            },
        )
        assert response.status_code in {403, 404}, "Owner-B Storage read was not denied"
    assert graph.container.assistant_attachments.read(target.owner_a, task.id, original.id)[0] == raw
    proof = graph.ports.originals.verification_for(target.owner_a, task.id, original.id)
    assert proof.result == "bytes_verified"


def test_live_revoke_publishes_deleted_only_after_independent_actual_absence(live_persistence_storage):
    from app.domain.errors import DomainError

    target, task, graph, _, _ = live_persistence_storage
    original, _ = save_raw(live_persistence_storage)
    revision = graph.ports.controls.get(target.owner_a, task.id).revision
    graph.container.assistant_cleanup.revoke(target.owner_a, task.id, revision, uuid4())
    status = graph.container.assistant_cleanup.status(target.owner_a, task.id)
    assert not status.pending and not status.protected
    with pytest.raises(DomainError):
        graph.container.assistant_attachments.read(target.owner_a, task.id, original.id)
    rows = graph.container.assistant_cleanup.retry_cleanup(target.owner_a, task.id)
    assert next(r for r in rows if r.id == original.id).state == "deleted"


@pytest.mark.parametrize("operation", ["overwrite", "delete"])
def test_live_cross_owner_storage_mutation_is_denied(request, operation):
    import os

    import httpx

    # These intentionally hostile probes could change ONLY a fresh DEMO_ONLY object if RLS is wrong.
    # A separate future approval is required before even requesting a connecting fixture.
    if os.environ.get("ASSISTANT_TEST_CROSS_OWNER_MUTATIONS_APPROVED") != "1":
        pytest.skip("Separate approval for synthetic cross-owner mutation probes required")
    profile, _ = admitted_live_profile("storage_write")
    admitted_live_profile("storage_read")
    fixture = request.getfixturevalue("live_persistence_storage")
    target, task, graph, _, _ = fixture
    original, raw = save_raw(fixture)
    key = f"{target.owner_a}/workflow-originals/{task.id}/{original.id}"
    values = profile.storage_values
    base = values["ASSISTANT_TEST_SUPABASE_URL"] + "/storage/v1/object/medication-sources"
    headers = {
        "apikey": values["ASSISTANT_TEST_PUBLISHABLE_KEY"],
        "Authorization": "Bearer " + values["ASSISTANT_TEST_JWT_B"],
    }
    with httpx.Client(timeout=5) as http:
        if operation == "overwrite":
            response = http.post(
                base + "/" + key,
                content=b"DEMO_ONLY forbidden owner B overwrite",
                headers={**headers, "Content-Type": "image/png", "x-upsert": "true"},
            )
            assert response.status_code in {403, 404}, "Owner-B overwrite was not denied"
        else:
            response = http.request("DELETE", base, json={"prefixes": [key]}, headers=headers)
            # Some Storage versions return 200 with no rows when RLS filters every key.
            assert response.status_code in {403, 404} or (response.status_code == 200 and response.json() == []), (
                "Owner-B deletion was not denied or filtered"
            )
    assert graph.container.assistant_attachments.read(target.owner_a, task.id, original.id)[0] == raw


def test_live_unknown_claimed_writer_retains_pending_after_revoke(live_persistence_storage):
    from app.contracts.workflow_attachments import OriginalAttachment
    from app.infrastructure.workflow_repos import SupabaseOriginalRepository

    from .test_workflow_originals import original_png

    target, task, graph, _, data = live_persistence_storage
    raw = original_png()
    attachment = uuid4()
    context = graph.container.assistant_attachments.context(target.owner_a, task.id, task.revision)
    attachment_row = OriginalAttachment(
        id=attachment,
        owner=target.owner_a,
        task_id=task.id,
        upload_id=uuid4(),
        binding_revision=task.revision,
        object_ref=f"{target.owner_a}/workflow-originals/{task.id}/{attachment}",
        original_checksum=hashlib.sha256(raw).hexdigest(),
        content_type="image/png",
        source_kind="source_preview_photo",
        byte_size=len(raw),
    )
    reserve_claimed_original(SupabaseOriginalRepository(data), graph.ports.originals, context, attachment_row)
    # Deliberately no terminal observation. Absence or elapsed time cannot settle this writer.
    graph.container.assistant_cleanup.revoke(target.owner_a, task.id, task.revision, uuid4())
    assert graph.container.assistant_cleanup.status(target.owner_a, task.id).pending
    rows = graph.container.assistant_cleanup.retry_cleanup(target.owner_a, task.id)
    assert next(r for r in rows if r.id == attachment).state != "deleted"


@pytest.fixture
def live_native_medication(request):
    import os

    admitted_live_profile("storage_write")
    try:
        medication = UUID(os.environ.get("ASSISTANT_TEST_NATIVE_MEDICATION_A", ""))
        if medication.int == 0:
            raise ValueError
    except ValueError:
        pytest.fail("Explicit pre-existing synthetic native medication fixture required", pytrace=False)
    fixture = request.getfixturevalue("live_persistence_storage")
    target, _, graph, _, _ = fixture
    row = graph.container.enrollment.get_medication(target.owner_a, medication)
    if row is None or row.demo_only is not True:
        pytest.fail("Owned synthetic native medication fixture not verified", pytrace=False)
    return fixture, medication


def test_live_unbound_native_photo_has_proof_and_no_hidden_task_or_extra_original(live_native_medication):
    from io import BytesIO

    from PIL import Image

    from .test_workflow_originals import original_png

    (target, _, graph, _, data), medication = live_native_medication
    before_tasks = len(graph.ports.tasks.list(target.owner_a))
    before_originals = len(data.all_rows("assistant_workflow_attachments", owner="eq." + str(target.owner_a)))
    with Image.open(BytesIO(original_png())) as image:
        image.putpixel((11, 11), tuple(uuid4().bytes[:3]))
        out = BytesIO()
        image.save(out, format="PNG")
        content = out.getvalue()
    result = graph.container.gallery.upload_with_status(
        patient_id=target.owner_a,
        medication_id=medication,
        image=content,
        image_kind="package",
        source_description="DEMO_ONLY native compatibility",
        reviewed=True,
        for_comparison=False,
        consent=True,
        demo_only=True,
    )
    assert result.photo.deleted_at is None
    assert len(graph.ports.tasks.list(target.owner_a)) == before_tasks
    assert len(data.all_rows("assistant_workflow_attachments", owner="eq." + str(target.owner_a))) == before_originals
    changed = graph.container.gallery.manage_image(
        target.owner_a, result.photo.id, action="delete", expected_version=result.photo.metadata_version, confirmed=True
    )
    assert changed.deleted_at is not None and changed.cleanup_pending is False


def test_live_unbound_native_pdf_publication_and_ack_use_task_independent_proof(live_native_medication):
    (target, _, graph, _, _), medication = live_native_medication
    before = len(graph.ports.tasks.list(target.owner_a))
    content = ("%PDF-1.7\n% DEMO_ONLY " + str(uuid4()) + "\n1 0 obj<</Type/Catalog>>endobj\n%%EOF").encode()
    row, duplicate = graph.container.library_files.upload(
        patient_id=target.owner_a,
        medication_id=medication,
        filename="DEMO-native.pdf",
        content_type="application/pdf",
        data=content,
        category="other",
        description="DEMO_ONLY acceptance",
    )
    assert not duplicate
    assert len(graph.ports.tasks.list(target.owner_a)) == before
    assert graph.container.library_files.content(target.owner_a, row.id)[1] == content
    graph.container.library_files.delete(target.owner_a, row.id, confirmed=True)
    assert graph.container.library_files.metadata(target.owner_a, row.id, include_deleted=True).cleanup_pending is False
