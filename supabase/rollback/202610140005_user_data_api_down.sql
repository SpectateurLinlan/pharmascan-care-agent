BEGIN;
DROP FUNCTION public.record_confirmed_self_report(jsonb);
REVOKE INSERT, UPDATE ON public.patient_profiles, public.source_documents, public.source_fields,
    public.regimen_versions, public.dose_rules, public.dose_occurrences,
    public.agent_sessions, public.confirmation_challenges, public.agent_tool_calls FROM authenticated;
REVOKE INSERT, UPDATE, DELETE ON public.patient_medications FROM authenticated;
REVOKE INSERT ON public.dose_events FROM authenticated;
REVOKE EXECUTE ON FUNCTION pharmascan_private.core_consume_confirmation(uuid, uuid, text, uuid, uuid, text, text)
    FROM authenticated;
ALTER FUNCTION pharmascan_private.core_consume_confirmation(uuid, uuid, text, uuid, uuid, text, text)
    SET SCHEMA public;
DO $$
DECLARE definition text; routine regprocedure;
BEGIN
    FOREACH routine IN ARRAY ARRAY['public.core_guard_regimen()'::regprocedure,
                                   'public.core_guard_dose_event()'::regprocedure] LOOP
        SELECT pg_get_functiondef(routine) INTO definition;
        EXECUTE replace(definition, 'pharmascan_private.core_consume_confirmation(',
                        'public.core_consume_confirmation(');
    END LOOP;
END;
$$;
REVOKE USAGE ON SCHEMA pharmascan_private FROM authenticated, service_role, pharmascan_patient;
-- Do not drop the schema: a later migration may own objects in it.
NOTIFY pgrst, 'reload schema';
COMMIT;
