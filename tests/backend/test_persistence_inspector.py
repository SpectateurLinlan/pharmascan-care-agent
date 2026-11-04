"""Offline inspector tests do not authorize real ACL inspection."""

import importlib
import json
from contextlib import contextmanager

import pytest

from .test_persistent_workflow_profile import values


def inspector():
    from importlib.util import find_spec

    assert find_spec("scripts.qa.inspect_assistant_evidence_scope"), "Missing bounded offline/read-only inspector"
    return importlib.import_module("scripts.qa.inspect_assistant_evidence_scope")


def test_inspector_default_is_offline_and_never_reads_secrets(monkeypatch, capsys):
    import os

    import httpx
    import psycopg

    api = inspector()

    def forbidden(*a, **k):
        pytest.fail("Offline inventory attempted external/config access")

    monkeypatch.setattr(os, "getenv", forbidden)
    monkeypatch.setattr(psycopg, "connect", forbidden)
    monkeypatch.setattr(httpx.Client, "request", forbidden)
    assert api.main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "NOT_RUN" and result["network_calls"] == 0
    assert len(result["candidate_hashes"]) >= 25
    assert result["execution_ready"] is False


def test_inspector_requires_explicit_read_approval_before_profile_or_connection(monkeypatch, tmp_path, capsys):
    import psycopg

    api = inspector()
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps(values()), encoding="utf-8")
    monkeypatch.setattr(psycopg, "connect", lambda *a, **k: pytest.fail("Unauthorized inspection connected"))
    assert api.main(["--read-only", "--profile", str(profile)]) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "target_not_authorized"


def test_inspector_uses_only_fixed_read_queries_and_restricted_identity():
    api = inspector()
    from tests.backend.persistent_workflow_live_support import (
        PersistentWorkflowTestProfile,
        candidate_hashes,
        validate_persistent_test_profile,
    )

    profile = PersistentWorkflowTestProfile.from_values(
        values() | {"ASSISTANT_TEST_CANDIDATE_HASHES": json.dumps(candidate_hashes())}
    )
    target = validate_persistent_test_profile(profile, purpose="sql_read", require_hashes=True)
    seen = []

    class Cursor:
        def __init__(self, row):
            self.row = row

        def fetchone(self):
            return self.row

        def fetchall(self):
            return self.row

    class Connection:
        def execute(self, query, params=None):
            seen.append(query)
            assert query in api.READ_QUERIES.values()
            if query == api.READ_QUERIES["identity"]:
                return Cursor(
                    (
                        "assistant_evidence_login",
                        "assistant_evidence_login",
                        False,
                        False,
                        False,
                        False,
                        False,
                        False,
                        False,
                    )
                )
            if query == api.READ_QUERIES["database"]:
                return Cursor(("mt_assistant_test_demo",))
            if query == api.READ_QUERIES["commands"]:
                return Cursor([(name, True, True, False) for name in api.TECHNICAL_COMMANDS])
            if query == api.READ_QUERIES["patient_commands"]:
                return Cursor([(name, True, True, False) for name in api.PATIENT_COMMANDS])
            if query == api.READ_QUERIES["definitions"]:
                return Cursor([])
            return Cursor((0,))

    @contextmanager
    def connect(**kwargs):
        assert kwargs["user"] == "assistant_evidence_login"
        assert "default_transaction_read_only=on" in kwargs["options"]
        assert kwargs["passfile"] == ""
        yield Connection()

    result = api.inspect_read_only(profile, target, connect=connect)
    assert result["acl_observation"] == "PASS" and result["execution_ready"] is False
    assert seen and len(seen) == len(api.READ_QUERIES)


def test_inspector_classifies_every_actual_evidence_owned_technical_table():
    import re

    api = inspector()
    media = (api.ROOT / "supabase/review/assistant_workflows/media-verification.up.sql").read_text(encoding="utf-8")
    block = re.search(r"FOREACH relation_name IN ARRAY ARRAY\[(.*?)\] LOOP", media, re.S).group(1)
    media_tables = set(re.findall(r"'(assistant_[a-z_]+)'", block))
    metadata = (api.ROOT / "supabase/review/assistant_workflows/metadata.up.sql").read_text(encoding="utf-8")
    direct = set(re.findall(r"ALTER TABLE public\.(assistant_[a-z_]+) OWNER TO assistant_evidence_owner", metadata))
    native = (api.ROOT / "supabase/review/assistant_workflows/native-media.up.sql").read_text(encoding="utf-8")
    native_block = re.search(r"FOREACH relation_name IN ARRAY ARRAY\[(.*?)\] LOOP", native, re.S).group(1)
    native_tables = set(re.findall(r"'(assistant_[a-z_]+)'", native_block))
    assert media_tables | direct | native_tables == set(api._TECHNICAL_TABLES)
    assert "assistant_evidence.record_native_media_observation(jsonb)" in api.TECHNICAL_COMMANDS
    assert "public.assistant_native_media_command(jsonb)" in api.PATIENT_COMMANDS


def test_live_writer_reservation_claims_the_actual_reserved_writer():
    from types import SimpleNamespace
    from uuid import uuid4

    from tests.backend.persistent_workflow_live_support import reserve_claimed_original

    owner, task, writer, attachment = uuid4(), uuid4(), uuid4(), uuid4()
    context = SimpleNamespace(owner=owner, task_id=task)
    row = SimpleNamespace(id=attachment, upload_id=writer, operation_event_id=None, pending_writer_ids=(writer,))
    seen = []

    class Verified:
        def reserve_ticket(self, ctx, aid, wid):
            assert wid in row.pending_writer_ids
            seen.append((aid, wid))
            return "DEMO-ticket"

        def claim_ticket(self, o, t):
            assert o == owner and t == "DEMO-ticket"

    result = reserve_claimed_original(SimpleNamespace(reserve=lambda *a: row), Verified(), context, row)
    assert result == "DEMO-ticket" and seen == [(attachment, writer)]


def test_read_only_failure_never_reports_zero_network_after_an_inspection_attempt(monkeypatch, tmp_path, capsys):
    api = inspector()
    from tests.backend.persistent_workflow_live_support import candidate_hashes

    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(values() | {"ASSISTANT_TEST_CANDIDATE_HASHES": json.dumps(candidate_hashes())}), encoding="utf-8"
    )

    def fail(*a, **k):
        raise RuntimeError("DEMO-PRIVATE-diagnostic")

    monkeypatch.setattr(api, "inspect_read_only", fail)
    assert api.main(["--read-only", "--allow-isolated-read", "--profile", str(profile)]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["network_calls"] is None and result["inspection_attempted"] is True
    assert result["status"] == "READ_ONLY_UNAVAILABLE" and "DEMO-PRIVATE" not in json.dumps(result)
