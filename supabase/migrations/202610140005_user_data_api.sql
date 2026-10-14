-- User JWT Data API access. Preserve every core guard and owner policy.
-- The confirmation helper is moved outside the exposed public schema so it
-- can run from INVOKER triggers without becoming a callable consumption RPC.
BEGIN;
CREATE SCHEMA IF NOT EXISTS pharmascan_private;
REVOKE ALL ON SCHEMA pharmascan_private FROM PUBLIC, anon;
GRANT USAGE ON SCHEMA pharmascan_private TO authenticated, service_role, pharmascan_patient;
ALTER FUNCTION public.core_consume_confirmation(uuid, uuid, text, uuid, uuid, text, text)
    SET SCHEMA pharmascan_private;
GRANT EXECUTE ON FUNCTION pharmascan_private.core_consume_confirmation(uuid, uuid, text, uuid, uuid, text, text)
    TO authenticated;
DO $$
DECLARE definition text; routine regprocedure;
BEGIN
    FOREACH routine IN ARRAY ARRAY['public.core_guard_regimen()'::regprocedure,
                                   'public.core_guard_dose_event()'::regprocedure] LOOP
        SELECT pg_get_functiondef(routine) INTO definition;
        EXECUTE replace(definition, 'public.core_consume_confirmation(',
                        'pharmascan_private.core_consume_confirmation(');
    END LOOP;
END;
$$;
GRANT INSERT, UPDATE ON public.patient_profiles, public.source_documents, public.source_fields,
    public.regimen_versions, public.dose_rules, public.dose_occurrences,
    public.agent_sessions, public.confirmation_challenges, public.agent_tool_calls TO authenticated;
GRANT INSERT, UPDATE, DELETE ON public.patient_medications TO authenticated;
GRANT INSERT ON public.dose_events TO authenticated;

-- Safe public application operation: identity is auth.uid(), no arbitrary SQL,
-- existing trigger checks bindings and atomically consumes the challenge.
CREATE FUNCTION public.record_confirmed_self_report(p_event jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $$
DECLARE existing public.dose_events%ROWTYPE; inserted public.dose_events%ROWTYPE;
BEGIN
    IF auth.uid() IS NULL OR (p_event->>'patient_id')::uuid IS DISTINCT FROM auth.uid() THEN
        RAISE EXCEPTION 'Authenticated owner required';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(auth.uid()::text || ':' || (p_event->>'idempotency_key'), 0));
    SELECT * INTO existing FROM public.dose_events
        WHERE patient_id = auth.uid() AND idempotency_key = p_event->>'idempotency_key';
    IF FOUND THEN
        IF existing.regimen_id IS DISTINCT FROM (p_event->>'regimen_id')::uuid
           OR existing.occurrence_id IS DISTINCT FROM (p_event->>'occurrence_id')::uuid
           OR existing.intake_status IS DISTINCT FROM p_event->>'intake_status' THEN
            RAISE EXCEPTION 'Idempotency binding conflict';
        END IF;
        RETURN to_jsonb(existing);
    END IF;
    INSERT INTO public.dose_events(id, patient_id, regimen_id, occurrence_id, confirmation_challenge_id,
        event_time, intake_status, visual_status, evidence_method, ingestion_proven, idempotency_key, demo_only)
    VALUES ((p_event->>'id')::uuid, auth.uid(), (p_event->>'regimen_id')::uuid,
        (p_event->>'occurrence_id')::uuid, (p_event->>'confirmation_challenge_id')::uuid,
        (p_event->>'event_time')::timestamptz, p_event->>'intake_status', 'not_checked',
        'self_report', false, p_event->>'idempotency_key', true) RETURNING * INTO inserted;
    UPDATE public.dose_occurrences SET status = 'closed'
        WHERE patient_id = auth.uid() AND id = inserted.occurrence_id;
    RETURN to_jsonb(inserted);
END;
$$;
REVOKE ALL ON FUNCTION public.record_confirmed_self_report(jsonb) FROM PUBLIC, anon, service_role;
GRANT EXECUTE ON FUNCTION public.record_confirmed_self_report(jsonb) TO authenticated;
NOTIFY pgrst, 'reload schema';
COMMIT;
