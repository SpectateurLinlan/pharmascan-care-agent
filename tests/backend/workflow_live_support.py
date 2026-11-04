"""Explicit acceptance targets; no environment-file reads or network operations."""

import re
from urllib.parse import unquote, urlparse

from scripts.qa.check_supabase_test_target import validate_target


def sql_target(dsn: str) -> str:
    parsed = urlparse(dsn)
    name = unquote(parsed.path).removeprefix("/")
    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or parsed.hostname != "127.0.0.1"
        or parsed.port != 55439
        or parsed.query
        or parsed.fragment
        or not re.fullmatch(r"mt_assistant_test_[a-zA-Z0-9_]+", name)
    ):
        raise ValueError("Explicit isolated loopback SQL target required; no connection attempted")
    return name


def storage_target(values: dict[str, str]) -> str:
    url = urlparse(values.get("ASSISTANT_TEST_SUPABASE_URL", ""))
    if url.scheme != "https" or url.path not in {"", "/"} or url.query or url.fragment or url.username or url.password:
        raise ValueError("Exact isolated HTTPS Storage endpoint required")
    test = {
        "APP_ENV": "test",
        "AUTH_MODE": "supabase",
        "PERSISTENCE": "supabase",
        "TEST_PROJECT_REF": values.get("ASSISTANT_TEST_PROJECT_REF", ""),
        "SUPABASE_URL": values.get("ASSISTANT_TEST_SUPABASE_URL", ""),
        "DATABASE_URL": values.get("ASSISTANT_TEST_SUPABASE_DATABASE_URL", ""),
        "SUPABASE_PUBLISHABLE_KEY": values.get("ASSISTANT_TEST_PUBLISHABLE_KEY", ""),
    }
    return validate_target(test, {"SUPABASE_URL": values.get("ASSISTANT_NORMAL_SUPABASE_URL", "")})
