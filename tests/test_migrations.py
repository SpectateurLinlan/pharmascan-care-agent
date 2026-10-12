"""只审查 SQL 文本结构；不连接 PostgreSQL，不证明真实迁移、RLS 或触发器通过。"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = ROOT / "supabase" / "migrations" / "202610130001_core.sql"
ROLLBACK_PATH = ROOT / "supabase" / "rollback" / "202610130001_core.sql"
OWNED_TABLES = (
    "patient_profiles",
    "source_documents",
    "source_fields",
    "patient_medications",
    "regimen_versions",
    "dose_rules",
    "dose_occurrences",
    "dose_events",
    "agent_sessions",
    "confirmation_challenges",
    "agent_tool_calls",
    "audit_events",
)
ALL_TABLES = ("medication_products", *OWNED_TABLES)


def _read(path):
    return path.read_text(encoding="utf-8")


def _without_comments(sql):
    # 保留字符串和 dollar-quoted 函数体；注释中的安全声明不能满足断言。
    tokens = re.compile(
        r"'(?:''|[^'])*'|\$\$[\s\S]*?\$\$|--[^\n]*|/\*[\s\S]*?\*/"
    )
    return tokens.sub(
        lambda match: " " if match.group().startswith(("--", "/*")) else match.group(),
        sql,
    )


def _normalize(sql):
    return re.sub(r"\s+", " ", _without_comments(sql)).strip().lower()


def _table(sql, name):
    match = re.search(
        rf"\bCREATE\s+TABLE\s+public\.{re.escape(name)}\s*\((.*?)\n\);",
        _without_comments(sql),
        re.IGNORECASE | re.DOTALL,
    )
    assert match, f"缺少完整表定义：{name}"
    return _normalize(match.group(1))


def _function(sql, name):
    match = re.search(
        rf"\bCREATE\s+FUNCTION\s+public\.{re.escape(name)}\s*\(.*?AS\s+\$\$(.*?)\$\$;",
        _without_comments(sql),
        re.IGNORECASE | re.DOTALL,
    )
    assert match, f"缺少函数定义：{name}"
    return _normalize(match.group(1))


def _require(text, *fragments):
    for fragment in fragments:
        assert _normalize(fragment) in text, f"缺少约束或保护：{fragment}"


def _indexes(sql, table):
    return [
        _normalize(match.group())
        for match in re.finditer(
            rf"\bCREATE\s+(?:UNIQUE\s+)?INDEX\s+\w+\s+ON\s+public\.{re.escape(table)}\s*\(.*?;",
            _without_comments(sql),
            re.IGNORECASE | re.DOTALL,
        )
    ]


def _assert_owner_rls(sql, table):
    normalized = _normalize(sql)
    owner = "user_id" if table == "patient_profiles" else "patient_id"
    _require(
        normalized,
        f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;",
        f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY;",
        f"CREATE POLICY {table}_owner ON public.{table} FOR ALL TO authenticated "
        f"USING ((SELECT auth.uid()) = {owner}) WITH CHECK ((SELECT auth.uid()) = {owner});",
    )


def test_exact_core_tables_and_no_photo_slice():
    sql = _read(MIGRATION_PATH)
    created = re.findall(r"CREATE TABLE public\.(\w+)\s*\(", _without_comments(sql))
    assert len(created) == len(set(created))
    assert set(created) == set(ALL_TABLES)
    normalized = _normalize(sql)
    assert not re.search(r"\b(storage_path|raw_input|prompt_text|transcript|image_payload)\b", normalized)
    assert not re.search(r"\b(create extension|insert into auth\.users|vector\s*\()", normalized)


def test_every_owned_table_has_pk_fk_demo_constraint_unique_and_index():
    sql = _read(MIGRATION_PATH)
    for name in OWNED_TABLES:
        body = _table(sql, name)
        _require(body, "PRIMARY KEY", "demo_only boolean NOT NULL DEFAULT true CHECK (demo_only = true)")
        assert _indexes(sql, name), f"缺少索引：{name}"
        if name == "patient_profiles":
            _require(body, "user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE RESTRICT")
        else:
            _require(
                body,
                "patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id) ON DELETE RESTRICT",
                "UNIQUE (patient_id, id)",
            )


def test_owner_rls_has_enable_force_using_and_with_check():
    sql = _read(MIGRATION_PATH)
    for name in OWNED_TABLES:
        _assert_owner_rls(sql, name)


def test_rls_check_detects_policy_removal_and_wrong_owner():
    sql = _read(MIGRATION_PATH)
    changes = (
        ("ALTER TABLE public.dose_events FORCE ROW LEVEL SECURITY;", ""),
        ("WITH CHECK ((SELECT auth.uid()) = patient_id);", "WITH CHECK (true);"),
        ("USING ((SELECT auth.uid()) = patient_id)", "USING (true)"),
    )
    for old, new in changes:
        assert old in sql
        altered = sql.replace(old, new)
        rejected = False
        try:
            _assert_owner_rls(altered, "dose_events")
        except AssertionError:
            rejected = True
        assert rejected, f"静态 RLS 检查未拒绝削弱的保护：{old}"


def test_shared_product_identity_is_not_generic_name_unique():
    sql = _read(MIGRATION_PATH)
    body = _table(sql, "medication_products")
    _require(
        body,
        "ingredient_names text[] NOT NULL",
        "market_code text NOT NULL",
        "dosage_form text NOT NULL",
        "(strength_value IS NULL) = (strength_unit IS NULL)",
        "strength_value > 0",
        "strength_value::text NOT IN ('NaN', 'Infinity', '-Infinity')",
    )
    indexes = " ".join(_indexes(sql, "medication_products"))
    _require(
        indexes,
        "CREATE UNIQUE INDEX medication_products_registration_uq ON public.medication_products(market_code, local_registration_code) WHERE local_registration_code IS NOT NULL;",
        "lower(generic_name), strength_value, strength_unit, dosage_form, market_code",
    )
    assert not re.search(r"unique\s*\(\s*(?:lower\()?generic_name", body + indexes)
    normalized = _normalize(sql)
    _require(
        normalized,
        "ALTER TABLE public.medication_products ENABLE ROW LEVEL SECURITY;",
        "ALTER TABLE public.medication_products FORCE ROW LEVEL SECURITY;",
        "CREATE POLICY medication_products_demo_read ON public.medication_products FOR SELECT TO authenticated USING (demo_only = true);",
    )


def test_all_patient_relations_use_composite_foreign_keys():
    sql = _read(MIGRATION_PATH)
    expected = {
        "source_fields": {"source_documents"},
        "patient_medications": {"source_documents"},
        "regimen_versions": {"patient_medications", "source_documents", "regimen_versions", "source_fields"},
        "dose_rules": {"regimen_versions"},
        "dose_occurrences": {"regimen_versions", "dose_rules"},
        "dose_events": {"regimen_versions", "dose_occurrences", "confirmation_challenges"},
        "confirmation_challenges": {"agent_sessions", "regimen_versions", "dose_occurrences"},
        "agent_tool_calls": {"agent_sessions", "source_documents", "regimen_versions", "dose_occurrences"},
        "audit_events": {"agent_sessions", "agent_tool_calls", "regimen_versions", "dose_events"},
    }
    relation = re.compile(
        r"foreign key \(([^)]+)\) references public\.(\w+)\(([^)]+)\) on delete restrict"
    )
    for name, targets in expected.items():
        body = _table(sql, name)
        found = relation.findall(body)
        assert {target for _, target, _ in found} == targets, name
        for local, target, remote in found:
            local_columns = local.split(", ")
            remote_columns = remote.split(", ")
            assert local_columns[0] == remote_columns[0] == "patient_id", (name, target)
            assert len(local_columns) == len(remote_columns), (name, target)
            assert remote_columns[-1] == "id", (name, target)
            _require(_table(sql, target), f"UNIQUE ({remote})")
        for target in targets:
            assert not re.search(rf"\w+ uuid[^,]*references public\.{target}\(id\)", body)
    _require(
        _normalize(sql),
        "ALTER TABLE public.regimen_versions ADD CONSTRAINT regimen_versions_confirmation_fk FOREIGN KEY (patient_id, confirmation_challenge_id) REFERENCES public.confirmation_challenges(patient_id, id) ON DELETE RESTRICT;",
    )


def test_same_medication_version_and_same_regimen_rule_event_constraints():
    sql = _read(MIGRATION_PATH)
    _require(
        _table(sql, "regimen_versions"),
        "UNIQUE (patient_id, patient_medication_id, version_no)",
        "FOREIGN KEY (patient_id, patient_medication_id, supersedes_id) REFERENCES public.regimen_versions(patient_id, patient_medication_id, id)",
        "supersedes_id IS NULL OR supersedes_id <> id",
    )
    for table in ("dose_occurrences", "confirmation_challenges", "dose_events"):
        body = _table(sql, table)
        child = "rule_id" if table == "dose_occurrences" else "occurrence_id"
        parent = "dose_rules" if table == "dose_occurrences" else "dose_occurrences"
        _require(
            body,
            f"FOREIGN KEY (patient_id, regimen_id, {child}) REFERENCES public.{parent}(patient_id, regimen_id, id)",
        )


def test_active_regimen_requires_review_quantity_unit_schedule_or_prn():
    body = _table(_read(MIGRATION_PATH), "regimen_versions")
    _require(
        body,
        "state <> 'active' OR (",
        "source_id IS NOT NULL AND source_reviewed_at IS NOT NULL",
        "dose_amount IS NOT NULL AND dose_unit IS NOT NULL",
        "medication_name_field_id IS NOT NULL AND quantity_field_id IS NOT NULL AND unit_field_id IS NOT NULL",
        "effective_from IS NOT NULL AND confirmation_challenge_id IS NOT NULL",
        "is_prn AND prn_field_id IS NOT NULL AND frequency_rule IS NULL",
        "NOT is_prn AND frequency_field_id IS NOT NULL AND frequency_rule IS NOT NULL",
        "dose_amount > 0 AND dose_amount::text NOT IN ('NaN', 'Infinity', '-Infinity')",
        "jsonb_typeof(frequency_rule) = 'object'",
        "jsonb_typeof(frequency_rule -> 'kind') = 'string'",
        "frequency_rule ->> 'kind' IN ('daily', 'weekly', 'interval')",
        "effective_to >= effective_from",
    )
    _require(
        " ".join(_indexes(_read(MIGRATION_PATH), "regimen_versions")),
        "CREATE UNIQUE INDEX regimen_versions_one_active_uq ON public.regimen_versions(patient_id, patient_medication_id) WHERE state = 'active';",
    )


def test_activation_matches_actual_reviewed_source_fields_and_current_medication():
    sql = _read(MIGRATION_PATH)
    body = _function(sql, "core_guard_regimen")
    _require(
        body,
        "medication.archived_at IS NOT NULL",
        "medication.identity_status NOT IN ('user_reviewed_document', 'professional_verified')",
        "source_row.review_status NOT IN ('user_reviewed', 'professional_verified')",
        "NEW.source_reviewed_at IS DISTINCT FROM source_row.reviewed_at",
        "review_status NOT IN ('user_reviewed', 'professional_verified')",
        "field_name = required_field.name AND field_value = required_field.expected",
        "review_status IN ('user_reviewed', 'professional_verified') AND reviewed_at IS NOT NULL",
        "NEW.medication_name_field_id, 'medication_name', to_jsonb(medication.display_name)",
        "NEW.quantity_field_id, 'dose_amount', to_jsonb(NEW.dose_amount)",
        "NEW.unit_field_id, 'dose_unit', to_jsonb(NEW.dose_unit)",
        "CASE WHEN NEW.is_prn THEN NEW.prn_field_id ELSE NEW.frequency_field_id END",
        "field_name = 'is_prn' AND field_value IS DISTINCT FROM to_jsonb(NEW.is_prn)",
        "field_name = 'route' AND field_value = to_jsonb(NEW.route)",
        "field_name = 'food_instruction' AND field_value = to_jsonb(NEW.food_instruction)",
        "prior.version_no >= NEW.version_no",
        "core_consume_confirmation",
    )
    _require(
        _normalize(sql),
        "CREATE TRIGGER regimen_versions_guard BEFORE INSERT OR UPDATE OR DELETE ON public.regimen_versions FOR EACH ROW EXECUTE FUNCTION public.core_guard_regimen();",
    )


def test_reviewed_sources_and_historical_regimens_are_not_overwritten():
    sql = _read(MIGRATION_PATH)
    _require(
        _function(sql, "core_freeze_reviewed_source"),
        "OLD.review_status IN ('user_reviewed', 'professional_verified')",
        "RAISE EXCEPTION",
    )
    body = _function(sql, "core_guard_regimen")
    _require(
        body,
        "IF TG_OP = 'DELETE' THEN RAISE EXCEPTION",
        "OLD.state IN ('ended', 'superseded') THEN RAISE EXCEPTION",
        "NEW.state NOT IN ('ended', 'superseded')",
        "to_jsonb(NEW) - ARRAY['state', 'effective_to']",
        "NEW.patient_medication_id <> OLD.patient_medication_id OR NEW.version_no <> OLD.version_no",
    )
    _require(
        _function(sql, "core_guard_medication_history"),
        "to_jsonb(NEW) - 'archived_at'",
        "state = 'active'",
        "RAISE EXCEPTION",
    )
    for table in ("source_documents", "patient_medications"):
        assert re.search(rf"CREATE TRIGGER \w+ BEFORE UPDATE OR DELETE ON public\.{table}\b", sql)
    _require(
        _normalize(sql),
        "CREATE TRIGGER source_fields_history_guard BEFORE INSERT OR UPDATE OR DELETE ON public.source_fields",
    )
    _require(
        _function(sql, "core_freeze_reviewed_source"),
        "parent_status IN ('user_reviewed', 'professional_verified')",
        "WHERE patient_id = owner_id AND id = document_id FOR UPDATE",
    )


def test_occurrence_generation_and_dose_write_uniqueness():
    sql = _read(MIGRATION_PATH)
    _require(_table(sql, "dose_occurrences"), "UNIQUE (patient_id, generation_key)")
    events = _table(sql, "dose_events")
    _require(
        events,
        "UNIQUE (patient_id, occurrence_id)",
        "UNIQUE (patient_id, idempotency_key)",
        "UNIQUE (patient_id, confirmation_challenge_id)",
        "occurrence_id uuid,",
        "regimen_id uuid NOT NULL",
    )
    body = _function(sql, "core_guard_occurrence")
    _require(
        body,
        "regimen.state <> 'active' OR regimen.is_prn",
        "NEW.due_at < regimen.effective_from",
        "NEW.due_at >= regimen.effective_to",
        "rule_row.rule_kind <> 'scheduled' OR NOT rule_row.enabled",
        "to_jsonb(NEW) - 'status'",
        "OLD.status = 'closed'",
    )


def test_self_report_never_proves_ingestion_or_visual_match():
    sql = _read(MIGRATION_PATH)
    events = _table(sql, "dose_events")
    _require(
        events,
        "intake_status IN ('reported_taken', 'reported_not_taken', 'unsure', 'not_reported')",
        "visual_status text NOT NULL DEFAULT 'not_checked'",
        "ingestion_proven boolean NOT NULL DEFAULT false CHECK (ingestion_proven = false)",
        "evidence_method = 'self_report'",
        "CONSTRAINT dose_events_no_photo_ck CHECK (visual_status = 'not_checked')",
    )
    guard = _function(sql, "core_guard_dose_event")
    assert not re.search(r"new\.(ingestion_proven|visual_status)\s*:=", guard)
    assert not re.search(r"'(?:taken|verified_ingestion|missed)'", events)
    _require(
        guard,
        "regimen.state <> 'active'",
        "medication.archived_at IS NOT NULL",
        "IF regimen.is_prn THEN",
        "NEW.occurrence_id IS NOT NULL THEN RAISE EXCEPTION",
        "occurrence.status = 'closed'",
        "FOR UPDATE",
        "NEW.occurrence_id, NEW.intake_status, NEW.idempotency_key",
    )
    _require(
        _normalize(sql),
        "CREATE TRIGGER dose_events_history_guard BEFORE UPDATE OR DELETE ON public.dose_events FOR EACH ROW EXECUTE FUNCTION public.core_reject_mutation();",
    )


def test_timezone_and_absolute_timestamps_are_explicit():
    sql = _read(MIGRATION_PATH)
    _require(_normalize(sql), "SET LOCAL TIME ZONE 'UTC';")
    for name in ("patient_profiles", "dose_rules"):
        _require(_table(sql, name), "timezone text NOT NULL DEFAULT 'Asia/Singapore'")
    for table, columns in {
        "regimen_versions": ("effective_from", "effective_to", "source_reviewed_at"),
        "dose_occurrences": ("due_at", "created_at"),
        "dose_events": ("event_time", "created_at"),
        "confirmation_challenges": ("issued_at", "expires_at", "confirmed_at", "consumed_at"),
    }.items():
        for column in columns:
            _require(_table(sql, table), f"{column} timestamptz")
    _require(_table(sql, "dose_rules"), "local_time time without time zone")
    _require(
        _function(sql, "core_validate_timezone"),
        "SELECT 1 FROM pg_catalog.pg_timezone_names WHERE name = NEW.timezone",
        "RAISE EXCEPTION",
    )
    _require(_function(sql, "core_guard_rule"), "NEW.timezone IS DISTINCT FROM patient_timezone")


def test_prn_rule_has_no_scheduled_time_or_inferred_occurrence():
    sql = _read(MIGRATION_PATH)
    _require(
        _table(sql, "dose_rules"),
        "rule_kind = 'prn' AND local_time IS NULL AND days_of_week IS NULL",
        "rule_kind = 'scheduled' AND local_time IS NOT NULL AND days_of_week IS NOT NULL",
        "days_of_week <@ ARRAY[1, 2, 3, 4, 5, 6, 7]::smallint[]",
        "array_position(days_of_week, NULL) IS NULL",
    )
    _require(_function(sql, "core_guard_rule"), "(NEW.rule_kind = 'prn') IS DISTINCT FROM regimen.is_prn")
    _require(_function(sql, "core_guard_occurrence"), "regimen.state <> 'active' OR regimen.is_prn")


def test_confirmation_hash_binding_expiry_and_single_use():
    sql = _read(MIGRATION_PATH)
    body = _table(sql, "confirmation_challenges")
    _require(
        body,
        "token_hash text NOT NULL CHECK (token_hash ~ '^[0-9a-f]{64}$')",
        "request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$')",
        "UNIQUE (patient_id, token_hash)",
        "UNIQUE (patient_id, idempotency_key)",
        "expires_at <= issued_at + interval '10 minutes'",
        "consumed_at >= confirmed_at AND consumed_at < expires_at",
    )
    consume = _function(sql, "core_consume_confirmation")
    _require(
        consume,
        "WHERE patient_id = p_patient_id AND id = p_challenge_id FOR UPDATE",
        "WHERE patient_id = p_patient_id AND id = challenge.session_id FOR UPDATE",
        "session_row.state_version <> challenge.session_state_version",
        "session_row.state <> 'awaiting_confirmation'",
        "session_row.expires_at <= consumed_time",
        "challenge.confirmed_at IS NULL",
        "challenge.expires_at <= consumed_time",
        "challenge.consumed_at IS NOT NULL",
        "challenge.action <> p_action",
        "challenge.regimen_id <> p_regimen_id",
        "challenge.occurrence_id IS DISTINCT FROM p_occurrence_id",
        "challenge.intended_intake_status IS DISTINCT FROM p_intake_status",
        "challenge.idempotency_key <> p_idempotency_key",
        "SET consumed_at = consumed_time",
    )
    _require(
        _function(sql, "core_guard_challenge"),
        "NEW.confirmed_at IS NOT NULL OR NEW.consumed_at IS NOT NULL",
        "to_jsonb(NEW) - ARRAY['confirmed_at', 'consumed_at']",
        "OLD.consumed_at IS NOT NULL",
        "NEW.consumed_at IS NOT NULL AND OLD.confirmed_at IS NULL",
    )


def test_trace_summary_is_an_allowlist_not_an_unrestricted_json_blob():
    sql = _read(MIGRATION_PATH)
    safe = _function(sql, "core_trace_summary_is_safe")
    allowed = set(re.findall(r"when '([^']+)' then", safe))
    assert allowed == {"item_count", "demo_only", "decision", "error_code", "state", "intake_status", "visual_status"}
    _require(
        safe,
        "jsonb_typeof(p_summary) <> 'object'",
        "octet_length(p_summary::text) > 1024",
        "jsonb_each(p_summary)",
        "ELSE RETURN false",
        "jsonb_typeof(entry.item) <> 'string'",
        "jsonb_typeof(entry.item) <> 'number'",
        "entry.item <> 'true'::jsonb",
    )
    for table, columns in {
        "agent_tool_calls": ("request_summary", "response_summary"),
        "audit_events": ("before_redacted", "after_redacted"),
    }.items():
        body = _table(sql, table)
        for column in columns:
            _require(body, f"CHECK (public.core_trace_summary_is_safe({column}))")
        _require(body, "correlation_id uuid NOT NULL")
    sessions = _table(sql, "agent_sessions")
    assert "pending_field_names text[]" in sessions
    assert "pending_slots" not in sessions
    _require(
        _normalize(sql),
        "CREATE TRIGGER audit_events_history_guard BEFORE UPDATE OR DELETE ON public.audit_events FOR EACH ROW EXECUTE FUNCTION public.core_reject_mutation();",
    )


def test_every_foreign_key_has_a_matching_index_prefix():
    sql = _read(MIGRATION_PATH)
    for name in ALL_TABLES:
        indexes = _indexes(sql, name)
        body = _table(sql, name)
        indexed_columns = re.findall(r"(?:unique|primary key)\s*\(([^)]+)\)", body)
        indexed_columns += [match for index in indexes for match in re.findall(r"on public\.\w+\(([^)]+)\)", index)]
        for columns in re.findall(r"foreign key \(([^)]+)\)", body):
            assert any(value == columns or value.startswith(columns + ", ") for value in indexed_columns), (name, columns)
    _require(
        " ".join(_indexes(sql, "dose_occurrences")),
        "ON public.dose_occurrences(patient_id, due_at)",
    )
    _require(" ".join(_indexes(sql, "dose_events")), "ON public.dose_events(patient_id, event_time)")
    _require(
        " ".join(_indexes(sql, "agent_tool_calls")),
        "ON public.agent_tool_calls(patient_id, session_id, called_at)",
    )


def test_no_anonymous_writes_or_security_definer_rpc():
    sql = _normalize(_read(MIGRATION_PATH))
    assert "security definer" not in sql
    functions = re.findall(r"create function public\.(\w+)\(", sql)
    assert functions
    assert sql.count("security invoker set search_path = pg_catalog, public") == len(functions)
    grants = re.findall(r"\bgrant .*?;", sql)
    assert grants
    for grant in grants:
        assert not re.search(r"\bto (?:public|anon)\b", grant)
        if "authenticated" in grant and "on table" in grant:
            assert grant.startswith("grant select on table")
        if "authenticated" in grant and "on function" in grant:
            assert "core_trace_summary_is_safe(jsonb)" in grant
    _require(sql, "FROM PUBLIC, anon, authenticated, service_role;")
    for name in functions:
        revoke = re.search(r"revoke all on function (.*?) from public, anon, authenticated, service_role;", sql)
        assert revoke and f"public.{name}(" in revoke.group(1)


def test_transaction_wrappers_and_no_destructive_up_migration():
    for path in (MIGRATION_PATH, ROLLBACK_PATH):
        normalized = _normalize(_read(path))
        assert normalized.startswith("begin;")
        assert normalized.endswith("commit;")
        assert len(re.findall(r"\bcommit;", normalized)) == 1
        assert "SET LOCAL search_path = pg_catalog, public;".lower() in normalized
    up = _normalize(_read(MIGRATION_PATH))
    assert not re.search(r"\b(drop|truncate)\s+(table|schema|database|extension)\b", up)
    assert not re.search(r"\bon delete\s+(cascade|set null)\b", up)
    assert not re.search(r"\b(execute|dblink|http_get|http_post)\s*\(", up)


def test_rollback_warns_and_requires_explicit_admin_acknowledgement():
    raw = _read(ROLLBACK_PATH)
    assert "不要在生产执行" in raw
    sql = _normalize(raw)
    _require(
        sql,
        "current_setting('pharmascan.rollback_target', true) IS DISTINCT FROM 'empty-temporary-test-database'",
        "SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = current_user AND (rolsuper OR rolbypassrls)",
        "RAISE EXCEPTION 'Rollback refused: explicit empty temporary test database acknowledgement required'",
        "RAISE EXCEPTION 'Rollback refused: an administrative role that can inspect all RLS rows is required'",
    )
    assert not re.search(r"\bset\s+(?:local\s+)?pharmascan\.rollback_target", sql)


def test_rollback_locks_and_rejects_non_demo_and_even_demo_rows_before_drops():
    sql = _normalize(_read(ROLLBACK_PATH))
    lock = re.search(r"lock table (.*?) in access exclusive mode;", sql)
    assert lock
    assert set(re.findall(r"public\.(\w+)", lock.group(1))) == set(ALL_TABLES)
    protected = re.search(r"if exists \((.*?)\) then raise exception 'rollback refused: non-demo", sql)
    empty = re.search(
        r"if exists \(\s*(select 1 from public\.patient_profiles union all.*?)\) then raise exception 'rollback refused: data exists",
        sql,
    )
    assert protected and empty
    for table in ALL_TABLES:
        _require(protected.group(1), f"SELECT 1 FROM public.{table} WHERE demo_only IS DISTINCT FROM true")
        assert re.search(rf"select 1 from public\.{table}(?: union all|$)", empty.group(1).strip()), table
    _require(protected.group(1), "is_synthetic IS DISTINCT FROM true")
    first_drop = sql.index("drop constraint")
    assert sql.index("rolsuper or rolbypassrls") < lock.start() < protected.start() < empty.start() < first_drop


def test_rollback_is_restrict_only_and_dependency_order_is_safe():
    up = _read(MIGRATION_PATH)
    down = _normalize(_read(ROLLBACK_PATH))
    assert not re.search(r"\b(cascade|truncate|delete from)\b", down)
    assert not re.search(r"drop\s+(schema|database|extension)\b", down)
    assert not re.search(r"(?:drop table|alter table) auth\.users\b", down)
    assert not re.search(r"\b(disable trigger|disable row level security|row_security\s*=\s*off)\b", down)
    dropped = re.findall(r"drop table public\.(\w+) restrict;", down)
    assert len(dropped) == len(set(dropped))
    assert set(dropped) == set(ALL_TABLES)
    position = {table: index for index, table in enumerate(dropped)}
    for table in ALL_TABLES:
        for parent in re.findall(r"references public\.(\w+)\(", _table(up, table)):
            if parent != table:
                assert position[table] < position[parent], (table, parent)
    _require(
        down,
        "ALTER TABLE public.regimen_versions DROP CONSTRAINT regimen_versions_confirmation_fk RESTRICT;",
    )
    assert down.index("drop constraint regimen_versions_confirmation_fk") < down.index("drop table")
    created_functions = set(re.findall(r"CREATE FUNCTION public\.(\w+)\(", up))
    removed_functions = set(re.findall(r"drop function public\.(\w+)\(", down))
    assert created_functions == removed_functions
    assert len(re.findall(r"drop function .*? restrict;", down)) == len(created_functions)
    assert down.rindex("drop table") < down.index("drop function")


def test_static_tests_are_local_text_only_and_do_not_claim_db_execution():
    assert "不证明真实迁移" in __doc__
    source = Path(__file__).read_text(encoding="utf-8")
    imports = re.findall(r"^(?:from|import)\s+(\w+)", source, re.MULTILINE)
    assert set(imports) == {"pathlib", "re"}
    assert not re.search(r"^\s*(?:import|from)\s+(?:psycopg|sqlalchemy|supabase|requests|subprocess|socket)\b", source, re.MULTILINE)
