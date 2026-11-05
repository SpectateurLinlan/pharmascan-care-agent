"""Opt-in local real Auth/Data API/Storage, with recorded public knowledge only.

Never a deployment entry point. Database administrator/API secret/provider keys
are absent from Settings. The application's actual release gate still applies.
"""

import json
import os
from pathlib import Path

import httpx
from app.config import Settings
from app.transport.app_factory import create_app as patient_app
from app.transport.container import build_supabase_container

from tests.backend.local_supabase_live_support import verify_local_live_target
from tests.backend.persistent_workflow_live_support import (
    ROOT,
    PersistentWorkflowTestProfile,
    validate_persistent_test_profile,
)


def local_settings(profile: PersistentWorkflowTestProfile) -> Settings:
    """No dotenv, ambient application/provider credentials or admin SQL fallback."""
    return Settings(
        database_url=None,
        supabase_url=profile.storage_values["ASSISTANT_TEST_SUPABASE_URL"],
        supabase_publishable_key=profile.storage_values["ASSISTANT_TEST_PUBLISHABLE_KEY"],
        supabase_secret_key=None,
        app_env="test",
        app_origin="http://127.0.0.1:5195",
        vision_api_base_url=None,
        enable_demo_seed=False,
        persistence="supabase",
        auth_mode="supabase",
        source="LOCAL_DEMO_REAL_SERVICES_PUBLIC_KNOWLEDGE_REPLAY",
        model_provider="deterministic",
        assistant_knowledge_v2_enabled=True,
        assistant_workflows_enabled=True,
        assistant_native_media_enabled=True,
        assistant_progress_enabled=True,
        assistant_evidence_dsn=profile.evidence_dsn,
        enable_medication_library_files=True,
        enable_late_dose_reports=True,
        enable_multiple_care_reminders=True,
        enable_care_task_followups=True,
    )


def recorded_knowledge_client():
    fixture = json.loads((Path(__file__).parent / "fixtures/ibuprofen_labels_public.json").read_text(encoding="utf-8"))

    def replay(request):
        if request.url.host != "api.fda.gov" or request.url.path != "/drug/label.json":
            raise AssertionError("Local acceptance forbids unrecorded external requests")
        if "IBUPROFEN" not in request.url.params.get("search", ""):
            return httpx.Response(404)
        return httpx.Response(200, content=fixture["raw_response_utf8"], headers={"Content-Type": "application/json"})

    return httpx.Client(transport=httpx.MockTransport(replay), trust_env=False)


def create_app():
    if os.environ.get("MEDITHREAD_LOCAL_ACCEPTANCE") != "1":
        raise RuntimeError("Real-service runtime requires explicit local acceptance opt-in")
    values = json.loads((ROOT / "internal/acceptance/local-supabase/profile.json").read_bytes())
    profile = PersistentWorkflowTestProfile.from_values(values)
    if profile.target_mode != "local_supabase":
        raise RuntimeError("Explicit local target required")
    target = validate_persistent_test_profile(profile, purpose="sql_read", require_hashes=True)
    verify_local_live_target(profile, target)
    settings = local_settings(profile)
    root = build_supabase_container(settings=settings, knowledge_http_client_factory=recorded_knowledge_client)
    return patient_app(container=root, settings=settings)
