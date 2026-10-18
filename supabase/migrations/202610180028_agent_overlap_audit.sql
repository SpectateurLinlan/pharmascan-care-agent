-- Correctness 01 / BUG-06. Add only the existing application REGIMEN_OVERLAP code.
-- No tables, grants, RLS, triggers, history or byte limits change.
-- Production execution requires separate owner approval.
BEGIN;
SET LOCAL search_path = pg_catalog, public;
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
                    'POLICY_BLOCKED', 'INVALID_INPUT', 'PROVIDER_UNAVAILABLE', 'INTERNAL_ERROR', 'REGIMEN_OVERLAP'
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

COMMIT;
