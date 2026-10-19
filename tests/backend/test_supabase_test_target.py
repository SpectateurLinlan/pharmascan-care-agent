"""Offline target separation: no provider connection or real credentials."""

import pytest

from scripts.qa.check_supabase_test_target import validate_target


def values():
    return {
        "APP_ENV": "test",
        "AUTH_MODE": "supabase",
        "PERSISTENCE": "supabase",
        "TEST_PROJECT_REF": "demoisolated",
        "SUPABASE_URL": "https://demoisolated.supabase.co",
        "DATABASE_URL": "postgresql://postgres.demoisolated:DEMO@aws-0-test.pooler.supabase.com:5432/postgres",
        "SUPABASE_PUBLISHABLE_KEY": "DEMO-publishable",
    }


def test_explicit_test_project_is_accepted_without_connecting():
    assert len(validate_target(values(), {"SUPABASE_URL": "https://demoproduction.supabase.co"})) == 12


@pytest.mark.parametrize(
    "change",
    [
        {"SUPABASE_URL": "https://demoproduction.supabase.co"},
        {"DATABASE_URL": "postgresql://postgres.demoproduction:DEMO@aws-0-test.pooler.supabase.com:5432/postgres"},
        {"DATABASE_URL": "postgresql://postgres.demoisolated:DEMO@aws-0-test.pooler.supabase.com:6543/postgres"},
        {"APP_ENV": "production"},
        {"SUPABASE_SECRET_KEY": "DEMO-administrative"},
        {"SUPABASE_PUBLISHABLE_KEY": "sb_secret_DEMO"},
    ],
)
def test_production_ambiguous_and_admin_targets_are_refused(change):
    with pytest.raises(ValueError):
        validate_target(values() | change, {"SUPABASE_URL": "https://demoproduction.supabase.co"})
