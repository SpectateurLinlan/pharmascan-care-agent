-- REVIEW ONLY / NOT APPLIED. Requires035/036 and I02-I08 review candidates.
-- No target provisioning, historical dose reconstruction, providers or Storage.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';

CREATE TABLE public.assistant_record_commands (
 owner uuid NOT NULL REFERENCES public.patient_profiles(user_id),action_key uuid NOT NULL,
 task_id uuid NOT NULL,binding_revision integer NOT NULL CHECK(binding_revision>0),
 capability_id text NOT NULL CHECK(capability_id IN ('dose.report','dose.prn.report','dose.late.review','dose.correction.review')),
 kind text NOT NULL CHECK(kind IN ('prepare_review','prepare_report','prepare_late_report','self_report','prn_report','late_report','correction')),
 command_digest text NOT NULL CHECK(command_digest ~ '^[a-f0-9]{64}$'),
 prepared_ref jsonb NOT NULL CHECK(public.assistant_wf_keys(prepared_ref,ARRAY['kind','id','version'])),
 operation_key uuid NOT NULL,native_id uuid,state text NOT NULL CHECK(state IN ('pending','applied')),
 PRIMARY KEY(owner,action_key),
 FOREIGN KEY(owner,action_key) REFERENCES public.assistant_business_receipts(owner,action_key) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX assistant_record_challenge_binding ON public.assistant_record_commands(owner,native_id)
 WHERE kind IN ('prepare_report','prepare_late_report');
ALTER TABLE public.assistant_record_commands OWNER TO assistant_workflow_owner;
ALTER TABLE public.assistant_record_commands ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assistant_record_commands FORCE ROW LEVEL SECURITY;
CREATE POLICY assistant_record_command_owner ON public.assistant_record_commands TO assistant_workflow_owner
 USING(owner=public.assistant_patient_uid()) WITH CHECK(owner=public.assistant_patient_uid());
REVOKE ALL ON public.assistant_record_commands FROM PUBLIC,anon,authenticated,service_role,
 assistant_evidence_login,assistant_evidence_owner;

GRANT SELECT,INSERT ON public.dose_events,public.audit_events TO assistant_workflow_owner;
GRANT SELECT,UPDATE ON public.dose_occurrences TO assistant_workflow_owner;
GRANT SELECT ON public.dose_report_entries,public.effective_dose_events TO assistant_workflow_owner;
CREATE POLICY assistant_record_event_owner ON public.dose_events TO assistant_workflow_owner
 USING(patient_id=public.assistant_patient_uid()) WITH CHECK(patient_id=public.assistant_patient_uid());
CREATE POLICY assistant_record_audit_owner ON public.audit_events TO assistant_workflow_owner
 USING(patient_id=public.assistant_patient_uid()) WITH CHECK(patient_id=public.assistant_patient_uid());
CREATE POLICY assistant_record_occurrence_owner ON public.dose_occurrences TO assistant_workflow_owner
 USING(patient_id=public.assistant_patient_uid()) WITH CHECK(patient_id=public.assistant_patient_uid());
CREATE POLICY assistant_record_history_owner ON public.dose_report_entries FOR SELECT TO assistant_workflow_owner
 USING(patient_id=public.assistant_patient_uid());
-- The normal fixed domain owner can invoke the existing consumption helper.
-- Neither restricted verification identity gets schema/function/clinical access.
GRANT USAGE ON SCHEMA pharmascan_private TO assistant_workflow_owner;
GRANT EXECUTE ON FUNCTION pharmascan_private.core_consume_confirmation(uuid,uuid,text,uuid,uuid,text,text)
 TO assistant_workflow_owner;

CREATE TRIGGER assistant_record_event_owner_first BEFORE INSERT ON public.dose_events
 FOR EACH STATEMENT EXECUTE FUNCTION public.assistant_medication_owner_fence();
CREATE TRIGGER assistant_record_occurrence_owner_first BEFORE INSERT OR UPDATE OR DELETE ON public.dose_occurrences
 FOR EACH STATEMENT EXECUTE FUNCTION public.assistant_medication_owner_fence();
CREATE TRIGGER assistant_record_history_owner_first BEFORE INSERT ON public.dose_report_entries
 FOR EACH STATEMENT EXECUTE FUNCTION public.assistant_medication_owner_fence();

CREATE FUNCTION public.assistant_record_digest(p_command jsonb) RETURNS text
LANGUAGE sql IMMUTABLE SECURITY INVOKER SET search_path='' AS $$
 SELECT encode(sha256(convert_to(CASE WHEN p_command->>'kind' IN ('self_report','prn_report')
 THEN p_command #- ARRAY['values','event_time'] ELSE p_command END::text,'UTF8')),'hex')
$$;
ALTER FUNCTION public.assistant_record_digest(jsonb) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_record_digest(jsonb)
 FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;

CREATE FUNCTION public.assistant_record_late_key(p_occurrence uuid,p_values jsonb) RETURNS text
LANGUAGE sql IMMUTABLE SECURITY INVOKER SET search_path='' AS $$
 SELECT 'late:'||(p_values->>'id')||':'||encode(sha256(convert_to(concat_ws(E'\n',p_occurrence::text,
 p_values->>'id',p_values->>'intake_status',CASE WHEN p_values->>'actual_administration_at' IS NULL THEN ''
 ELSE extract(epoch FROM (p_values->>'actual_administration_at')::timestamptz)::bigint::text END,
 p_values->>'reason',coalesce(p_values->>'expected_report_id',''),coalesce(p_values->>'notes','')),'UTF8')),'hex')
$$;
ALTER FUNCTION public.assistant_record_late_key(uuid,jsonb) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_record_late_key(uuid,jsonb)
 FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;

-- Native entry points use this same fence. An unbound legacy confirmation has
-- no new workflow association and retains its native policy. The fixed workflow
-- writer additionally requires an actually issued private preparation association.
CREATE FUNCTION public.assistant_record_assert_current(p_owner uuid,p_challenge uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE binding public.assistant_record_commands%ROWTYPE;t jsonb;ctl jsonb;
BEGIN
 IF public.assistant_patient_uid() IS DISTINCT FROM p_owner THEN RAISE EXCEPTION 'Verified owner required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(p_owner::text,35035));
 SELECT * INTO binding FROM public.assistant_record_commands WHERE owner=p_owner AND native_id=p_challenge
  AND kind IN ('prepare_report','prepare_late_report') AND state IN ('pending','applied') ORDER BY action_key LIMIT 1;
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT data INTO t FROM public.assistant_workflow_tasks WHERE owner=p_owner AND id=binding.task_id;
 SELECT data INTO ctl FROM public.assistant_workflow_operations WHERE owner=p_owner AND task_id=binding.task_id
  AND id=binding.task_id AND record_type='control';
 IF t IS NULL OR ctl IS NULL OR t->>'state' IS DISTINCT FROM 'awaiting_confirmation'
 OR t->>'save_mode' IS DISTINCT FROM 'allowed' OR ctl->>'mode' IS DISTINCT FROM 'allowed'
 OR ctl->'revoked' IS DISTINCT FROM 'false'::jsonb OR ctl->>'status' IS DISTINCT FROM 'idle'
 OR t->>'capability_id' IS DISTINCT FROM binding.capability_id
 OR (t->>'revision')::int IS DISTINCT FROM binding.binding_revision
 OR (ctl->>'revision')::int IS DISTINCT FROM binding.binding_revision
 OR NOT (t->'business_refs' @> jsonb_build_array(binding.prepared_ref)) THEN
  RAISE EXCEPTION 'Confirmation predates current owned patient review' USING ERRCODE='40001'; END IF;
 RETURN to_jsonb(binding);
END $$;
ALTER FUNCTION public.assistant_record_assert_current(uuid,uuid) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_record_assert_current(uuid,uuid)
 FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;

CREATE FUNCTION public.assistant_record_native_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE prep jsonb;
BEGIN
 IF TG_TABLE_NAME='confirmation_challenges' THEN
  IF NEW.action='record_self_report' THEN PERFORM public.assistant_record_assert_current(NEW.patient_id,NEW.id); END IF;
 ELSIF TG_TABLE_NAME='dose_events' THEN
  prep:=public.assistant_record_assert_current(NEW.patient_id,NEW.confirmation_challenge_id);
  IF prep IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.assistant_record_commands c
   WHERE c.owner=NEW.patient_id AND c.task_id=(prep->>'task_id')::uuid
   AND c.binding_revision=(prep->>'binding_revision')::int AND c.operation_key=(prep->>'operation_key')::uuid
   AND c.state='pending' AND c.kind IN ('self_report','prn_report') AND c.native_id=NEW.id) THEN
   RAISE EXCEPTION 'Bound native reports require the coupled domain transaction' USING ERRCODE='40001'; END IF;
 ELSE
  IF EXISTS(SELECT 1 FROM public.assistant_record_commands c WHERE c.owner=NEW.patient_id
   AND c.kind='prepare_late_report' AND c.operation_key=NEW.id)
  AND NOT EXISTS(SELECT 1 FROM public.assistant_record_commands c WHERE c.owner=NEW.patient_id
   AND c.operation_key=NEW.id AND c.native_id=NEW.id AND c.state='pending' AND c.kind IN ('late_report','correction')) THEN
   RAISE EXCEPTION 'Bound corrections require the coupled domain transaction' USING ERRCODE='40001'; END IF;
 END IF;
 RETURN NEW;
END $$;
ALTER FUNCTION public.assistant_record_native_guard() OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_record_native_guard()
 FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;
CREATE TRIGGER assistant_record_challenge_current BEFORE INSERT OR UPDATE ON public.confirmation_challenges
 FOR EACH ROW EXECUTE FUNCTION public.assistant_record_native_guard();
CREATE TRIGGER assistant_record_event_current BEFORE INSERT ON public.dose_events
 FOR EACH ROW EXECUTE FUNCTION public.assistant_record_native_guard();
CREATE TRIGGER assistant_record_history_current BEFORE INSERT ON public.dose_report_entries
 FOR EACH ROW EXECUTE FUNCTION public.assistant_record_native_guard();

ALTER FUNCTION public.record_confirmed_self_report(jsonb) RENAME TO assistant_record_self_legacy_005;
ALTER FUNCTION public.record_late_dose_report(uuid,jsonb,uuid) RENAME TO assistant_record_late_legacy_033;
REVOKE ALL ON FUNCTION public.assistant_record_self_legacy_005(jsonb),public.assistant_record_late_legacy_033(uuid,jsonb,uuid)
 FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;
GRANT EXECUTE ON FUNCTION public.assistant_record_self_legacy_005(jsonb),public.assistant_record_late_legacy_033(uuid,jsonb,uuid)
 TO assistant_workflow_owner;

CREATE FUNCTION public.assistant_record_event_projection(p_value jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE SECURITY INVOKER SET search_path='' AS $$
 SELECT jsonb_object_agg(key,value) FROM jsonb_each(p_value) WHERE key=ANY(ARRAY['id','patient_id','regimen_id',
 'occurrence_id','event_time','intake_status','visual_status','ingestion_proven','idempotency_key','created_at',
 'reported_late','actual_administration_at'])
$$;
ALTER FUNCTION public.assistant_record_event_projection(jsonb) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_record_event_projection(jsonb)
 FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;

CREATE FUNCTION public.assistant_record_summary(p_owner uuid,p_challenge uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE c public.confirmation_challenges%ROWTYPE;r public.regimen_versions%ROWTYPE;
 m public.patient_medications%ROWTYPE;due timestamptz;zone text;
BEGIN
 SELECT * INTO STRICT c FROM public.confirmation_challenges WHERE patient_id=p_owner AND id=p_challenge;
 SELECT * INTO STRICT r FROM public.regimen_versions WHERE patient_id=p_owner AND id=c.regimen_id;
 SELECT * INTO STRICT m FROM public.patient_medications WHERE patient_id=p_owner AND id=r.patient_medication_id;
 SELECT timezone INTO STRICT zone FROM public.patient_profiles WHERE user_id=p_owner;
 SELECT due_at INTO due FROM public.dose_occurrences WHERE patient_id=p_owner AND id=c.occurrence_id;
 RETURN jsonb_build_object('medication_display_name',m.display_name,'dose_amount',r.dose_amount,'dose_unit',r.dose_unit,
 'regimen_version_no',r.version_no,'occurrence_due_at',due,'local_due_time',to_char(due AT TIME ZONE zone,'YYYY-MM-DD HH24:MI'),
 'local_timezone',zone,'intake_status',c.intended_intake_status,'intake_status_label',
 CASE c.intended_intake_status WHEN 'reported_taken' THEN 'Taken (as reported by you)'
 WHEN 'reported_not_taken' THEN 'Not taken (as reported by you)' WHEN 'unsure' THEN 'Unsure (as reported by you)' ELSE 'No report' END,
 'safety_notice',CASE c.intended_intake_status
 WHEN 'reported_taken' THEN 'Recorded as reported by you — this does not prove the medication was taken.'
 WHEN 'unsure' THEN 'Recorded as unsure — nothing was inferred about the actual intake.' ELSE 'Recorded as reported by you.' END,
 'ingestion_proven',false,'visual_status','not_checked');
END $$;
ALTER FUNCTION public.assistant_record_summary(uuid,uuid) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_record_summary(uuid,uuid)
 FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;

CREATE FUNCTION public.assistant_record_late_target(p_owner uuid,p_occurrence uuid,p_values jsonb,p_version integer) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE d public.dose_occurrences%ROWTYPE;r public.regimen_versions%ROWTYPE;m public.patient_medications%ROWTYPE;
 s public.source_documents%ROWTYPE;latest public.dose_report_entries%ROWTYPE;current_event record;zone text;
 actual timestamptz:=(p_values->>'actual_administration_at')::timestamptz;current_id uuid;history_version integer:=0;
BEGIN
 SELECT * INTO d FROM public.dose_occurrences WHERE patient_id=p_owner AND id=p_occurrence FOR UPDATE;
 IF NOT FOUND OR d.due_at>clock_timestamp() OR d.due_at<clock_timestamp()-interval '7 days' THEN
  RAISE EXCEPTION 'Choose an existing past occurrence within seven days' USING ERRCODE='22023'; END IF;
 SELECT * INTO STRICT r FROM public.regimen_versions WHERE patient_id=p_owner AND id=d.regimen_id FOR SHARE;
 SELECT * INTO STRICT m FROM public.patient_medications WHERE patient_id=p_owner AND id=r.patient_medication_id FOR SHARE;
 SELECT * INTO s FROM public.source_documents WHERE patient_id=p_owner AND id=r.source_id;
 SELECT timezone INTO STRICT zone FROM public.patient_profiles WHERE user_id=p_owner;
 IF r.is_prn OR r.state IN ('draft','pending_clarification') OR r.effective_from IS NULL OR d.due_at<r.effective_from
 OR (r.effective_to IS NOT NULL AND d.due_at>=r.effective_to)
 OR (r.course_start_date IS NOT NULL AND (d.due_at AT TIME ZONE zone)::date<r.course_start_date)
 OR (r.course_end_date IS NOT NULL AND (d.due_at AT TIME ZONE zone)::date>r.course_end_date)
 OR m.identity_status NOT IN ('user_reviewed_document','professional_verified')
 OR s.id IS NULL OR s.review_status NOT IN ('user_reviewed','professional_verified') THEN
  RAISE EXCEPTION 'Reviewed applicable historical plan required' USING ERRCODE='22023'; END IF;
 IF actual IS NOT NULL AND (p_values->>'intake_status'<>'reported_taken' OR actual>clock_timestamp()
 OR actual<clock_timestamp()-interval '7 days' OR actual<r.effective_from
 OR (r.effective_to IS NOT NULL AND actual>=r.effective_to)
 OR (r.course_start_date IS NOT NULL AND (actual AT TIME ZONE zone)::date<r.course_start_date)
 OR (r.course_end_date IS NOT NULL AND (actual AT TIME ZONE zone)::date>r.course_end_date)
 OR date_trunc('second',actual)<>actual) THEN
  RAISE EXCEPTION 'Review the actual administration time within this historical plan' USING ERRCODE='22023'; END IF;
 SELECT * INTO latest FROM public.dose_report_entries WHERE patient_id=p_owner AND occurrence_id=p_occurrence ORDER BY version DESC LIMIT 1;
 SELECT * INTO current_event FROM public.effective_dose_events WHERE patient_id=p_owner AND occurrence_id=p_occurrence;
 current_id:=current_event.id;history_version:=coalesce(latest.version,0);
 IF current_id IS DISTINCT FROM (p_values->>'expected_report_id')::uuid OR history_version+1 IS DISTINCT FROM p_version THEN
  RAISE EXCEPTION 'Current historical report changed' USING ERRCODE='40001'; END IF;
 RETURN jsonb_build_object('occurrence_id',d.id,'regimen_id',r.id,'medication_id',m.id,'medication_name',m.display_name,
 'strength_text',s.dose_basis->>'strength_text','form',s.dose_basis->>'form','version_no',r.version_no,'can_report',true,
 'unavailable_reason',NULL,'due_at',d.due_at,'dose_amount',r.dose_amount,'dose_unit',r.dose_unit,'report_id',current_id,
 'intake_status',current_event.intake_status,'actual_administration_at',latest.actual_administration_at,
 'recorded_at',coalesce(latest.recorded_at,current_event.created_at),'reason',latest.reason,'notes',coalesce(latest.notes,''));
END $$;
ALTER FUNCTION public.assistant_record_late_target(uuid,uuid,jsonb,integer) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_record_late_target(uuid,uuid,jsonb,integer)
 FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;

CREATE FUNCTION public.assistant_record_native_result(p_owner uuid,p_command jsonb,p_created boolean DEFAULT false,p_token text DEFAULT '') RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE c public.assistant_record_commands%ROWTYPE;b public.assistant_business_receipts%ROWTYPE;
 ch public.confirmation_challenges%ROWTYPE;value jsonb;target jsonb;zone text;
BEGIN
 SELECT * INTO STRICT c FROM public.assistant_record_commands WHERE owner=p_owner AND action_key=(p_command->'binding'->>'action_key')::uuid;
 SELECT * INTO STRICT b FROM public.assistant_business_receipts WHERE owner=p_owner AND action_key=c.action_key;
 IF c.state<>'applied' THEN RAISE EXCEPTION 'Record transaction is unsettled' USING ERRCODE='40001'; END IF;
 IF c.kind='prepare_review' THEN
  value:='null'::jsonb;
 ELSIF c.kind='prepare_report' THEN
  SELECT * INTO STRICT ch FROM public.confirmation_challenges WHERE patient_id=p_owner AND id=c.native_id;
  value:=jsonb_build_object('challenge',public.assistant_medication_projection(to_jsonb(ch),'challenge'),
   'token',p_token,'created',p_created,'summary',public.assistant_record_summary(p_owner,ch.id));
 ELSIF c.kind='prepare_late_report' THEN
  SELECT * INTO STRICT ch FROM public.confirmation_challenges WHERE patient_id=p_owner AND id=c.native_id;
  IF ch.consumed_at IS NOT NULL THEN RAISE EXCEPTION 'Read the actual applied historical record' USING ERRCODE='40001'; END IF;
  target:=public.assistant_record_late_target(p_owner,(c.prepared_ref->>'id')::uuid,p_command->'values',(c.prepared_ref->>'version')::int);
  SELECT timezone INTO STRICT zone FROM public.patient_profiles WHERE user_id=p_owner;
  value:=jsonb_build_object('challenge_id',ch.id,'session_id',ch.session_id,'expires_at',ch.expires_at,
   'occurrence',target,'proposed',p_command->'values','timezone',zone);
 ELSIF c.kind IN ('self_report','prn_report') THEN
  SELECT public.assistant_record_event_projection(to_jsonb(e)) INTO value FROM public.dose_events e
   WHERE e.patient_id=p_owner AND e.id=c.native_id AND e.regimen_id=(c.prepared_ref->>'id')::uuid
   AND e.idempotency_key='report-'||c.action_key::text;
  IF value IS NULL THEN RAISE EXCEPTION 'Native event unavailable; retain receipt' USING ERRCODE='40001'; END IF;
  value:=jsonb_build_object('event',value,'existing_event_id',c.native_id,'already_recorded',NOT p_created);
 ELSE
  SELECT to_jsonb(e) INTO value FROM public.dose_report_entries e WHERE patient_id=p_owner AND id=c.native_id
   AND occurrence_id=(c.prepared_ref->>'id')::uuid;
 END IF;
 IF value IS NULL THEN RAISE EXCEPTION 'Native record unavailable; retain receipt' USING ERRCODE='40001'; END IF;
 RETURN jsonb_build_object('receipt',to_jsonb(b),'result',value);
END $$;
ALTER FUNCTION public.assistant_record_native_result(uuid,jsonb,boolean,text) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_record_native_result(uuid,jsonb,boolean,text)
 FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;

CREATE FUNCTION public.assistant_record_apply(p_command jsonb,p_native_event uuid DEFAULT NULL) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE o uuid:=public.assistant_patient_uid();b jsonb:=p_command->'binding';kind text:=p_command->>'kind';ref jsonb:=b->'prepared_ref';
 preparing boolean:=kind IN ('prepare_review','prepare_report','prepare_late_report');
 selecting boolean:=kind='prepare_review';historical boolean:=kind IN ('prepare_late_report','late_report','correction');
 tid uuid;action_id uuid;operation_id uuid;revision integer;digest text;allowed text[];t jsonb;ctl jsonb;native_key text;
 prior public.assistant_record_commands%ROWTYPE;session_row public.agent_sessions%ROWTYPE;ch public.confirmation_challenges%ROWTYPE;
 plan public.regimen_versions%ROWTYPE;medicine public.patient_medications%ROWTYPE;occ public.dose_occurrences%ROWTYPE;
 values_json jsonb:=p_command->'values';native_ref jsonb;prep jsonb;native_id uuid;result jsonb;target jsonb;zone text;
 generation bigint;stamped timestamptz;token_once text:='';created boolean:=true;child jsonb;status text;
BEGIN
 IF o IS NULL OR public.assistant_patient_role() IS DISTINCT FROM 'authenticated' THEN
  RAISE EXCEPTION 'Verified patient required' USING ERRCODE='42501'; END IF;
 allowed:=CASE kind
 WHEN 'prepare_review' THEN ARRAY['kind','binding']
 WHEN 'prepare_report' THEN ARRAY['kind','binding','session_id','session_state_version','operation_key','intake_status','occurrence_id']
 WHEN 'prepare_late_report' THEN ARRAY['kind','binding','session_id','session_state_version','values']
 WHEN 'self_report' THEN ARRAY['kind','binding','challenge_id','confirmed','values']
 WHEN 'prn_report' THEN ARRAY['kind','binding','challenge_id','confirmed','values']
 WHEN 'late_report' THEN ARRAY['kind','binding','challenge_id','confirmed','occurrence_id','values']
 WHEN 'correction' THEN ARRAY['kind','binding','challenge_id','confirmed','occurrence_id','values'] ELSE NULL END;
 IF allowed IS NULL OR NOT coalesce(public.assistant_wf_keys(p_command,allowed),false)
 OR octet_length(p_command::text)>32768 OR NOT coalesce(public.assistant_wf_keys(b,ARRAY['task_id','task_revision',
 'capability_id','action_key','prepared_ref','expected_domain_revision','run_binding']),false)
 OR NOT (b ?& ARRAY['task_id','task_revision','capability_id','action_key','prepared_ref','expected_domain_revision'])
 OR NOT coalesce(public.assistant_wf_keys(ref,ARRAY['kind','id','version']),false)
 OR jsonb_typeof(b->'task_revision') IS DISTINCT FROM 'number' OR b->>'task_revision' !~ '^[1-9][0-9]*$'
 OR jsonb_typeof(b->'expected_domain_revision') IS DISTINCT FROM 'number' OR b->>'expected_domain_revision' !~ '^(0|[1-9][0-9]*)$'
 OR ref->>'id' IS NULL OR ref->>'kind' NOT IN ('regimen','dose_occurrence')
 OR jsonb_typeof(ref->'version') IS DISTINCT FROM 'number' OR ref->>'version' !~ '^[1-9][0-9]*$'
 OR (NOT preparing AND p_command->'confirmed' IS DISTINCT FROM 'true'::jsonb) THEN
  RAISE EXCEPTION 'Invalid fixed record command' USING ERRCODE='22023'; END IF;
 tid:=(b->>'task_id')::uuid;action_id:=(b->>'action_key')::uuid;revision:=(b->>'task_revision')::int;
 IF tid IS NULL OR action_id IS NULL THEN RAISE EXCEPTION 'Missing patient report binding' USING ERRCODE='22023'; END IF;
 digest:=public.assistant_record_digest(p_command);
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 SELECT data INTO t FROM public.assistant_workflow_tasks WHERE owner=o AND id=tid FOR UPDATE;
 SELECT data INTO ctl FROM public.assistant_workflow_operations WHERE owner=o AND task_id=tid AND id=tid AND record_type='control' FOR UPDATE;
 SELECT * INTO prior FROM public.assistant_record_commands WHERE owner=o AND action_key=action_id;
 IF FOUND THEN
  IF prior.command_digest IS DISTINCT FROM digest OR prior.task_id IS DISTINCT FROM tid THEN
   RAISE EXCEPTION 'Record action reused with different inputs' USING ERRCODE='23505'; END IF;
  RETURN jsonb_build_object('result',public.assistant_record_native_result(o,p_command),'replayed',true);
 END IF;
 IF EXISTS(SELECT 1 FROM public.assistant_business_receipts WHERE owner=o AND action_key=action_id) THEN
  RAISE EXCEPTION 'Action belongs to another transaction' USING ERRCODE='23505'; END IF;
 SELECT coalesce((SELECT g.revision FROM public.assistant_enrollment_generations g WHERE owner=o),0) INTO generation;
 IF t IS NULL OR ctl IS NULL OR t->>'state' IS DISTINCT FROM (CASE WHEN selecting THEN 'ready_for_review' ELSE 'awaiting_confirmation' END)
 OR t->>'save_mode' IS DISTINCT FROM 'allowed' OR ctl->>'mode' IS DISTINCT FROM 'allowed'
 OR ctl->'revoked' IS DISTINCT FROM 'false'::jsonb OR ctl->>'status' IS DISTINCT FROM 'idle'
 OR t->>'capability_id' IS DISTINCT FROM b->>'capability_id' OR ctl->>'capability_id' IS DISTINCT FROM b->>'capability_id'
 OR (t->>'revision')::int IS DISTINCT FROM revision OR (ctl->>'revision')::int IS DISTINCT FROM revision
 OR (NOT selecting AND NOT (t->'business_refs' @> jsonb_build_array(ref)))
 OR (selecting AND (t->'business_refs' IS DISTINCT FROM '[]'::jsonb OR t->'attachment_ids' IS DISTINCT FROM '[]'::jsonb))
 OR generation IS DISTINCT FROM (b->>'expected_domain_revision')::bigint THEN
  RAISE EXCEPTION 'Current saved patient review changed' USING ERRCODE='40001'; END IF;
 IF nullif(b->'run_binding','null'::jsonb) IS NOT NULL THEN PERFORM public.assistant_run_assert_current(o,b->'run_binding'); END IF;
 IF selecting THEN
  IF b->>'capability_id' IN ('dose.late.review','dose.correction.review') THEN
   IF ref->>'kind' IS DISTINCT FROM 'dose_occurrence'
   OR ref->>'id' IS DISTINCT FROM t->'fields'->>'occurrence_id'
   OR ref->'version' IS DISTINCT FROM t->'fields'->'expected_version'
   OR ((t->'fields'->>'expected_report_id' IS NOT NULL) IS DISTINCT FROM (b->>'capability_id'='dose.correction.review')) THEN
    RAISE EXCEPTION 'Choose the existing historical report generation' USING ERRCODE='40001'; END IF;
   target:=public.assistant_record_late_target(o,(ref->>'id')::uuid,
    jsonb_build_object('expected_report_id',t->'fields'->'expected_report_id'),(ref->>'version')::int);
  ELSIF b->>'capability_id' IN ('dose.report','dose.prn.report') THEN
   IF ref->>'kind' IS DISTINCT FROM 'regimen' OR ref->>'id' IS DISTINCT FROM t->'fields'->>'regimen_id'
   OR ref->'version' IS DISTINCT FROM t->'fields'->'expected_version' THEN
    RAISE EXCEPTION 'Choose the saved owned plan version' USING ERRCODE='40001'; END IF;
   SELECT * INTO plan FROM public.regimen_versions WHERE patient_id=o AND id=(ref->>'id')::uuid FOR SHARE;
   IF NOT FOUND OR plan.state<>'active' OR plan.version_no IS DISTINCT FROM (ref->>'version')::int
   OR plan.is_prn IS DISTINCT FROM (b->>'capability_id'='dose.prn.report') THEN
    RAISE EXCEPTION 'Current active report plan required' USING ERRCODE='40001'; END IF;
   SELECT * INTO STRICT medicine FROM public.patient_medications WHERE patient_id=o AND id=plan.patient_medication_id FOR SHARE;
   SELECT timezone INTO STRICT zone FROM public.patient_profiles WHERE user_id=o;
   IF medicine.archived_at IS NOT NULL OR (plan.effective_from IS NOT NULL AND clock_timestamp()<plan.effective_from)
   OR (plan.effective_to IS NOT NULL AND clock_timestamp()>=plan.effective_to)
   OR (plan.course_start_date IS NOT NULL AND (clock_timestamp() AT TIME ZONE zone)::date<plan.course_start_date)
   OR (plan.course_end_date IS NOT NULL AND (clock_timestamp() AT TIME ZONE zone)::date>plan.course_end_date) THEN
    RAISE EXCEPTION 'Current applicable report plan required' USING ERRCODE='40001'; END IF;
  ELSE RAISE EXCEPTION 'Capability cannot select a patient report target' USING ERRCODE='22023'; END IF;
  child:=public.assistant_workflow_command_legacy_035('task_cas',jsonb_build_object('task_id',tid,'expected_revision',revision,
   'event_id',action_id,'request_digest',digest,'update',jsonb_build_object('state','awaiting_confirmation','save_mode','allowed',
    'storage_state','saved','fields',t->'fields','missing_fields','[]'::jsonb,'attachment_ids','[]'::jsonb,'business_refs',jsonb_build_array(ref))));
  IF child ? 'error' THEN RAISE EXCEPTION 'Saved report target changed' USING ERRCODE='40001'; END IF;
  IF nullif(b->'run_binding','null'::jsonb) IS NOT NULL THEN PERFORM public.assistant_run_assert_current(o,b->'run_binding'); END IF;
  INSERT INTO public.assistant_business_receipts(owner,action_key,task_id,capability_id,binding_revision,business_ref,domain_revision,outcome)
   VALUES(o,action_id,tid,b->>'capability_id',revision+1,ref,generation,'prepared');
  INSERT INTO public.assistant_record_commands(owner,action_key,task_id,binding_revision,capability_id,kind,command_digest,
   prepared_ref,operation_key,native_id,state) VALUES(o,action_id,tid,revision+1,b->>'capability_id',kind,digest,ref,action_id,NULL,'applied');
  RETURN jsonb_build_object('result',public.assistant_record_native_result(o,p_command),'replayed',false);
 END IF;
 IF (kind='self_report' AND b->>'capability_id'<>'dose.report') OR (kind='prn_report' AND b->>'capability_id'<>'dose.prn.report')
 OR (kind='late_report' AND b->>'capability_id'<>'dose.late.review')
 OR (kind='correction' AND b->>'capability_id'<>'dose.correction.review')
 OR (kind='prepare_report' AND b->>'capability_id' NOT IN ('dose.report','dose.prn.report'))
 OR (kind='prepare_late_report' AND b->>'capability_id' NOT IN ('dose.late.review','dose.correction.review')) THEN
  RAISE EXCEPTION 'Capability cannot prepare or record this report' USING ERRCODE='22023'; END IF;
 IF historical THEN
  IF ref->>'kind'<>'dose_occurrence' OR NOT coalesce(public.assistant_wf_keys(values_json,ARRAY['id','intake_status',
   'actual_administration_at','reason','notes','expected_report_id']),false)
  OR values_json->>'id' IS NULL OR values_json->>'reason' NOT IN ('forgot_to_record','app_unavailable','unsure_time','correcting_record','other')
  OR length(coalesce(values_json->>'notes',''))>1000 OR t->'fields'->>'occurrence_id' IS DISTINCT FROM ref->>'id'
  OR t->'fields'->'expected_version' IS DISTINCT FROM ref->'version'
  OR t->'fields'->>'expected_report_id' IS DISTINCT FROM values_json->>'expected_report_id'
  OR ((values_json->>'expected_report_id' IS NOT NULL) IS DISTINCT FROM (b->>'capability_id'='dose.correction.review'))
  OR (NOT preparing AND (p_command->>'occurrence_id' IS DISTINCT FROM ref->>'id'
   OR values_json->>'id' IS DISTINCT FROM action_id::text)) THEN
   RAISE EXCEPTION 'Historical report differs from selected occurrence/current report' USING ERRCODE='22023'; END IF;
  operation_id:=(values_json->>'id')::uuid;status:=values_json->>'intake_status';
  target:=public.assistant_record_late_target(o,(ref->>'id')::uuid,values_json,(ref->>'version')::int);
  SELECT * INTO STRICT occ FROM public.dose_occurrences WHERE patient_id=o AND id=(ref->>'id')::uuid FOR UPDATE;
  SELECT * INTO STRICT plan FROM public.regimen_versions WHERE patient_id=o AND id=occ.regimen_id FOR SHARE;
  native_key:=public.assistant_record_late_key(occ.id,values_json);
 ELSE
  IF ref->>'kind'<>'regimen' THEN RAISE EXCEPTION 'Choose the owned plan version' USING ERRCODE='22023'; END IF;
  SELECT * INTO plan FROM public.regimen_versions WHERE patient_id=o AND id=(ref->>'id')::uuid FOR SHARE;
  IF NOT FOUND OR plan.version_no IS DISTINCT FROM (ref->>'version')::int OR plan.state<>'active'
  OR plan.is_prn IS DISTINCT FROM (b->>'capability_id'='dose.prn.report') THEN
   RAISE EXCEPTION 'Current reviewed medication plan changed' USING ERRCODE='40001'; END IF;
  SELECT * INTO STRICT medicine FROM public.patient_medications WHERE patient_id=o AND id=plan.patient_medication_id FOR SHARE;
  IF medicine.archived_at IS NOT NULL OR (plan.effective_from IS NOT NULL AND clock_timestamp()<plan.effective_from)
  OR (plan.effective_to IS NOT NULL AND clock_timestamp()>=plan.effective_to) THEN
   RAISE EXCEPTION 'Current applicable medication required' USING ERRCODE='40001'; END IF;
  IF preparing THEN
   operation_id:=(p_command->>'operation_key')::uuid;status:=p_command->>'intake_status';
   occ.id:=(p_command->>'occurrence_id')::uuid;
  ELSE
   IF NOT coalesce(public.assistant_wf_keys(values_json,ARRAY['regimen_id','occurrence_id','intake_status','event_time','idempotency_key']),false)
   OR values_json->>'regimen_id' IS DISTINCT FROM plan.id::text
   OR values_json->>'idempotency_key' IS DISTINCT FROM 'report-'||action_id::text THEN
    RAISE EXCEPTION 'Native report request differs from selected plan' USING ERRCODE='22023'; END IF;
   operation_id:=action_id;status:=values_json->>'intake_status';occ.id:=(values_json->>'occurrence_id')::uuid;
  END IF;
  native_key:='report-'||operation_id::text;
  IF plan.is_prn THEN
   IF occ.id IS NOT NULL THEN RAISE EXCEPTION 'PRN cannot refer to a scheduled occurrence' USING ERRCODE='22023'; END IF;
  ELSE
   SELECT * INTO occ FROM public.dose_occurrences WHERE patient_id=o AND id=occ.id AND regimen_id=plan.id FOR UPDATE;
   IF NOT FOUND OR occ.status='closed' OR EXISTS(SELECT 1 FROM public.effective_dose_events WHERE patient_id=o AND occurrence_id=occ.id) THEN
    RAISE EXCEPTION 'Choose an existing open owned occurrence' USING ERRCODE='40001'; END IF;
  END IF;
  SELECT timezone INTO STRICT zone FROM public.patient_profiles WHERE user_id=o;
  IF (plan.course_start_date IS NOT NULL AND (coalesce(occ.due_at,clock_timestamp()) AT TIME ZONE zone)::date<plan.course_start_date)
  OR (plan.course_end_date IS NOT NULL AND (coalesce(occ.due_at,clock_timestamp()) AT TIME ZONE zone)::date>plan.course_end_date) THEN
   RAISE EXCEPTION 'Dose lies outside reviewed course dates' USING ERRCODE='22023'; END IF;
 END IF;
 IF operation_id IS NULL OR status IS NULL OR status NOT IN ('reported_taken','reported_not_taken','unsure') THEN
  RAISE EXCEPTION 'Choose an explicit patient report status' USING ERRCODE='22023'; END IF;
 INSERT INTO public.assistant_record_commands(owner,action_key,task_id,binding_revision,capability_id,kind,command_digest,
  prepared_ref,operation_key,state) VALUES(o,action_id,tid,revision,b->>'capability_id',kind,digest,ref,operation_id,'pending');
 IF preparing THEN
  SELECT * INTO session_row FROM public.agent_sessions WHERE patient_id=o AND id=(p_command->>'session_id')::uuid FOR UPDATE;
  IF NOT FOUND OR session_row.state<>'awaiting_confirmation' OR session_row.expires_at<=clock_timestamp()
  OR session_row.state_version IS DISTINCT FROM (p_command->>'session_state_version')::int THEN
   RAISE EXCEPTION 'Independent confirmation session changed or expired' USING ERRCODE='40001'; END IF;
  SELECT * INTO ch FROM public.confirmation_challenges WHERE patient_id=o AND idempotency_key=native_key;
  IF FOUND THEN
   prep:=public.assistant_record_assert_current(o,ch.id);
   IF prep IS NULL OR prep->>'task_id' IS DISTINCT FROM tid::text OR prep->'prepared_ref' IS DISTINCT FROM ref
   OR ch.session_id IS DISTINCT FROM session_row.id OR ch.session_state_version IS DISTINCT FROM session_row.state_version
   OR ch.regimen_id IS DISTINCT FROM plan.id OR ch.occurrence_id IS DISTINCT FROM occ.id
   OR ch.intended_intake_status IS DISTINCT FROM status OR ch.consumed_at IS NOT NULL OR ch.expires_at<=clock_timestamp() THEN
    RAISE EXCEPTION 'Existing confirmation cannot be adopted by a new review' USING ERRCODE='40001'; END IF;
   native_id:=ch.id;created:=false;
  ELSE
   native_id:=gen_random_uuid();stamped:=clock_timestamp();token_once:=replace(gen_random_uuid()::text||gen_random_uuid()::text,'-','');
   UPDATE public.assistant_record_commands SET native_id=assistant_record_apply.native_id WHERE owner=o AND action_key=action_id;
   INSERT INTO public.confirmation_challenges(id,patient_id,session_id,session_state_version,action,regimen_id,occurrence_id,
    intended_intake_status,idempotency_key,token_hash,request_hash,issued_at,expires_at)
   VALUES(native_id,o,session_row.id,session_row.state_version,'record_self_report',plan.id,occ.id,status,native_key,
    encode(sha256(convert_to(token_once,'UTF8')),'hex'),digest,stamped,stamped+interval '10 minutes');
  END IF;
  native_ref:=ref;
 ELSE
  SELECT * INTO ch FROM public.confirmation_challenges WHERE patient_id=o AND id=(p_command->>'challenge_id')::uuid FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Request an independent confirmation first' USING ERRCODE='40001'; END IF;
  prep:=public.assistant_record_assert_current(o,ch.id);
  IF prep IS NULL OR prep->>'task_id' IS DISTINCT FROM tid::text OR prep->'prepared_ref' IS DISTINCT FROM ref
  OR (prep->>'operation_key')::uuid IS DISTINCT FROM operation_id OR prep->>'state' IS DISTINCT FROM 'applied'
  OR ch.action IS DISTINCT FROM 'record_self_report' OR ch.regimen_id IS DISTINCT FROM plan.id
  OR ch.occurrence_id IS DISTINCT FROM occ.id OR ch.idempotency_key IS DISTINCT FROM native_key
  OR ch.intended_intake_status IS DISTINCT FROM status OR ch.consumed_at IS NOT NULL OR ch.expires_at<=clock_timestamp() THEN
   RAISE EXCEPTION 'Current exact patient confirmation required' USING ERRCODE='40001'; END IF;
  SELECT * INTO STRICT session_row FROM public.agent_sessions WHERE patient_id=o AND id=ch.session_id FOR UPDATE;
  IF session_row.state<>'awaiting_confirmation' OR session_row.state_version IS DISTINCT FROM ch.session_state_version
  OR session_row.expires_at<=clock_timestamp() THEN RAISE EXCEPTION 'Confirmation session changed' USING ERRCODE='40001'; END IF;
  IF ch.confirmed_at IS NULL THEN UPDATE public.confirmation_challenges SET confirmed_at=clock_timestamp() WHERE patient_id=o AND id=ch.id; END IF;
  native_id:=CASE WHEN historical THEN operation_id ELSE coalesce(p_native_event,gen_random_uuid()) END;
  UPDATE public.assistant_record_commands c SET native_id=assistant_record_apply.native_id WHERE c.owner=o AND c.action_key=action_id;
  IF historical THEN
   result:=public.assistant_record_late_legacy_033(occ.id,values_json,ch.id);
   IF result->>'id' IS DISTINCT FROM native_id::text THEN RAISE EXCEPTION 'Native report result changed' USING ERRCODE='40001'; END IF;
   native_ref:=jsonb_build_object('kind','late_report','id',native_id,'version',(result->>'version')::int);
  ELSE
   result:=public.assistant_record_self_legacy_005(jsonb_build_object('id',native_id,'patient_id',o,'regimen_id',plan.id,
    'occurrence_id',occ.id,'confirmation_challenge_id',ch.id,'event_time',clock_timestamp(),'intake_status',status,'idempotency_key',native_key));
   IF result->>'id' IS DISTINCT FROM native_id::text THEN RAISE EXCEPTION 'Read prior native event instead of claiming a new effect' USING ERRCODE='40001'; END IF;
   native_ref:=jsonb_build_object('kind','dose_event','id',native_id,'version',NULL);
  END IF;
  IF nullif(b->'run_binding','null'::jsonb) IS NOT NULL THEN PERFORM public.assistant_run_assert_current(o,b->'run_binding'); END IF;
  child:=public.assistant_workflow_command_legacy_035('task_cas',jsonb_build_object('task_id',tid,'expected_revision',revision,
   'event_id',action_id,'request_digest',digest,'update',jsonb_build_object('state','completed','save_mode','allowed',
    'storage_state','saved','fields',t->'fields','missing_fields','[]'::jsonb,'attachment_ids',t->'attachment_ids','business_refs',jsonb_build_array(native_ref))));
  IF child ? 'error' THEN RAISE EXCEPTION 'Task changed after native record publication' USING ERRCODE='40001'; END IF;
 END IF;
 SELECT coalesce((SELECT g.revision FROM public.assistant_enrollment_generations g WHERE owner=o),0) INTO generation;
 IF nullif(b->'run_binding','null'::jsonb) IS NOT NULL THEN PERFORM public.assistant_run_assert_current(o,b->'run_binding'); END IF;
 INSERT INTO public.assistant_business_receipts(owner,action_key,task_id,capability_id,binding_revision,business_ref,domain_revision,outcome)
 VALUES(o,action_id,tid,b->>'capability_id',revision+CASE WHEN preparing THEN 0 ELSE 1 END,native_ref,generation,
  CASE WHEN preparing THEN 'prepared' ELSE 'applied' END);
 UPDATE public.assistant_record_commands c SET state='applied',native_id=assistant_record_apply.native_id WHERE c.owner=o AND c.action_key=action_id;
 RETURN jsonb_build_object('result',public.assistant_record_native_result(o,p_command,created,token_once),'replayed',false);
END $$;
ALTER FUNCTION public.assistant_record_apply(jsonb,uuid) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_record_apply(jsonb,uuid)
 FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;

CREATE FUNCTION public.assistant_record_write(p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF p_command->>'kind' IS NULL OR p_command->>'kind' NOT IN ('self_report','prn_report','late_report','correction') THEN
  RAISE EXCEPTION 'Use a confirmed native record command' USING ERRCODE='22023'; END IF;
 RETURN public.assistant_record_apply(p_command);
EXCEPTION
 WHEN SQLSTATE '40001' THEN RETURN jsonb_build_object('error','stale');
 WHEN unique_violation THEN RETURN jsonb_build_object('error','duplicate');
 WHEN no_data_found THEN RETURN jsonb_build_object('error','not_found');
 WHEN invalid_parameter_value OR invalid_text_representation OR check_violation OR not_null_violation
 OR invalid_datetime_format OR datetime_field_overflow OR foreign_key_violation OR raise_exception THEN
  RETURN jsonb_build_object('error','invalid');
 WHEN insufficient_privilege THEN RETURN jsonb_build_object('error','unavailable');
END $$;
ALTER FUNCTION public.assistant_record_write(jsonb) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_record_write(jsonb)
 FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;
GRANT EXECUTE ON FUNCTION public.assistant_record_write(jsonb) TO authenticated;

-- Owned read-only selection lookup distinguishes it from later patient summaries.
CREATE FUNCTION public.assistant_record_review_receipt(p_task_id uuid,p_revision integer) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=public.assistant_patient_uid();result jsonb;n integer;
BEGIN
 IF o IS NULL OR public.assistant_patient_role() IS DISTINCT FROM 'authenticated' THEN
  RAISE EXCEPTION 'Verified patient required' USING ERRCODE='42501'; END IF;
 SELECT count(*) INTO n FROM public.assistant_record_commands WHERE owner=o AND task_id=p_task_id
  AND binding_revision=p_revision AND kind='prepare_review' AND state='applied';
 IF n<>1 THEN RETURN jsonb_build_object('error','not_found'); END IF;
 SELECT to_jsonb(r) INTO result FROM public.assistant_record_commands c JOIN public.assistant_business_receipts r
  ON r.owner=c.owner AND r.action_key=c.action_key WHERE c.owner=o AND c.task_id=p_task_id
  AND c.binding_revision=p_revision AND c.kind='prepare_review' AND c.state='applied'
  AND r.task_id=c.task_id AND r.capability_id=c.capability_id AND r.binding_revision=c.binding_revision
  AND r.business_ref=c.prepared_ref AND r.outcome='prepared';
 IF result IS NULL THEN RETURN jsonb_build_object('error','not_found'); END IF;
 RETURN jsonb_build_object('result',result);
END $$;
ALTER FUNCTION public.assistant_record_review_receipt(uuid,integer) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_record_review_receipt(uuid,integer)
 FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;
GRANT EXECUTE ON FUNCTION public.assistant_record_review_receipt(uuid,integer) TO authenticated;

-- Reads immutable applied report identities; never synthesizes a patient request.
CREATE FUNCTION public.assistant_record_result(p_action_key uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=public.assistant_patient_uid();c public.assistant_record_commands%ROWTYPE;
BEGIN
 IF o IS NULL OR public.assistant_patient_role() IS DISTINCT FROM 'authenticated' THEN
  RAISE EXCEPTION 'Verified patient required' USING ERRCODE='42501'; END IF;
 SELECT * INTO c FROM public.assistant_record_commands WHERE owner=o AND action_key=p_action_key
  AND state='applied' AND kind IN ('self_report','prn_report','late_report','correction');
 IF NOT FOUND OR NOT EXISTS(SELECT 1 FROM public.assistant_business_receipts r WHERE r.owner=o
  AND r.action_key=c.action_key AND r.task_id=c.task_id AND r.capability_id=c.capability_id AND r.outcome='applied') THEN
  RETURN jsonb_build_object('error','not_found'); END IF;
 RETURN jsonb_build_object('result',public.assistant_record_native_result(o,
  jsonb_build_object('binding',jsonb_build_object('action_key',p_action_key))));
EXCEPTION WHEN SQLSTATE '40001' THEN RETURN jsonb_build_object('error','stale');
 WHEN no_data_found THEN RETURN jsonb_build_object('error','not_found');
END $$;
ALTER FUNCTION public.assistant_record_result(uuid) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_record_result(uuid)
 FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;
GRANT EXECUTE ON FUNCTION public.assistant_record_result(uuid) TO authenticated;

CREATE FUNCTION public.assistant_record_prepare(p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF p_command->>'kind' IS NULL OR p_command->>'kind' NOT IN ('prepare_review','prepare_report','prepare_late_report') THEN
  RAISE EXCEPTION 'Use an unconfirmed native preparation command' USING ERRCODE='22023'; END IF;
 RETURN public.assistant_record_apply(p_command);
EXCEPTION
 WHEN SQLSTATE '40001' THEN RETURN jsonb_build_object('error','stale');
 WHEN unique_violation THEN RETURN jsonb_build_object('error','duplicate');
 WHEN no_data_found THEN RETURN jsonb_build_object('error','not_found');
 WHEN invalid_parameter_value OR invalid_text_representation OR check_violation OR not_null_violation
 OR invalid_datetime_format OR datetime_field_overflow OR foreign_key_violation OR raise_exception THEN
  RETURN jsonb_build_object('error','invalid');
 WHEN insufficient_privilege THEN RETURN jsonb_build_object('error','unavailable');
END $$;
ALTER FUNCTION public.assistant_record_prepare(jsonb) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_record_prepare(jsonb)
 FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;
GRANT EXECUTE ON FUNCTION public.assistant_record_prepare(jsonb) TO authenticated;

CREATE FUNCTION public.assistant_record_read(p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=public.assistant_patient_uid();c public.assistant_record_commands%ROWTYPE;
BEGIN
 IF o IS NULL OR public.assistant_patient_role() IS DISTINCT FROM 'authenticated' THEN
  RAISE EXCEPTION 'Verified patient required' USING ERRCODE='42501'; END IF;
 IF jsonb_typeof(p_command) IS DISTINCT FROM 'object' OR octet_length(p_command::text)>32768 THEN
  RAISE EXCEPTION 'Invalid readback command fingerprint' USING ERRCODE='22023'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 SELECT * INTO c FROM public.assistant_record_commands WHERE owner=o AND action_key=(p_command->'binding'->>'action_key')::uuid;
 IF NOT FOUND THEN RETURN jsonb_build_object('error','not_found'); END IF;
 IF c.command_digest IS DISTINCT FROM public.assistant_record_digest(p_command)
 OR c.task_id IS DISTINCT FROM (p_command->'binding'->>'task_id')::uuid THEN
  RETURN jsonb_build_object('error','duplicate'); END IF;
 RETURN jsonb_build_object('result',public.assistant_record_native_result(o,p_command),'replayed',true);
EXCEPTION WHEN SQLSTATE '40001' THEN RETURN jsonb_build_object('error','stale');
 WHEN no_data_found THEN RETURN jsonb_build_object('error','not_found');
 WHEN invalid_parameter_value OR invalid_text_representation THEN RETURN jsonb_build_object('error','invalid');
END $$;
ALTER FUNCTION public.assistant_record_read(jsonb) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_record_read(jsonb)
 FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;
GRANT EXECUTE ON FUNCTION public.assistant_record_read(jsonb) TO authenticated;

-- Preserve legacy unbound signatures and validation. A bound native call derives
-- its original owned task from private issue metadata; it cannot adopt a legacy
-- challenge or publish an event outside the coupled transaction.
CREATE FUNCTION public.record_confirmed_self_report(p_event jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=public.assistant_patient_uid();prep public.assistant_record_commands%ROWTYPE;ch public.confirmation_challenges%ROWTYPE;
 event_row public.dose_events%ROWTYPE;b jsonb;cmd jsonb;result jsonb;generation bigint;
BEGIN
 IF o IS NULL OR public.assistant_patient_role() IS DISTINCT FROM 'authenticated' OR p_event->>'patient_id' IS DISTINCT FROM o::text THEN
  RAISE EXCEPTION 'Verified patient required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 SELECT * INTO prep FROM public.assistant_record_commands WHERE owner=o AND native_id=(p_event->>'confirmation_challenge_id')::uuid
  AND kind='prepare_report' AND state='applied' ORDER BY action_key LIMIT 1;
 IF NOT FOUND THEN RETURN public.assistant_record_self_legacy_005(p_event); END IF;
 SELECT * INTO event_row FROM public.dose_events WHERE patient_id=o AND idempotency_key=p_event->>'idempotency_key';
 IF FOUND THEN
  IF event_row.regimen_id IS DISTINCT FROM (p_event->>'regimen_id')::uuid
  OR event_row.occurrence_id IS DISTINCT FROM (p_event->>'occurrence_id')::uuid OR event_row.intake_status IS DISTINCT FROM p_event->>'intake_status'
  OR NOT EXISTS(SELECT 1 FROM public.assistant_business_receipts r WHERE r.owner=o AND r.action_key=prep.operation_key
   AND r.task_id=prep.task_id AND r.outcome='applied' AND r.business_ref->>'id'=event_row.id::text) THEN
   RAISE EXCEPTION 'Native record request changed' USING ERRCODE='40001'; END IF;
  RETURN to_jsonb(event_row);
 END IF;
 PERFORM public.assistant_record_assert_current(o,prep.native_id);
 SELECT * INTO STRICT ch FROM public.confirmation_challenges WHERE patient_id=o AND id=prep.native_id;
 IF ch.confirmed_at IS NULL THEN RAISE EXCEPTION 'Explicit patient confirmation required' USING ERRCODE='22023'; END IF;
 SELECT coalesce((SELECT g.revision FROM public.assistant_enrollment_generations g WHERE owner=o),0) INTO generation;
 b:=jsonb_build_object('task_id',prep.task_id,'task_revision',prep.binding_revision,'capability_id',prep.capability_id,
  'action_key',prep.operation_key,'prepared_ref',prep.prepared_ref,'expected_domain_revision',generation,'run_binding',NULL);
 cmd:=jsonb_build_object('kind',CASE WHEN prep.capability_id='dose.prn.report' THEN 'prn_report' ELSE 'self_report' END,
  'binding',b,'confirmed',true,'challenge_id',ch.id,'values',jsonb_build_object('regimen_id',p_event->'regimen_id',
   'occurrence_id',p_event->'occurrence_id','intake_status',p_event->'intake_status','event_time',p_event->'event_time',
   'idempotency_key',p_event->'idempotency_key'));
 result:=public.assistant_record_apply(cmd,(p_event->>'id')::uuid);
 SELECT * INTO STRICT event_row FROM public.dose_events WHERE patient_id=o AND id=(result->'result'->'receipt'->'business_ref'->>'id')::uuid;
 RETURN to_jsonb(event_row);
END $$;
ALTER FUNCTION public.record_confirmed_self_report(jsonb) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.record_confirmed_self_report(jsonb) FROM PUBLIC,anon,authenticated,service_role,
 assistant_evidence_login,assistant_evidence_owner;
GRANT EXECUTE ON FUNCTION public.record_confirmed_self_report(jsonb) TO authenticated;

CREATE FUNCTION public.record_late_dose_report(p_occurrence_id uuid,p_values jsonb,p_challenge_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=public.assistant_patient_uid();prep public.assistant_record_commands%ROWTYPE;ch public.confirmation_challenges%ROWTYPE;
 entry public.dose_report_entries%ROWTYPE;b jsonb;cmd jsonb;result jsonb;generation bigint;
BEGIN
 IF o IS NULL OR public.assistant_patient_role() IS DISTINCT FROM 'authenticated' THEN
  RAISE EXCEPTION 'Verified patient required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 SELECT * INTO prep FROM public.assistant_record_commands WHERE owner=o AND native_id=p_challenge_id
  AND kind='prepare_late_report' AND state='applied' ORDER BY action_key LIMIT 1;
 IF NOT FOUND THEN RETURN public.assistant_record_late_legacy_033(p_occurrence_id,p_values,p_challenge_id); END IF;
 SELECT * INTO entry FROM public.dose_report_entries WHERE patient_id=o AND id=(p_values->>'id')::uuid;
 IF FOUND THEN
  IF entry.idempotency_key IS DISTINCT FROM public.assistant_record_late_key(p_occurrence_id,p_values)
  OR NOT EXISTS(SELECT 1 FROM public.assistant_business_receipts r WHERE r.owner=o AND r.action_key=entry.id
   AND r.task_id=prep.task_id AND r.outcome='applied' AND r.business_ref->>'id'=entry.id::text) THEN
   RAISE EXCEPTION 'Historical record request changed' USING ERRCODE='40001'; END IF;
  RETURN to_jsonb(entry);
 END IF;
 PERFORM public.assistant_record_assert_current(o,prep.native_id);
 SELECT * INTO STRICT ch FROM public.confirmation_challenges WHERE patient_id=o AND id=prep.native_id;
 IF ch.confirmed_at IS NULL THEN RAISE EXCEPTION 'Explicit patient confirmation required' USING ERRCODE='22023'; END IF;
 SELECT coalesce((SELECT g.revision FROM public.assistant_enrollment_generations g WHERE owner=o),0) INTO generation;
 b:=jsonb_build_object('task_id',prep.task_id,'task_revision',prep.binding_revision,'capability_id',prep.capability_id,
  'action_key',prep.operation_key,'prepared_ref',prep.prepared_ref,'expected_domain_revision',generation,'run_binding',NULL);
 cmd:=jsonb_build_object('kind',CASE WHEN prep.capability_id='dose.correction.review' THEN 'correction' ELSE 'late_report' END,
  'binding',b,'confirmed',true,'challenge_id',ch.id,'occurrence_id',p_occurrence_id,'values',p_values);
 result:=public.assistant_record_apply(cmd);
 SELECT * INTO STRICT entry FROM public.dose_report_entries WHERE patient_id=o AND id=(result->'result'->'receipt'->'business_ref'->>'id')::uuid;
 RETURN to_jsonb(entry);
END $$;
ALTER FUNCTION public.record_late_dose_report(uuid,jsonb,uuid) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.record_late_dose_report(uuid,jsonb,uuid) FROM PUBLIC,anon,authenticated,service_role,
 assistant_evidence_login,assistant_evidence_owner;
GRANT EXECUTE ON FUNCTION public.record_late_dose_report(uuid,jsonb,uuid) TO authenticated;
COMMIT;
