"""Knowledge rollout is explicitly configurable; no real provider requests."""

from dataclasses import replace

from app.application.medication_names import MedicationNameResolver
from app.config import Settings
from app.contracts.medication_names import NameQuery
from app.transport.container import build_container_from_settings


def test_knowledge_v2_flag_defaults_off_and_parses_explicit_enable(monkeypatch, tmp_path):
    monkeypatch.delenv("ASSISTANT_KNOWLEDGE_V2_ENABLED", raising=False)
    settings = Settings.from_env(env_file=tmp_path / "absent.env")
    assert settings.assistant_knowledge_v2_enabled is False
    monkeypatch.setenv("ASSISTANT_KNOWLEDGE_V2_ENABLED", "true")
    assert Settings.from_env(env_file=tmp_path / "absent.env").assistant_knowledge_v2_enabled is True


def test_composition_root_only_enables_name_resolution_when_requested(tmp_path):
    settings = Settings(
        database_url=None, supabase_url=None, supabase_publishable_key=None, supabase_secret_key=None,
        app_env="local", app_origin=None, vision_api_base_url=None, enable_demo_seed=False,
        persistence="in_memory", auth_mode="demo", source="DEMO_ONLY",
    )
    candidate = MedicationNameResolver().resolve(NameQuery(text="ibuprofen", purpose="general_use"), ()).candidates[0]
    for enabled in (False, True):
        root = build_container_from_settings(replace(settings, assistant_knowledge_v2_enabled=enabled))
        try:
            assert root.medication_understanding.validate_name_candidate(candidate) == enabled
        finally:
            root.close_request()
