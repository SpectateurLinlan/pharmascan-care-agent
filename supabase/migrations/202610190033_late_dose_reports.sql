-- Separate append-only patient statements; no mutation of original dose events.
BEGIN;
CREATE TABLE public.dose_report_entries(
 patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id), id uuid NOT NULL,
 occurrence_id uuid NOT NULL, regimen_id uuid NOT NULL,
 intake_status text NOT NULL CHECK(intake_status IN ('reported_taken','reported_not_taken','unsure')),
 actual_administration_at timestamptz,
 reason text NOT NULL CHECK(reason IN ('forgot_to_record','app_unavailable','unsure_time','correcting_record','other')),
 notes text NOT NULL DEFAULT '' CHECK(length(notes)<=1000), expected_report_id uuid,
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(), version integer NOT NULL CHECK(version BETWEEN 1 AND 100),
 idempotency_key text NOT NULL, ingestion_proven boolean NOT NULL DEFAULT false CHECK(NOT ingestion_proven),
 visual_status text NOT NULL DEFAULT 'not_checked' CHECK(visual_status='not_checked'),
 PRIMARY KEY(patient_id,id), UNIQUE(patient_id,occurrence_id,version), UNIQUE(patient_id,idempotency_key),
 FOREIGN KEY(patient_id,occurrence_id) REFERENCES public.dose_occurrences(patient_id,id),
 FOREIGN KEY(patient_id,regimen_id) REFERENCES public.regimen_versions(patient_id,id),
 CHECK(actual_administration_at IS NULL OR (intake_status='reported_taken' AND date_trunc('second',actual_administration_at)=actual_administration_at))
);
ALTER TABLE public.dose_report_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.dose_report_entries FORCE ROW LEVEL SECURITY;
CREATE POLICY dose_report_entries_owner ON public.dose_report_entries FOR SELECT TO authenticated
 USING(patient_id=(SELECT auth.uid()));
REVOKE ALL ON public.dose_report_entries FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT ON public.dose_report_entries TO authenticated;
CREATE TRIGGER dose_report_entries_immutable BEFORE UPDATE OR DELETE ON public.dose_report_entries
 FOR EACH ROW EXECUTE FUNCTION public.core_reject_mutation();
CREATE VIEW public.effective_dose_events WITH(security_invoker=true) AS
 SELECT e.id,e.patient_id,e.regimen_id,e.occurrence_id,e.event_time,e.intake_status,e.visual_status,
 e.ingestion_proven,e.idempotency_key,e.created_at,false AS reported_late,NULL::timestamptz AS actual_administration_at
 FROM public.dose_events e WHERE NOT EXISTS(SELECT 1 FROM public.dose_report_entries x
  WHERE x.patient_id=e.patient_id AND x.occurrence_id=e.occurrence_id)
 UNION ALL
 SELECT r.id,r.patient_id,r.regimen_id,r.occurrence_id,r.recorded_at,r.intake_status,r.visual_status,
 r.ingestion_proven,r.idempotency_key,r.recorded_at,true,r.actual_administration_at
 FROM public.dose_report_entries r WHERE NOT EXISTS(SELECT 1 FROM public.dose_report_entries later
  WHERE later.patient_id=r.patient_id AND later.occurrence_id=r.occurrence_id AND later.version>r.version);
REVOKE ALL ON public.effective_dose_events FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT ON public.effective_dose_events TO authenticated;
-- Serialize the original reporting path against corrections as well. No guard is relaxed.
CREATE FUNCTION public.guard_original_after_late_report() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
BEGIN
 IF NEW.occurrence_id IS NOT NULL THEN
  PERFORM 1 FROM public.dose_occurrences WHERE patient_id=NEW.patient_id AND id=NEW.occurrence_id FOR UPDATE;
  IF EXISTS(SELECT 1 FROM public.dose_report_entries WHERE patient_id=NEW.patient_id AND occurrence_id=NEW.occurrence_id)
  THEN RAISE EXCEPTION 'Use a confirmed correction for this occurrence' USING ERRCODE='22023'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER zz_original_after_late_report BEFORE INSERT ON public.dose_events
 FOR EACH ROW EXECUTE FUNCTION public.guard_original_after_late_report();
REVOKE ALL ON FUNCTION public.guard_original_after_late_report() FROM PUBLIC,anon,service_role;
CREATE FUNCTION public.record_late_dose_report(p_occurrence_id uuid,p_values jsonb,p_challenge_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE owner_id uuid:=auth.uid(); occurrence public.dose_occurrences; plan public.regimen_versions;
 medicine public.patient_medications; result public.dose_report_entries; current_id uuid; current_version int:=0;
 status text:=p_values->>'intake_status'; actual timestamptz:=(p_values->>'actual_administration_at')::timestamptz;
 expected uuid:=(p_values->>'expected_report_id')::uuid; key text; canonical text; zone text; challenge public.confirmation_challenges;
BEGIN
 IF owner_id IS NULL THEN RAISE EXCEPTION 'Authentication required' USING ERRCODE='42501'; END IF;
 canonical:=concat_ws(E'\n',p_occurrence_id::text,p_values->>'id',status,
  CASE WHEN actual IS NULL THEN '' ELSE extract(epoch FROM actual)::bigint::text END,
  p_values->>'reason',coalesce(expected::text,''),coalesce(p_values->>'notes',''));
 key:='late:'||(p_values->>'id')||':'||encode(sha256(convert_to(canonical,'UTF8')),'hex');
 SELECT * INTO result FROM public.dose_report_entries WHERE patient_id=owner_id AND id=(p_values->>'id')::uuid;
 IF FOUND THEN
  IF result.idempotency_key<>key THEN RAISE EXCEPTION 'Report key reused' USING ERRCODE='22023'; END IF;
  RETURN to_jsonb(result);
 END IF;
 SELECT * INTO occurrence FROM public.dose_occurrences WHERE patient_id=owner_id AND id=p_occurrence_id FOR UPDATE;
 IF NOT FOUND OR occurrence.due_at>now() OR occurrence.due_at<now()-interval '7 days'
 THEN RAISE EXCEPTION 'Choose existing past occurrence within seven days' USING ERRCODE='22023'; END IF;
 SELECT * INTO plan FROM public.regimen_versions WHERE patient_id=owner_id AND id=occurrence.regimen_id FOR SHARE;
 SELECT * INTO medicine FROM public.patient_medications WHERE patient_id=owner_id AND id=plan.patient_medication_id FOR SHARE;
 SELECT timezone INTO zone FROM public.patient_profiles WHERE user_id=owner_id;
 IF plan.is_prn OR plan.state IN ('draft','pending_clarification') OR plan.effective_from IS NULL
  OR occurrence.due_at<plan.effective_from OR (plan.effective_to IS NOT NULL AND occurrence.due_at>=plan.effective_to)
  OR (plan.course_start_date IS NOT NULL AND (occurrence.due_at AT TIME ZONE zone)::date<plan.course_start_date)
  OR (plan.course_end_date IS NOT NULL AND (occurrence.due_at AT TIME ZONE zone)::date>plan.course_end_date)
  OR medicine.identity_status NOT IN ('user_reviewed_document','professional_verified')
  OR NOT EXISTS(SELECT 1 FROM public.source_documents WHERE patient_id=owner_id AND id=plan.source_id
    AND review_status IN ('user_reviewed','professional_verified'))
 THEN RAISE EXCEPTION 'Reviewed applicable historical plan required' USING ERRCODE='22023'; END IF;
 IF actual IS NOT NULL AND (status<>'reported_taken' OR actual>now() OR actual<now()-interval '7 days'
  OR actual<plan.effective_from OR (plan.effective_to IS NOT NULL AND actual>=plan.effective_to)
  OR (plan.course_start_date IS NOT NULL AND (actual AT TIME ZONE zone)::date<plan.course_start_date)
  OR (plan.course_end_date IS NOT NULL AND (actual AT TIME ZONE zone)::date>plan.course_end_date))
 THEN RAISE EXCEPTION 'Invalid actual administration time' USING ERRCODE='22023'; END IF;
 SELECT id,version INTO current_id,current_version FROM public.dose_report_entries
  WHERE patient_id=owner_id AND occurrence_id=p_occurrence_id ORDER BY version DESC LIMIT 1;
 IF current_id IS NULL THEN SELECT id INTO current_id FROM public.dose_events WHERE patient_id=owner_id AND occurrence_id=p_occurrence_id; END IF;
 IF current_id IS DISTINCT FROM expected THEN RAISE EXCEPTION 'Report changed; reload before correcting' USING ERRCODE='22023'; END IF;
 -- Existing single-use, session/version-bound confirmation mechanism; not a boolean bypass.
 PERFORM pharmascan_private.core_consume_confirmation(owner_id,p_challenge_id,'record_self_report',plan.id,p_occurrence_id,status,key);
 INSERT INTO public.dose_report_entries(patient_id,id,occurrence_id,regimen_id,intake_status,actual_administration_at,
  reason,notes,expected_report_id,version,idempotency_key)
 VALUES(owner_id,(p_values->>'id')::uuid,p_occurrence_id,plan.id,status,actual,p_values->>'reason',
  coalesce(p_values->>'notes',''),expected,coalesce(current_version,0)+1,key) RETURNING * INTO result;
 UPDATE public.dose_occurrences d SET status='closed' WHERE d.patient_id=owner_id AND d.id=p_occurrence_id AND d.status<>'closed';
 SELECT * INTO challenge FROM public.confirmation_challenges WHERE patient_id=owner_id AND id=p_challenge_id;
 INSERT INTO public.audit_events(patient_id,session_id,correlation_id,actor_type,action,regimen_id)
 VALUES(owner_id,challenge.session_id,result.id,'patient','self_report_recorded',plan.id);
 RETURN to_jsonb(result);
END $$;
REVOKE ALL ON FUNCTION public.record_late_dose_report(uuid,jsonb,uuid) FROM PUBLIC,anon,service_role;
GRANT EXECUTE ON FUNCTION public.record_late_dose_report(uuid,jsonb,uuid) TO authenticated;
NOTIFY pgrst,'reload schema';
COMMIT;
