-- Gate1 corrective migration (Session 3B).
--
-- WHY THIS FILE EXISTS
-- --------------------
-- Applying 202610130001_core.sql to the real development database and then
-- exercising the real Postgres adapter proved that three allowlists in the
-- core migration are INCOMPLETE: they omit values the application already
-- produces through its public, allowlisted interfaces. Each omission turns a
-- legitimate, non-identifying write into a constraint violation, so the
-- schema — not the application — was wrong. This migration completes them.
--
-- This is a completeness fix, never a relaxation:
--   * no value is removed and no domain is broadened beyond the application's
--     own closed enums (contracts/enums.py mirrors these lists);
--   * free text is still impossible — every accepted key remains an
--     allowlisted scalar, and the 1024-byte bound is unchanged;
--   * the P0 photo rule is untouched: visual_status may still only be
--     'not_checked';
--   * no table, column, policy, grant or trigger is added, dropped or altered.
--
-- Defect 1 — agent_tool_calls.tool_name omitted 'get_dose_status'
--   ToolName.GET_DOSE_STATUS is a registered, read-only allowlisted tool
--   ("Have I taken my Amlodipine today?"). It writes no dose event. Recording
--   its trace violated the CHECK, so every such turn failed to audit.
--
-- Defect 2 — agent_sessions.intent omitted 'dose_status_query'
--   AgentIntent.DOSE_STATUS_QUERY is produced by the deterministic router for
--   the same read-only question, so the session row could not be updated.
--
-- Defect 3 — core_trace_summary_is_safe rejected three legitimate values
--   a. 'already_recorded' (boolean) — whether an idempotent replay returned an
--      existing event instead of writing a second one. A boolean, not PII.
--   b. 'missing_count' (count) — how many required dose instructions are still
--      absent. A count, not content; it carries no medication or dose detail.
--   c. intake_status = 'no_report' — the read-only answer "nothing has been
--      reported for this dose". It is deliberately NOT one of the four
--      self-report statuses and must never be stored as one, so it is admitted
--      only as an answer marker and the four real statuses are unchanged.
--   Every other key and value domain is exactly as before.
--
-- Rollback: supabase/rollback/202610130002_agent_enum_gaps_down.sql
BEGIN;
SET LOCAL TIME ZONE 'UTC';
SET LOCAL search_path = pg_catalog, public;

-- Defect 1 -------------------------------------------------------------------
ALTER TABLE public.agent_tool_calls
    DROP CONSTRAINT agent_tool_calls_tool_name_check;
ALTER TABLE public.agent_tool_calls
    ADD CONSTRAINT agent_tool_calls_tool_name_check CHECK (tool_name IN (
        'list_active_medications', 'get_medication_history', 'get_dose_status',
        'enroll_medication_draft', 'confirm_regimen_draft', 'check_due_dose',
        'record_self_report'
    ));

-- Defect 2 -------------------------------------------------------------------
ALTER TABLE public.agent_sessions
    DROP CONSTRAINT agent_sessions_intent_check;
ALTER TABLE public.agent_sessions
    ADD CONSTRAINT agent_sessions_intent_check CHECK (intent IN (
        'medication_enrollment', 'dose_self_report', 'dose_status_query',
        'medication_history', 'clarification'
    ));

-- Defect 3 -------------------------------------------------------------------
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
            WHEN 'missing_count' THEN
                IF jsonb_typeof(entry.item) <> 'number' OR entry.item::text !~ '^[0-9]{1,7}$' THEN RETURN false; END IF;
            WHEN 'demo_only' THEN
                IF jsonb_typeof(entry.item) <> 'boolean' OR entry.item <> 'true'::jsonb THEN RETURN false; END IF;
            WHEN 'already_recorded' THEN
                IF jsonb_typeof(entry.item) <> 'boolean' THEN RETURN false; END IF;
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
                -- The four self-report statuses plus the read-only "nothing
                -- reported yet" answer marker. 'no_report' is never written to
                -- dose_events.intake_status, whose CHECK is untouched.
                IF jsonb_typeof(entry.item) <> 'string' OR entry.item #>> '{}' NOT IN (
                    'reported_taken', 'reported_not_taken', 'unsure', 'not_reported', 'no_report'
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
