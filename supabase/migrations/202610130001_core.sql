-- Gate1：开发者维护的 Supabase PostgreSQL 15+ 迁移，不是 Agent 的任意 SQL 工具。
-- 尚未连接数据库或验证真实迁移；由开发者在隔离的临时 PostgreSQL 中先行验证。
-- 本切片只接受无照片 synthetic/demo_only 数据，不创建 Auth 用户、不接入存储或向量。
-- authenticated 仅有所属行的 SELECT 权限；写入经验证 JWT 的 backend 服务执行。
-- service_role 可绕过 RLS，应用仍必须从已验证身份派生 patient_id、验证确认令牌。
BEGIN;
SET LOCAL TIME ZONE 'UTC';
SET LOCAL search_path = pg_catalog, public;

CREATE TABLE public.patient_profiles (
    user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE RESTRICT,
    display_name text CHECK (display_name IS NULL OR length(display_name) BETWEEN 1 AND 80),
    timezone text NOT NULL DEFAULT 'Asia/Singapore',
    language text NOT NULL DEFAULT 'en' CHECK (language IN ('en', 'zh')),
    visual_check_mode text NOT NULL DEFAULT 'REMINDERS_ONLY'
        CHECK (visual_check_mode = 'REMINDERS_ONLY'),
    demo_only boolean NOT NULL DEFAULT true CHECK (demo_only = true),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT patient_profiles_timezone_ck CHECK (
        timezone = 'UTC' OR timezone ~ '^[A-Za-z_]+/[A-Za-z0-9_+/-]+$'
    )
);
CREATE INDEX patient_profiles_created_idx ON public.patient_profiles(created_at);

-- 产品为共享 synthetic 目录，不是患者行；不以通用名作为全局唯一药品身份。
CREATE TABLE public.medication_products (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    generic_name text NOT NULL CHECK (length(btrim(generic_name)) BETWEEN 1 AND 160),
    brand_name text CHECK (brand_name IS NULL OR length(btrim(brand_name)) BETWEEN 1 AND 160),
    ingredient_names text[] NOT NULL CHECK (
        cardinality(ingredient_names) > 0 AND array_position(ingredient_names, NULL) IS NULL
    ),
    strength_value numeric CHECK (
        strength_value > 0 AND strength_value::text NOT IN ('NaN', 'Infinity', '-Infinity')
    ),
    strength_unit text CHECK (strength_unit IS NULL OR length(btrim(strength_unit)) BETWEEN 1 AND 40),
    dosage_form text NOT NULL CHECK (length(btrim(dosage_form)) BETWEEN 1 AND 80),
    release_type text CHECK (release_type IS NULL OR length(btrim(release_type)) BETWEEN 1 AND 80),
    market_code text NOT NULL CHECK (market_code ~ '^[A-Z]{2}$'),
    local_registration_code text CHECK (
        local_registration_code IS NULL OR length(btrim(local_registration_code)) BETWEEN 1 AND 100
    ),
    demo_only boolean NOT NULL DEFAULT true CHECK (demo_only = true),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT medication_products_strength_pair_ck CHECK (
        (strength_value IS NULL) = (strength_unit IS NULL)
    )
);
CREATE UNIQUE INDEX medication_products_registration_uq
    ON public.medication_products(market_code, local_registration_code)
    WHERE local_registration_code IS NOT NULL;
CREATE INDEX medication_products_identity_idx
    ON public.medication_products(lower(generic_name), strength_value, strength_unit, dosage_form, market_code);

CREATE TABLE public.source_documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id) ON DELETE RESTRICT,
    source_kind text NOT NULL CHECK (source_kind IN ('mock_import', 'user_manual')),
    is_synthetic boolean NOT NULL DEFAULT true CHECK (is_synthetic = true),
    review_status text NOT NULL DEFAULT 'extracted'
        CHECK (review_status IN ('extracted', 'user_reviewed', 'professional_verified', 'rejected')),
    reviewed_at timestamptz,
    checksum text NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),
    issued_at timestamptz,
    uploaded_at timestamptz NOT NULL DEFAULT now(),
    demo_only boolean NOT NULL DEFAULT true CHECK (demo_only = true),
    UNIQUE (patient_id, id),
    UNIQUE (patient_id, checksum),
    CONSTRAINT source_documents_review_ck CHECK (
        (review_status IN ('user_reviewed', 'professional_verified')) = (reviewed_at IS NOT NULL)
    )
);
CREATE INDEX source_documents_review_idx ON public.source_documents(patient_id, review_status, uploaded_at);

CREATE TABLE public.source_fields (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id) ON DELETE RESTRICT,
    source_id uuid NOT NULL,
    field_name text NOT NULL CHECK (field_name IN (
        'medication_name', 'dose_amount', 'dose_unit', 'frequency_rule', 'is_prn',
        'route', 'food_instruction', 'strength', 'form'
    )),
    field_value jsonb NOT NULL CHECK (
        jsonb_typeof(field_value) IN ('string', 'number', 'boolean', 'object', 'array')
        AND octet_length(field_value::text) <= 4096
    ),
    evidence_locator text NOT NULL CHECK (evidence_locator ~ '^synthetic:[A-Za-z0-9_.:-]{1,120}$'),
    extraction_method text NOT NULL CHECK (extraction_method IN ('synthetic_fixture', 'manual')),
    review_status text NOT NULL DEFAULT 'extracted'
        CHECK (review_status IN ('extracted', 'user_reviewed', 'professional_verified', 'rejected')),
    reviewed_at timestamptz,
    demo_only boolean NOT NULL DEFAULT true CHECK (demo_only = true),
    UNIQUE (patient_id, id),
    UNIQUE (patient_id, source_id, id),
    UNIQUE (patient_id, source_id, field_name),
    FOREIGN KEY (patient_id, source_id) REFERENCES public.source_documents(patient_id, id) ON DELETE RESTRICT,
    CONSTRAINT source_fields_review_ck CHECK (
        (review_status IN ('user_reviewed', 'professional_verified')) = (reviewed_at IS NOT NULL)
    )
);
CREATE INDEX source_fields_document_idx ON public.source_fields(patient_id, source_id, review_status);

CREATE TABLE public.patient_medications (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id) ON DELETE RESTRICT,
    product_id uuid REFERENCES public.medication_products(id) ON DELETE RESTRICT,
    display_name text NOT NULL CHECK (length(btrim(display_name)) BETWEEN 1 AND 160),
    source_id uuid,
    identity_status text NOT NULL DEFAULT 'unverified'
        CHECK (identity_status IN ('unverified', 'user_reviewed_document', 'professional_verified')),
    created_at timestamptz NOT NULL DEFAULT now(),
    archived_at timestamptz CHECK (archived_at IS NULL OR archived_at >= created_at),
    demo_only boolean NOT NULL DEFAULT true CHECK (demo_only = true),
    UNIQUE (patient_id, id),
    FOREIGN KEY (patient_id, source_id) REFERENCES public.source_documents(patient_id, id) ON DELETE RESTRICT
);
CREATE INDEX patient_medications_created_idx ON public.patient_medications(patient_id, created_at);
CREATE INDEX patient_medications_source_idx ON public.patient_medications(patient_id, source_id);
CREATE INDEX patient_medications_product_idx ON public.patient_medications(product_id);

CREATE TABLE public.regimen_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id) ON DELETE RESTRICT,
    patient_medication_id uuid NOT NULL,
    source_id uuid,
    version_no integer NOT NULL CHECK (version_no > 0),
    state text NOT NULL DEFAULT 'draft'
        CHECK (state IN ('draft', 'active', 'ended', 'superseded', 'pending_clarification')),
    dose_amount numeric CHECK (
        dose_amount > 0 AND dose_amount::text NOT IN ('NaN', 'Infinity', '-Infinity')
    ),
    dose_unit text CHECK (dose_unit IS NULL OR length(btrim(dose_unit)) BETWEEN 1 AND 40),
    frequency_rule jsonb,
    is_prn boolean NOT NULL DEFAULT false,
    route text CHECK (route IS NULL OR length(btrim(route)) BETWEEN 1 AND 80),
    food_instruction text CHECK (food_instruction IS NULL OR length(btrim(food_instruction)) BETWEEN 1 AND 160),
    medication_name_field_id uuid,
    quantity_field_id uuid,
    unit_field_id uuid,
    frequency_field_id uuid,
    prn_field_id uuid,
    source_reviewed_at timestamptz,
    effective_from timestamptz,
    effective_to timestamptz,
    supersedes_id uuid,
    confirmation_challenge_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    demo_only boolean NOT NULL DEFAULT true CHECK (demo_only = true),
    UNIQUE (patient_id, id),
    UNIQUE (patient_id, patient_medication_id, id),
    UNIQUE (patient_id, patient_medication_id, version_no),
    UNIQUE (patient_id, confirmation_challenge_id),
    FOREIGN KEY (patient_id, patient_medication_id)
        REFERENCES public.patient_medications(patient_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (patient_id, source_id) REFERENCES public.source_documents(patient_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (patient_id, patient_medication_id, supersedes_id)
        REFERENCES public.regimen_versions(patient_id, patient_medication_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (patient_id, source_id, medication_name_field_id)
        REFERENCES public.source_fields(patient_id, source_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (patient_id, source_id, quantity_field_id)
        REFERENCES public.source_fields(patient_id, source_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (patient_id, source_id, unit_field_id)
        REFERENCES public.source_fields(patient_id, source_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (patient_id, source_id, frequency_field_id)
        REFERENCES public.source_fields(patient_id, source_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (patient_id, source_id, prn_field_id)
        REFERENCES public.source_fields(patient_id, source_id, id) ON DELETE RESTRICT,
    CONSTRAINT regimen_versions_not_self_ck CHECK (supersedes_id IS NULL OR supersedes_id <> id),
    CONSTRAINT regimen_versions_time_ck CHECK (
        (effective_to IS NULL OR (effective_from IS NOT NULL AND effective_to >= effective_from))
        AND (state NOT IN ('ended', 'superseded') OR effective_to IS NOT NULL)
    ),
    CONSTRAINT regimen_versions_frequency_ck CHECK (
        frequency_rule IS NULL OR (
            jsonb_typeof(frequency_rule) = 'object'
            AND frequency_rule ? 'kind'
            AND jsonb_typeof(frequency_rule -> 'kind') = 'string'
            AND frequency_rule ->> 'kind' IN ('daily', 'weekly', 'interval')
            AND octet_length(frequency_rule::text) <= 4096
        )
    ),
    CONSTRAINT regimen_versions_active_complete_ck CHECK (
        state <> 'active' OR (
            source_id IS NOT NULL AND source_reviewed_at IS NOT NULL
            AND dose_amount IS NOT NULL AND dose_unit IS NOT NULL
            AND medication_name_field_id IS NOT NULL AND quantity_field_id IS NOT NULL AND unit_field_id IS NOT NULL
            AND effective_from IS NOT NULL AND confirmation_challenge_id IS NOT NULL
            AND ((is_prn AND prn_field_id IS NOT NULL AND frequency_rule IS NULL)
                 OR (NOT is_prn AND frequency_field_id IS NOT NULL AND frequency_rule IS NOT NULL))
        )
    )
);
CREATE UNIQUE INDEX regimen_versions_one_active_uq
    ON public.regimen_versions(patient_id, patient_medication_id) WHERE state = 'active';
CREATE INDEX regimen_versions_effective_idx ON public.regimen_versions(patient_id, effective_from, effective_to);
CREATE INDEX regimen_versions_source_idx ON public.regimen_versions(patient_id, source_id);
CREATE INDEX regimen_versions_supersedes_idx ON public.regimen_versions(patient_id, patient_medication_id, supersedes_id);
CREATE INDEX regimen_versions_name_field_idx ON public.regimen_versions(patient_id, source_id, medication_name_field_id);
CREATE INDEX regimen_versions_quantity_field_idx ON public.regimen_versions(patient_id, source_id, quantity_field_id);
CREATE INDEX regimen_versions_unit_field_idx ON public.regimen_versions(patient_id, source_id, unit_field_id);
CREATE INDEX regimen_versions_frequency_field_idx ON public.regimen_versions(patient_id, source_id, frequency_field_id);
CREATE INDEX regimen_versions_prn_field_idx ON public.regimen_versions(patient_id, source_id, prn_field_id);

CREATE TABLE public.dose_rules (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id) ON DELETE RESTRICT,
    regimen_id uuid NOT NULL,
    rule_kind text NOT NULL CHECK (rule_kind IN ('scheduled', 'prn')),
    -- One rule row carries exactly ONE local time. A regimen with several
    -- daily times (e.g. 08:00 and 20:00) is represented by several rows, not
    -- by packing times into a single value. This keeps every occurrence
    -- attributable to a specific rule_id and keeps the column genuinely
    -- time-typed.
    local_time time without time zone,
    days_of_week smallint[],
    timezone text NOT NULL DEFAULT 'Asia/Singapore',
    enabled boolean NOT NULL DEFAULT true,
    demo_only boolean NOT NULL DEFAULT true CHECK (demo_only = true),
    UNIQUE (patient_id, id),
    UNIQUE (patient_id, regimen_id, id),
    -- A patient must not accumulate two identical rules for one regimen.
    CONSTRAINT dose_rules_no_duplicate_slot_uk UNIQUE NULLS NOT DISTINCT (patient_id, regimen_id, rule_kind, local_time),
    FOREIGN KEY (patient_id, regimen_id) REFERENCES public.regimen_versions(patient_id, id) ON DELETE RESTRICT,
    CONSTRAINT dose_rules_timezone_ck CHECK (
        timezone = 'UTC' OR timezone ~ '^[A-Za-z_]+/[A-Za-z0-9_+/-]+$'
    ),
    CONSTRAINT dose_rules_schedule_ck CHECK (
        (rule_kind = 'prn' AND local_time IS NULL AND days_of_week IS NULL)
        OR (rule_kind = 'scheduled' AND local_time IS NOT NULL AND days_of_week IS NOT NULL
            AND cardinality(days_of_week) BETWEEN 1 AND 7
            AND array_position(days_of_week, NULL) IS NULL
            AND days_of_week <@ ARRAY[1, 2, 3, 4, 5, 6, 7]::smallint[])
    )
);
CREATE INDEX dose_rules_regimen_idx ON public.dose_rules(patient_id, regimen_id, enabled);

CREATE TABLE public.dose_occurrences (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id) ON DELETE RESTRICT,
    regimen_id uuid NOT NULL,
    rule_id uuid NOT NULL,
    due_at timestamptz NOT NULL,
    status text NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled', 'past_due', 'closed')),
    generation_key text NOT NULL CHECK (generation_key ~ '^[A-Za-z0-9_.:/+-]{1,200}$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    demo_only boolean NOT NULL DEFAULT true CHECK (demo_only = true),
    UNIQUE (patient_id, id),
    UNIQUE (patient_id, regimen_id, id),
    UNIQUE (patient_id, generation_key),
    FOREIGN KEY (patient_id, regimen_id) REFERENCES public.regimen_versions(patient_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (patient_id, regimen_id, rule_id) REFERENCES public.dose_rules(patient_id, regimen_id, id) ON DELETE RESTRICT
);
CREATE INDEX dose_occurrences_due_idx ON public.dose_occurrences(patient_id, due_at);
CREATE INDEX dose_occurrences_regimen_idx ON public.dose_occurrences(patient_id, regimen_id, rule_id);

CREATE TABLE public.agent_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id) ON DELETE RESTRICT,
    intent text CHECK (intent IN ('medication_enrollment', 'dose_self_report', 'medication_history', 'clarification')),
    state text NOT NULL DEFAULT 'collecting'
        CHECK (state IN ('collecting', 'awaiting_confirmation', 'completed', 'blocked', 'expired')),
    pending_field_names text[] NOT NULL DEFAULT ARRAY[]::text[] CHECK (
        array_position(pending_field_names, NULL) IS NULL
        AND pending_field_names <@ ARRAY['medication_name', 'dose_amount', 'dose_unit', 'frequency_rule', 'is_prn']::text[]
    ),
    prompt_version text NOT NULL CHECK (prompt_version ~ '^[A-Za-z0-9_.-]{1,64}$'),
    state_version integer NOT NULL DEFAULT 1 CHECK (state_version > 0),
    updated_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL CHECK (expires_at > updated_at),
    demo_only boolean NOT NULL DEFAULT true CHECK (demo_only = true),
    UNIQUE (patient_id, id)
);
CREATE INDEX agent_sessions_updated_idx ON public.agent_sessions(patient_id, updated_at);

-- 只存散列，不存令牌或完整请求。服务验证实际令牌、规范化请求散列与显式用户确认。
CREATE TABLE public.confirmation_challenges (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id) ON DELETE RESTRICT,
    session_id uuid NOT NULL,
    session_state_version integer NOT NULL CHECK (session_state_version > 0),
    action text NOT NULL CHECK (action IN ('activate_regimen', 'record_self_report')),
    regimen_id uuid NOT NULL,
    occurrence_id uuid,
    intended_intake_status text,
    idempotency_key text NOT NULL CHECK (idempotency_key ~ '^[A-Za-z0-9_.:-]{1,128}$'),
    token_hash text NOT NULL CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    issued_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    confirmed_at timestamptz,
    consumed_at timestamptz,
    demo_only boolean NOT NULL DEFAULT true CHECK (demo_only = true),
    UNIQUE (patient_id, id),
    UNIQUE (patient_id, token_hash),
    UNIQUE (patient_id, idempotency_key),
    FOREIGN KEY (patient_id, session_id) REFERENCES public.agent_sessions(patient_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (patient_id, regimen_id) REFERENCES public.regimen_versions(patient_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (patient_id, regimen_id, occurrence_id)
        REFERENCES public.dose_occurrences(patient_id, regimen_id, id) ON DELETE RESTRICT,
    CONSTRAINT confirmation_challenges_action_ck CHECK (
        (action = 'activate_regimen' AND occurrence_id IS NULL AND intended_intake_status IS NULL)
        OR (action = 'record_self_report' AND intended_intake_status IS NOT NULL
            AND intended_intake_status IN ('reported_taken', 'reported_not_taken', 'unsure', 'not_reported'))
    ),
    CONSTRAINT confirmation_challenges_time_ck CHECK (
        expires_at > issued_at AND expires_at <= issued_at + interval '10 minutes'
        AND (confirmed_at IS NULL OR (confirmed_at >= issued_at AND confirmed_at < expires_at))
        AND (consumed_at IS NULL OR (confirmed_at IS NOT NULL AND consumed_at >= confirmed_at AND consumed_at < expires_at))
    )
);
CREATE INDEX confirmation_challenges_session_idx ON public.confirmation_challenges(patient_id, session_id, expires_at);
CREATE INDEX confirmation_challenges_regimen_idx ON public.confirmation_challenges(patient_id, regimen_id, occurrence_id);
ALTER TABLE public.regimen_versions ADD CONSTRAINT regimen_versions_confirmation_fk
    FOREIGN KEY (patient_id, confirmation_challenge_id)
    REFERENCES public.confirmation_challenges(patient_id, id) ON DELETE RESTRICT;

CREATE TABLE public.dose_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id) ON DELETE RESTRICT,
    occurrence_id uuid,
    regimen_id uuid NOT NULL,
    confirmation_challenge_id uuid NOT NULL,
    event_time timestamptz NOT NULL,
    intake_status text NOT NULL
        CHECK (intake_status IN ('reported_taken', 'reported_not_taken', 'unsure', 'not_reported')),
    visual_status text NOT NULL DEFAULT 'not_checked' CHECK (visual_status IN (
        'not_checked', 'visually_consistent', 'ambiguous', 'unmatched', 'image_unusable'
    )),
    evidence_method text NOT NULL DEFAULT 'self_report' CHECK (evidence_method = 'self_report'),
    ingestion_proven boolean NOT NULL DEFAULT false CHECK (ingestion_proven = false),
    idempotency_key text NOT NULL CHECK (idempotency_key ~ '^[A-Za-z0-9_.:-]{1,128}$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    demo_only boolean NOT NULL DEFAULT true CHECK (demo_only = true),
    UNIQUE (patient_id, id),
    UNIQUE (patient_id, occurrence_id),
    UNIQUE (patient_id, idempotency_key),
    UNIQUE (patient_id, confirmation_challenge_id),
    FOREIGN KEY (patient_id, regimen_id) REFERENCES public.regimen_versions(patient_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (patient_id, regimen_id, occurrence_id)
        REFERENCES public.dose_occurrences(patient_id, regimen_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (patient_id, confirmation_challenge_id)
        REFERENCES public.confirmation_challenges(patient_id, id) ON DELETE RESTRICT,
    CONSTRAINT dose_events_no_photo_ck CHECK (visual_status = 'not_checked')
);
CREATE INDEX dose_events_time_idx ON public.dose_events(patient_id, event_time);
CREATE INDEX dose_events_regimen_idx ON public.dose_events(patient_id, regimen_id, occurrence_id);

-- 脱敏摘要只允许固定枚举/计数/布尔；拒绝任意字符串、全文输入、模型原始响应、秘密与照片。
CREATE FUNCTION public.core_trace_summary_is_safe(p_summary jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SECURITY INVOKER SET search_path = pg_catalog, public AS $$
DECLARE
    entry record;
BEGIN
    IF p_summary IS NULL OR jsonb_typeof(p_summary) <> 'object' OR octet_length(p_summary::text) > 1024 THEN
        RETURN false;
    END IF;
    FOR entry IN SELECT key, value AS item FROM jsonb_each(p_summary) LOOP
        CASE entry.key
            WHEN 'item_count' THEN
                IF jsonb_typeof(entry.item) <> 'number' OR entry.item::text !~ '^[0-9]{1,7}$' THEN RETURN false; END IF;
            WHEN 'demo_only' THEN
                IF entry.item <> 'true'::jsonb THEN RETURN false; END IF;
            WHEN 'decision' THEN
                IF jsonb_typeof(entry.item) <> 'string' OR entry.item #>> '{}' NOT IN (
                    'allowed', 'blocked', 'needs_clarification', 'confirmation_required', 'recorded', 'simulated'
                ) THEN RETURN false; END IF;
            WHEN 'error_code' THEN
                IF jsonb_typeof(entry.item) <> 'string' OR entry.item #>> '{}' NOT IN (
                    'AUTH_REQUIRED', 'NOT_FOUND', 'SOURCE_UNREVIEWED', 'INCOMPLETE_REGIMEN',
                    'CONFIRMATION_REQUIRED', 'CONFIRMATION_EXPIRED', 'DUPLICATE_EVENT', 'STALE_VERSION',
                    'POLICY_BLOCKED', 'INVALID_INPUT', 'PROVIDER_UNAVAILABLE', 'INTERNAL_ERROR'
                ) THEN RETURN false; END IF;
            WHEN 'state' THEN
                IF jsonb_typeof(entry.item) <> 'string' OR entry.item #>> '{}' NOT IN (
                    'draft', 'active', 'ended', 'superseded', 'pending_clarification', 'collecting',
                    'awaiting_confirmation', 'completed', 'blocked', 'expired'
                ) THEN RETURN false; END IF;
            WHEN 'intake_status' THEN
                IF jsonb_typeof(entry.item) <> 'string' OR entry.item #>> '{}' NOT IN (
                    'reported_taken', 'reported_not_taken', 'unsure', 'not_reported'
                ) THEN RETURN false; END IF;
            WHEN 'visual_status' THEN
                IF entry.item <> '"not_checked"'::jsonb THEN RETURN false; END IF;
            ELSE RETURN false;
        END CASE;
    END LOOP;
    RETURN true;
END;
$$;

CREATE TABLE public.agent_tool_calls (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id) ON DELETE RESTRICT,
    session_id uuid NOT NULL,
    correlation_id uuid NOT NULL,
    tool_name text NOT NULL CHECK (tool_name IN (
        'list_active_medications', 'get_medication_history', 'enroll_medication_draft',
        'confirm_regimen_draft', 'check_due_dose', 'record_self_report'
    )),
    tool_status text NOT NULL CHECK (tool_status IN ('started', 'success', 'failed', 'blocked', 'simulated')),
    request_summary jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (public.core_trace_summary_is_safe(request_summary)),
    response_summary jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (public.core_trace_summary_is_safe(response_summary)),
    source_id uuid,
    regimen_id uuid,
    occurrence_id uuid,
    policy_rule_id text CHECK (policy_rule_id IS NULL OR policy_rule_id IN (
        'SOURCE_REVIEW_REQUIRED', 'COMPLETE_REGIMEN_REQUIRED', 'CURRENT_VERSION_REQUIRED',
        'EXPLICIT_CONFIRMATION_REQUIRED', 'NO_DUPLICATE_EVENT', 'SELF_REPORT_NOT_INGESTION', 'DEMO_ONLY'
    )),
    duration_ms integer CHECK (duration_ms >= 0),
    called_at timestamptz NOT NULL DEFAULT now(),
    demo_only boolean NOT NULL DEFAULT true CHECK (demo_only = true),
    UNIQUE (patient_id, id),
    FOREIGN KEY (patient_id, session_id) REFERENCES public.agent_sessions(patient_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (patient_id, source_id) REFERENCES public.source_documents(patient_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (patient_id, regimen_id) REFERENCES public.regimen_versions(patient_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (patient_id, occurrence_id) REFERENCES public.dose_occurrences(patient_id, id) ON DELETE RESTRICT
);
CREATE INDEX agent_tool_calls_session_idx ON public.agent_tool_calls(patient_id, session_id, called_at);
CREATE INDEX agent_tool_calls_correlation_idx ON public.agent_tool_calls(patient_id, correlation_id);
CREATE INDEX agent_tool_calls_source_idx ON public.agent_tool_calls(patient_id, source_id);
CREATE INDEX agent_tool_calls_regimen_idx ON public.agent_tool_calls(patient_id, regimen_id);
CREATE INDEX agent_tool_calls_occurrence_idx ON public.agent_tool_calls(patient_id, occurrence_id);

CREATE TABLE public.audit_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id) ON DELETE RESTRICT,
    session_id uuid NOT NULL,
    tool_call_id uuid,
    correlation_id uuid NOT NULL,
    actor_type text NOT NULL CHECK (actor_type IN ('patient', 'backend', 'policy')),
    action text NOT NULL CHECK (action IN (
        'draft_created', 'source_reviewed', 'regimen_activated', 'regimen_ended', 'regimen_superseded',
        'self_report_recorded', 'confirmation_issued', 'confirmation_confirmed', 'policy_blocked', 'tool_completed'
    )),
    regimen_id uuid,
    dose_event_id uuid,
    before_redacted jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (public.core_trace_summary_is_safe(before_redacted)),
    after_redacted jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (public.core_trace_summary_is_safe(after_redacted)),
    occurred_at timestamptz NOT NULL DEFAULT now(),
    demo_only boolean NOT NULL DEFAULT true CHECK (demo_only = true),
    UNIQUE (patient_id, id),
    FOREIGN KEY (patient_id, session_id) REFERENCES public.agent_sessions(patient_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (patient_id, tool_call_id) REFERENCES public.agent_tool_calls(patient_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (patient_id, regimen_id) REFERENCES public.regimen_versions(patient_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (patient_id, dose_event_id) REFERENCES public.dose_events(patient_id, id) ON DELETE RESTRICT
);
CREATE INDEX audit_events_time_idx ON public.audit_events(patient_id, occurred_at);
CREATE INDEX audit_events_session_idx ON public.audit_events(patient_id, session_id);
CREATE INDEX audit_events_tool_idx ON public.audit_events(patient_id, tool_call_id);
CREATE INDEX audit_events_regimen_idx ON public.audit_events(patient_id, regimen_id);
CREATE INDEX audit_events_dose_idx ON public.audit_events(patient_id, dose_event_id);

CREATE FUNCTION public.core_validate_timezone() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_timezone_names WHERE name = NEW.timezone) THEN
        RAISE EXCEPTION 'Unsupported IANA timezone';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER patient_profiles_timezone_guard BEFORE INSERT OR UPDATE ON public.patient_profiles
    FOR EACH ROW EXECUTE FUNCTION public.core_validate_timezone();
CREATE TRIGGER dose_rules_timezone_guard BEFORE INSERT OR UPDATE ON public.dose_rules
    FOR EACH ROW EXECUTE FUNCTION public.core_validate_timezone();

CREATE FUNCTION public.core_freeze_reviewed_source() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $$
DECLARE
    parent_status text;
    owner_id uuid;
    document_id uuid;
BEGIN
    IF TG_TABLE_NAME = 'source_fields' THEN
        IF TG_OP = 'DELETE' THEN
            owner_id := OLD.patient_id;
            document_id := OLD.source_id;
        ELSE
            owner_id := NEW.patient_id;
            document_id := NEW.source_id;
            IF TG_OP = 'UPDATE' AND (NEW.patient_id <> OLD.patient_id OR NEW.source_id <> OLD.source_id OR NEW.id <> OLD.id) THEN
                RAISE EXCEPTION 'Source field identity is immutable';
            END IF;
        END IF;
        SELECT review_status INTO parent_status FROM public.source_documents
            WHERE patient_id = owner_id AND id = document_id FOR UPDATE;
        IF NOT FOUND OR parent_status IN ('user_reviewed', 'professional_verified') THEN
            RAISE EXCEPTION 'Cannot alter or append fields of a reviewed source document';
        END IF;
    END IF;
    IF TG_OP <> 'INSERT' AND OLD.review_status IN ('user_reviewed', 'professional_verified') THEN
        RAISE EXCEPTION 'Reviewed source is immutable; create a new source revision';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER source_documents_history_guard BEFORE UPDATE OR DELETE ON public.source_documents
    FOR EACH ROW EXECUTE FUNCTION public.core_freeze_reviewed_source();
CREATE TRIGGER source_fields_history_guard BEFORE INSERT OR UPDATE OR DELETE ON public.source_fields
    FOR EACH ROW EXECUTE FUNCTION public.core_freeze_reviewed_source();

CREATE FUNCTION public.core_consume_confirmation(
    p_patient_id uuid, p_challenge_id uuid, p_action text, p_regimen_id uuid,
    p_occurrence_id uuid, p_intake_status text, p_idempotency_key text
) RETURNS void LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $$
DECLARE
    challenge public.confirmation_challenges%ROWTYPE;
    session_row public.agent_sessions%ROWTYPE;
    consumed_time timestamptz;
BEGIN
    SELECT * INTO challenge FROM public.confirmation_challenges
        WHERE patient_id = p_patient_id AND id = p_challenge_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Confirmation required'; END IF;
    SELECT * INTO session_row FROM public.agent_sessions
        WHERE patient_id = p_patient_id AND id = challenge.session_id FOR UPDATE;
    consumed_time := clock_timestamp();
    IF NOT FOUND OR session_row.state <> 'awaiting_confirmation'
        OR session_row.state_version <> challenge.session_state_version
        OR session_row.expires_at <= consumed_time
        OR challenge.confirmed_at IS NULL OR challenge.confirmed_at > consumed_time
        OR challenge.issued_at > consumed_time OR challenge.expires_at <= consumed_time
        OR challenge.consumed_at IS NOT NULL OR challenge.action <> p_action
        OR challenge.regimen_id <> p_regimen_id
        OR challenge.occurrence_id IS DISTINCT FROM p_occurrence_id
        OR challenge.intended_intake_status IS DISTINCT FROM p_intake_status
        OR (p_idempotency_key IS NOT NULL AND challenge.idempotency_key <> p_idempotency_key) THEN
        RAISE EXCEPTION 'Confirmation expired, consumed, stale or mismatched';
    END IF;
    UPDATE public.confirmation_challenges SET consumed_at = consumed_time
        WHERE patient_id = p_patient_id AND id = p_challenge_id AND consumed_at IS NULL;
END;
$$;

CREATE FUNCTION public.core_guard_challenge() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Confirmation history is retained'; END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.confirmed_at IS NOT NULL OR NEW.consumed_at IS NOT NULL THEN
            RAISE EXCEPTION 'Issue an unconfirmed, unconsumed challenge first';
        END IF;
    ELSE
        IF (to_jsonb(NEW) - ARRAY['confirmed_at', 'consumed_at'])
            IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['confirmed_at', 'consumed_at'])
            OR OLD.consumed_at IS NOT NULL
            OR (OLD.confirmed_at IS NOT NULL AND NEW.confirmed_at IS DISTINCT FROM OLD.confirmed_at)
            OR (NEW.consumed_at IS NOT NULL AND OLD.confirmed_at IS NULL) THEN
            RAISE EXCEPTION 'Challenge binding is immutable and consumption is one-time';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER confirmation_challenges_guard BEFORE INSERT OR UPDATE OR DELETE ON public.confirmation_challenges
    FOR EACH ROW EXECUTE FUNCTION public.core_guard_challenge();

CREATE FUNCTION public.core_guard_regimen() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $$
DECLARE
    medication public.patient_medications%ROWTYPE;
    source_row public.source_documents%ROWTYPE;
    prior public.regimen_versions%ROWTYPE;
    required_field record;
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Regimen history is retained'; END IF;
    IF TG_OP = 'INSERT' AND NEW.state NOT IN ('draft', 'pending_clarification') THEN
        RAISE EXCEPTION 'Create a draft before explicit activation';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF NEW.patient_id <> OLD.patient_id OR NEW.id <> OLD.id
            OR NEW.patient_medication_id <> OLD.patient_medication_id OR NEW.version_no <> OLD.version_no THEN
            RAISE EXCEPTION 'Regimen identity is immutable';
        END IF;
        IF OLD.state IN ('ended', 'superseded') THEN RAISE EXCEPTION 'Historical regimen is immutable'; END IF;
        IF OLD.state = 'active' THEN
            IF NEW.state NOT IN ('ended', 'superseded') OR NEW.effective_to IS NULL
                OR (to_jsonb(NEW) - ARRAY['state', 'effective_to'])
                    IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['state', 'effective_to']) THEN
                RAISE EXCEPTION 'Only retire an active regimen; never overwrite instructions';
            END IF;
            RETURN NEW;
        END IF;
        IF NEW.state NOT IN ('draft', 'pending_clarification', 'active') THEN
            RAISE EXCEPTION 'Only an active regimen can be retired';
        END IF;
    END IF;
    IF NEW.state = 'active' THEN
        SELECT * INTO medication FROM public.patient_medications
            WHERE patient_id = NEW.patient_id AND id = NEW.patient_medication_id FOR UPDATE;
        IF NOT FOUND OR medication.archived_at IS NOT NULL
            OR medication.identity_status NOT IN ('user_reviewed_document', 'professional_verified') THEN
            RAISE EXCEPTION 'Medication is unavailable or identity source is unreviewed';
        END IF;
        SELECT * INTO source_row FROM public.source_documents
            WHERE patient_id = NEW.patient_id AND id = NEW.source_id FOR SHARE;
        IF NOT FOUND OR source_row.review_status NOT IN ('user_reviewed', 'professional_verified')
            OR NEW.source_reviewed_at IS DISTINCT FROM source_row.reviewed_at THEN
            RAISE EXCEPTION 'A reviewed source document is required';
        END IF;
        IF EXISTS (
            SELECT 1 FROM public.source_fields WHERE patient_id = NEW.patient_id AND source_id = NEW.source_id
                AND review_status NOT IN ('user_reviewed', 'professional_verified')
        ) THEN RAISE EXCEPTION 'Every field in the cited source must be reviewed'; END IF;
        IF EXISTS (
            SELECT 1 FROM public.source_fields WHERE patient_id = NEW.patient_id AND source_id = NEW.source_id
                AND field_name = 'is_prn' AND field_value IS DISTINCT FROM to_jsonb(NEW.is_prn)
        ) THEN RAISE EXCEPTION 'PRN flag contradicts reviewed source evidence'; END IF;
        IF NEW.route IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.source_fields WHERE patient_id = NEW.patient_id AND source_id = NEW.source_id
                AND field_name = 'route' AND field_value = to_jsonb(NEW.route)
                AND review_status IN ('user_reviewed', 'professional_verified')
        ) THEN RAISE EXCEPTION 'Route requires matching reviewed source evidence'; END IF;
        IF NEW.food_instruction IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.source_fields WHERE patient_id = NEW.patient_id AND source_id = NEW.source_id
                AND field_name = 'food_instruction' AND field_value = to_jsonb(NEW.food_instruction)
                AND review_status IN ('user_reviewed', 'professional_verified')
        ) THEN RAISE EXCEPTION 'Food instruction requires matching reviewed source evidence'; END IF;
        FOR required_field IN
            SELECT * FROM (VALUES
                (NEW.medication_name_field_id, 'medication_name', to_jsonb(medication.display_name)),
                (NEW.quantity_field_id, 'dose_amount', to_jsonb(NEW.dose_amount)),
                (NEW.unit_field_id, 'dose_unit', to_jsonb(NEW.dose_unit)),
                (CASE WHEN NEW.is_prn THEN NEW.prn_field_id ELSE NEW.frequency_field_id END,
                 CASE WHEN NEW.is_prn THEN 'is_prn' ELSE 'frequency_rule' END,
                 CASE WHEN NEW.is_prn THEN 'true'::jsonb ELSE NEW.frequency_rule END)
            ) AS required(id, name, expected)
        LOOP
            PERFORM 1 FROM public.source_fields
                WHERE patient_id = NEW.patient_id AND source_id = NEW.source_id AND id = required_field.id
                    AND field_name = required_field.name AND field_value = required_field.expected
                    AND review_status IN ('user_reviewed', 'professional_verified') AND reviewed_at IS NOT NULL
                FOR SHARE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Required source field is missing, mismatched or unreviewed'; END IF;
        END LOOP;
        IF NEW.supersedes_id IS NOT NULL THEN
            SELECT * INTO prior FROM public.regimen_versions
                WHERE patient_id = NEW.patient_id AND patient_medication_id = NEW.patient_medication_id
                    AND id = NEW.supersedes_id FOR SHARE;
            IF NOT FOUND OR prior.version_no >= NEW.version_no OR prior.state NOT IN ('ended', 'superseded') THEN
                RAISE EXCEPTION 'Retire the earlier version before activating its successor';
            END IF;
        END IF;
        PERFORM public.core_consume_confirmation(
            NEW.patient_id, NEW.confirmation_challenge_id, 'activate_regimen', NEW.id, NULL, NULL, NULL
        );
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER regimen_versions_guard BEFORE INSERT OR UPDATE OR DELETE ON public.regimen_versions
    FOR EACH ROW EXECUTE FUNCTION public.core_guard_regimen();

CREATE FUNCTION public.core_guard_medication_history() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $$
BEGIN
    PERFORM 1 FROM public.regimen_versions
        WHERE patient_id = OLD.patient_id AND patient_medication_id = OLD.id
            AND state IN ('active', 'ended', 'superseded');
    IF FOUND THEN
        IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Medication history is retained'; END IF;
        IF (to_jsonb(NEW) - 'archived_at') IS DISTINCT FROM (to_jsonb(OLD) - 'archived_at') THEN
            RAISE EXCEPTION 'Medication identity with regimen history is immutable';
        END IF;
        IF NEW.archived_at IS NOT NULL AND EXISTS (
            SELECT 1 FROM public.regimen_versions
            WHERE patient_id = OLD.patient_id AND patient_medication_id = OLD.id AND state = 'active'
        ) THEN RAISE EXCEPTION 'Retire the active regimen before archiving'; END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER patient_medications_history_guard BEFORE UPDATE OR DELETE ON public.patient_medications
    FOR EACH ROW EXECUTE FUNCTION public.core_guard_medication_history();

CREATE FUNCTION public.core_guard_rule() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $$
DECLARE
    regimen public.regimen_versions%ROWTYPE;
    patient_timezone text;
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Dose rule history is retained'; END IF;
    IF TG_OP = 'UPDATE' THEN
        IF (to_jsonb(NEW) - 'enabled') IS DISTINCT FROM (to_jsonb(OLD) - 'enabled') OR NEW.enabled THEN
            RAISE EXCEPTION 'Only disable an existing rule; create a new version for schedule changes';
        END IF;
        RETURN NEW;
    END IF;
    SELECT * INTO regimen FROM public.regimen_versions
        WHERE patient_id = NEW.patient_id AND id = NEW.regimen_id FOR SHARE;
    IF NOT FOUND OR regimen.state NOT IN ('draft', 'pending_clarification', 'active')
        OR (NEW.rule_kind = 'prn') IS DISTINCT FROM regimen.is_prn THEN
        RAISE EXCEPTION 'Rule must agree with a current regimen and its PRN flag';
    END IF;
    SELECT timezone INTO patient_timezone FROM public.patient_profiles WHERE user_id = NEW.patient_id;
    IF NEW.timezone IS DISTINCT FROM patient_timezone THEN RAISE EXCEPTION 'Rule timezone must match patient timezone'; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER dose_rules_guard BEFORE INSERT OR UPDATE OR DELETE ON public.dose_rules
    FOR EACH ROW EXECUTE FUNCTION public.core_guard_rule();

CREATE FUNCTION public.core_guard_occurrence() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $$
DECLARE
    regimen public.regimen_versions%ROWTYPE;
    rule_row public.dose_rules%ROWTYPE;
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Occurrence history is retained'; END IF;
    IF TG_OP = 'UPDATE' THEN
        IF (to_jsonb(NEW) - 'status') IS DISTINCT FROM (to_jsonb(OLD) - 'status')
            OR OLD.status = 'closed' OR (OLD.status = 'past_due' AND NEW.status = 'scheduled') THEN
            RAISE EXCEPTION 'Occurrence identity/time is immutable; status cannot move backwards';
        END IF;
        RETURN NEW;
    END IF;
    SELECT * INTO regimen FROM public.regimen_versions
        WHERE patient_id = NEW.patient_id AND id = NEW.regimen_id FOR SHARE;
    IF NOT FOUND OR regimen.state <> 'active' OR regimen.is_prn
        OR NEW.due_at < regimen.effective_from
        OR (regimen.effective_to IS NOT NULL AND NEW.due_at >= regimen.effective_to) THEN
        RAISE EXCEPTION 'Generate only from an active scheduled regimen within its effective window';
    END IF;
    SELECT * INTO rule_row FROM public.dose_rules
        WHERE patient_id = NEW.patient_id AND regimen_id = NEW.regimen_id AND id = NEW.rule_id FOR SHARE;
    IF NOT FOUND OR rule_row.rule_kind <> 'scheduled' OR NOT rule_row.enabled THEN
        RAISE EXCEPTION 'No inferred PRN occurrence or disabled rule';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER dose_occurrences_guard BEFORE INSERT OR UPDATE OR DELETE ON public.dose_occurrences
    FOR EACH ROW EXECUTE FUNCTION public.core_guard_occurrence();

CREATE FUNCTION public.core_guard_dose_event() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $$
DECLARE
    regimen public.regimen_versions%ROWTYPE;
    medication public.patient_medications%ROWTYPE;
    occurrence public.dose_occurrences%ROWTYPE;
BEGIN
    SELECT * INTO regimen FROM public.regimen_versions
        WHERE patient_id = NEW.patient_id AND id = NEW.regimen_id FOR SHARE;
    IF NOT FOUND OR regimen.state <> 'active' THEN RAISE EXCEPTION 'Current active regimen required'; END IF;
    SELECT * INTO medication FROM public.patient_medications
        WHERE patient_id = NEW.patient_id AND id = regimen.patient_medication_id FOR SHARE;
    IF NOT FOUND OR medication.archived_at IS NOT NULL THEN RAISE EXCEPTION 'Archived or unknown medication'; END IF;
    IF NEW.event_time < regimen.effective_from
        OR (regimen.effective_to IS NOT NULL AND NEW.event_time >= regimen.effective_to) THEN
        RAISE EXCEPTION 'Self-report must be within the regimen effective window';
    END IF;
    IF regimen.is_prn THEN
        IF NEW.occurrence_id IS NOT NULL THEN RAISE EXCEPTION 'PRN self-report has no scheduled occurrence'; END IF;
    ELSE
        SELECT * INTO occurrence FROM public.dose_occurrences
            WHERE patient_id = NEW.patient_id AND regimen_id = NEW.regimen_id AND id = NEW.occurrence_id FOR UPDATE;
        IF NOT FOUND OR occurrence.status = 'closed' THEN RAISE EXCEPTION 'Open scheduled occurrence required'; END IF;
    END IF;
    PERFORM public.core_consume_confirmation(
        NEW.patient_id, NEW.confirmation_challenge_id, 'record_self_report', NEW.regimen_id,
        NEW.occurrence_id, NEW.intake_status, NEW.idempotency_key
    );
    -- reported_taken 仍只是患者自报；不更新 visual_status 或将 ingestion_proven 变为 true。
    RETURN NEW;
END;
$$;
CREATE TRIGGER dose_events_insert_guard BEFORE INSERT ON public.dose_events
    FOR EACH ROW EXECUTE FUNCTION public.core_guard_dose_event();

CREATE FUNCTION public.core_reject_mutation() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $$
BEGIN
    RAISE EXCEPTION 'Append-only history; correction requires a separately audited design';
END;
$$;
CREATE TRIGGER dose_events_history_guard BEFORE UPDATE OR DELETE ON public.dose_events
    FOR EACH ROW EXECUTE FUNCTION public.core_reject_mutation();
CREATE TRIGGER audit_events_history_guard BEFORE UPDATE OR DELETE ON public.audit_events
    FOR EACH ROW EXECUTE FUNCTION public.core_reject_mutation();

CREATE FUNCTION public.core_guard_tool_call() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Tool trace history is retained'; END IF;
    IF OLD.tool_status <> 'started' OR NEW.tool_status = 'started'
        OR (to_jsonb(NEW) - ARRAY['tool_status', 'response_summary', 'duration_ms', 'policy_rule_id'])
            IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['tool_status', 'response_summary', 'duration_ms', 'policy_rule_id']) THEN
        RAISE EXCEPTION 'Only finalize a started tool trace once';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER agent_tool_calls_guard BEFORE UPDATE OR DELETE ON public.agent_tool_calls
    FOR EACH ROW EXECUTE FUNCTION public.core_guard_tool_call();

-- 每个患者表显式 ENABLE/FORCE RLS；复合 FK 在 RLS 之外也约束关联的 patient_id。
ALTER TABLE public.patient_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.patient_profiles FORCE ROW LEVEL SECURITY;
CREATE POLICY patient_profiles_owner ON public.patient_profiles FOR ALL TO authenticated
    USING ((SELECT auth.uid()) = user_id) WITH CHECK ((SELECT auth.uid()) = user_id);
ALTER TABLE public.source_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.source_documents FORCE ROW LEVEL SECURITY;
CREATE POLICY source_documents_owner ON public.source_documents FOR ALL TO authenticated
    USING ((SELECT auth.uid()) = patient_id) WITH CHECK ((SELECT auth.uid()) = patient_id);
ALTER TABLE public.source_fields ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.source_fields FORCE ROW LEVEL SECURITY;
CREATE POLICY source_fields_owner ON public.source_fields FOR ALL TO authenticated
    USING ((SELECT auth.uid()) = patient_id) WITH CHECK ((SELECT auth.uid()) = patient_id);
ALTER TABLE public.patient_medications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.patient_medications FORCE ROW LEVEL SECURITY;
CREATE POLICY patient_medications_owner ON public.patient_medications FOR ALL TO authenticated
    USING ((SELECT auth.uid()) = patient_id) WITH CHECK ((SELECT auth.uid()) = patient_id);
ALTER TABLE public.regimen_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.regimen_versions FORCE ROW LEVEL SECURITY;
CREATE POLICY regimen_versions_owner ON public.regimen_versions FOR ALL TO authenticated
    USING ((SELECT auth.uid()) = patient_id) WITH CHECK ((SELECT auth.uid()) = patient_id);
ALTER TABLE public.dose_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.dose_rules FORCE ROW LEVEL SECURITY;
CREATE POLICY dose_rules_owner ON public.dose_rules FOR ALL TO authenticated
    USING ((SELECT auth.uid()) = patient_id) WITH CHECK ((SELECT auth.uid()) = patient_id);
ALTER TABLE public.dose_occurrences ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.dose_occurrences FORCE ROW LEVEL SECURITY;
CREATE POLICY dose_occurrences_owner ON public.dose_occurrences FOR ALL TO authenticated
    USING ((SELECT auth.uid()) = patient_id) WITH CHECK ((SELECT auth.uid()) = patient_id);
ALTER TABLE public.dose_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.dose_events FORCE ROW LEVEL SECURITY;
CREATE POLICY dose_events_owner ON public.dose_events FOR ALL TO authenticated
    USING ((SELECT auth.uid()) = patient_id) WITH CHECK ((SELECT auth.uid()) = patient_id);
ALTER TABLE public.agent_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_sessions FORCE ROW LEVEL SECURITY;
CREATE POLICY agent_sessions_owner ON public.agent_sessions FOR ALL TO authenticated
    USING ((SELECT auth.uid()) = patient_id) WITH CHECK ((SELECT auth.uid()) = patient_id);
ALTER TABLE public.confirmation_challenges ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.confirmation_challenges FORCE ROW LEVEL SECURITY;
CREATE POLICY confirmation_challenges_owner ON public.confirmation_challenges FOR ALL TO authenticated
    USING ((SELECT auth.uid()) = patient_id) WITH CHECK ((SELECT auth.uid()) = patient_id);
ALTER TABLE public.agent_tool_calls ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_tool_calls FORCE ROW LEVEL SECURITY;
CREATE POLICY agent_tool_calls_owner ON public.agent_tool_calls FOR ALL TO authenticated
    USING ((SELECT auth.uid()) = patient_id) WITH CHECK ((SELECT auth.uid()) = patient_id);
ALTER TABLE public.audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_events FORCE ROW LEVEL SECURITY;
CREATE POLICY audit_events_owner ON public.audit_events FOR ALL TO authenticated
    USING ((SELECT auth.uid()) = patient_id) WITH CHECK ((SELECT auth.uid()) = patient_id);
ALTER TABLE public.medication_products ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.medication_products FORCE ROW LEVEL SECURITY;
CREATE POLICY medication_products_demo_read ON public.medication_products FOR SELECT TO authenticated
    USING (demo_only = true);

REVOKE ALL ON TABLE public.patient_profiles, public.medication_products, public.source_documents,
    public.source_fields, public.patient_medications, public.regimen_versions, public.dose_rules,
    public.dose_occurrences, public.dose_events, public.agent_sessions, public.confirmation_challenges,
    public.agent_tool_calls, public.audit_events FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON TABLE public.patient_profiles, public.medication_products, public.source_documents,
    public.source_fields, public.patient_medications, public.regimen_versions, public.dose_rules,
    public.dose_occurrences, public.dose_events, public.agent_sessions, public.confirmation_challenges,
    public.agent_tool_calls, public.audit_events TO authenticated;
GRANT SELECT ON TABLE public.medication_products TO service_role;
GRANT SELECT, INSERT, UPDATE ON TABLE public.patient_profiles, public.source_documents, public.source_fields,
    public.patient_medications, public.regimen_versions, public.dose_rules, public.dose_occurrences,
    public.agent_sessions, public.confirmation_challenges, public.agent_tool_calls TO service_role;
GRANT SELECT, INSERT ON TABLE public.dose_events, public.audit_events TO service_role;

-- Supabase 默认函数权限不能成为 PostgREST 中可直接调用的确认/写入 RPC。
REVOKE ALL ON FUNCTION public.core_trace_summary_is_safe(jsonb), public.core_validate_timezone(),
    public.core_freeze_reviewed_source(), public.core_consume_confirmation(uuid, uuid, text, uuid, uuid, text, text),
    public.core_guard_challenge(), public.core_guard_regimen(), public.core_guard_medication_history(),
    public.core_guard_rule(), public.core_guard_occurrence(), public.core_guard_dose_event(),
    public.core_reject_mutation(), public.core_guard_tool_call() FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.core_trace_summary_is_safe(jsonb) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.core_validate_timezone(), public.core_freeze_reviewed_source(),
    public.core_consume_confirmation(uuid, uuid, text, uuid, uuid, text, text), public.core_guard_challenge(),
    public.core_guard_regimen(), public.core_guard_medication_history(), public.core_guard_rule(),
    public.core_guard_occurrence(), public.core_guard_dose_event(), public.core_reject_mutation(),
    public.core_guard_tool_call() TO service_role;

-- 应用事务：锁定药品/版本，退役旧版，激活新版，关闭旧版未来 occurrence，再生成新版。
-- 重试先查询 (patient_id, idempotency_key)，比较请求绑定，不重复消耗确认挑战。
-- DST 的间隙/重叠、frequency_rule 的具体排程及规范化 generation_key 由确定性应用服务验证。
-- SQL 不填充患者 fixture，不调用 Agent、LLM、远程服务，也不隐式记录任何服药结果。
COMMIT;
