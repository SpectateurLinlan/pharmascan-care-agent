-- Rollback for 202610130004_patient_rls_role.sql.
--
-- Removes the dedicated patient role and every privilege this migration
-- granted. It does NOT restore the ``core_schema_migrations`` grants to
-- ``anon``/``authenticated``: re-opening that hole is a downgrade, not a
-- rollback, and the forward migration records it as a defect fix. If a future
-- environment genuinely needs the ledger exposed again, that must be an
-- explicit, separately reviewed decision.
BEGIN;
SET LOCAL TIME ZONE 'UTC';
SET LOCAL search_path = pg_catalog, public;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pharmascan_patient') THEN
        EXECUTE 'REVOKE ALL ON TABLE public.medication_products, public.audit_events, '
                'public.dose_events, public.patient_profiles, public.source_documents, '
                'public.source_fields, public.patient_medications, public.regimen_versions, '
                'public.dose_rules, public.dose_occurrences, public.agent_sessions, '
                'public.confirmation_challenges, public.agent_tool_calls '
                'FROM pharmascan_patient';

        EXECUTE 'REVOKE ALL ON FUNCTION public.core_trace_summary_is_safe(jsonb), '
                'public.core_validate_timezone(), public.core_freeze_reviewed_source(), '
                'public.core_consume_confirmation(uuid, uuid, text, uuid, uuid, text, text), '
                'public.core_guard_challenge(), public.core_guard_regimen(), '
                'public.core_guard_medication_history(), public.core_guard_rule(), '
                'public.core_guard_occurrence(), public.core_guard_dose_event(), '
                'public.core_reject_mutation(), public.core_guard_tool_call() '
                'FROM pharmascan_patient';

        EXECUTE 'REVOKE USAGE ON SCHEMA public FROM pharmascan_patient';
        EXECUTE 'REVOKE authenticated FROM pharmascan_patient';
        EXECUTE format('REVOKE pharmascan_patient FROM %I', current_user);
        EXECUTE 'DROP ROLE pharmascan_patient';
    END IF;
END;
$$;

COMMIT;
