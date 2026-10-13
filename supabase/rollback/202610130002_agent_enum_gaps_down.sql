-- Rollback for 202610130002_agent_enum_gaps.sql.
--
-- Restores the exact constraint/function definitions from
-- 202610130001_core.sql. Only run this after confirming that no row depends on
-- the widened allowlists (a rollback fails loudly rather than silently
-- truncating data, because ADD CONSTRAINT validates existing rows).
BEGIN;
SET LOCAL TIME ZONE 'UTC';
SET LOCAL search_path = pg_catalog, public;

ALTER TABLE public.agent_tool_calls
    DROP CONSTRAINT agent_tool_calls_tool_name_check;
ALTER TABLE public.agent_tool_calls
    ADD CONSTRAINT agent_tool_calls_tool_name_check CHECK (tool_name IN (
        'list_active_medications', 'get_medication_history', 'enroll_medication_draft',
        'confirm_regimen_draft', 'check_due_dose', 'record_self_report'
    ));

ALTER TABLE public.agent_sessions
    DROP CONSTRAINT agent_sessions_intent_check;
ALTER TABLE public.agent_sessions
    ADD CONSTRAINT agent_sessions_intent_check CHECK (intent IN (
        'medication_enrollment', 'dose_self_report', 'medication_history', 'clarification'
    ));

CREATE OR REPLACE FUNCTION public.core_trace_summary_is_safe(p_summary jsonb) RETURNS boolean
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

REVOKE ALL ON FUNCTION public.core_trace_summary_is_safe(jsonb) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.core_trace_summary_is_safe(jsonb) TO authenticated, service_role;

COMMIT;
