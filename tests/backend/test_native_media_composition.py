"""Recording construction only; no claim of SQL installation or Storage acceptance."""

import hashlib
from dataclasses import replace

import pytest
from app.application.native_media_verification import VerifiedNativeMediaStore
from app.domain.errors import ProviderUnavailableError

from .test_persistent_workflow_composition import persistent_root


def enable(monkeypatch, **changes):
    from app.transport import container as module

    build = module.build_supabase_container
    monkeypatch.setattr(
        module, "build_supabase_container", lambda *, settings: build(settings=replace(settings, **changes))
    )


def test_candidate_native_apis_use_verified_stores_without_hidden_workflows(monkeypatch):
    _, scoped, calls, connections, _ = persistent_root(monkeypatch)
    normal = scoped("DEMO-A")
    candidate = normal.assistant_candidate.container
    assert isinstance(candidate.gallery._storage, VerifiedNativeMediaStore)
    assert isinstance(candidate.evidence_enrollment._storage, VerifiedNativeMediaStore)
    assert not isinstance(normal.gallery._storage, VerifiedNativeMediaStore)
    assert len(calls) == 1 and not connections


def test_native_bridge_can_be_explicit_without_enabling_assistant_workflows(monkeypatch):
    enable(
        monkeypatch,
        assistant_native_media_enabled=True,
        assistant_workflows_enabled=False,
        enable_medication_library_files=True,
    )
    _, scoped, calls, connections, _ = persistent_root(monkeypatch)
    normal = scoped("DEMO-A")
    assert normal.assistant_workflows is None and normal.assistant_candidate is None
    for service in (normal.gallery, normal.evidence_enrollment, normal.library_files):
        assert isinstance(service._storage, VerifiedNativeMediaStore)
    assert isinstance(normal.draft_deletion._repository._storage, VerifiedNativeMediaStore)
    assert len(calls) == 1 and not connections


def test_missing_verifier_refuses_native_file_io_before_intent_or_storage(monkeypatch):
    enable(monkeypatch, assistant_native_media_enabled=True)
    _, scoped, calls, connections, owners = persistent_root(monkeypatch)
    normal = scoped("DEMO-A")
    data = b"DEMO"
    digest = hashlib.sha256(data).hexdigest()
    path = f"{owners['DEMO-A']}/{owners['DEMO-A']}/{digest}.png"
    with pytest.raises(ProviderUnavailableError):
        normal.gallery._storage.put(path, data)
    with pytest.raises(ProviderUnavailableError):
        normal.gallery._storage.delete(path)
    assert len(calls) == 1 and not connections
