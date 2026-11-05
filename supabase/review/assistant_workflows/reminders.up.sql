-- REVIEW ONLY / NOT APPLIED. I13 after settings; target SQL/DST/ACL gates required.
-- No notification, subscription, delivery observation, worker, Cron or calendar write.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';
CREATE TABLE public.assistant_reminder_generations(owner uuid PRIMARY KEY,revision bigint NOT NULL DEFAULT 0 CHECK(revision>=0));
CREATE TABLE public.assistant_reminder_commands (
 owner uuid NOT NULL,action_key uuid NOT NULL,task_id uuid NOT NULL,capability_id text NOT NULL,
 kind text NOT NULL CHECK(kind IN ('prepare_reminder','snooze','settings')),
 command_digest text NOT NULL CHECK(command_digest ~ '^[a-f0-9]{64}$'),prepared_ref jsonb NOT NULL,
 binding_revision integer NOT NULL CHECK(binding_revision>0),domain_revision bigint NOT NULL CHECK(domain_revision>=0),
 snapshot_hash text CHECK(snapshot_hash ~ '^[a-f0-9]{64}$'),native_hash text CHECK(native_hash ~ '^[a-f0-9]{64}$'),
 PRIMARY KEY(owner,action_key),FOREIGN KEY(owner,action_key) REFERENCES public.assistant_business_receipts(owner,action_key) DEFERRABLE INITIALLY DEFERRED
);
DO $$ DECLARE relation_name text; BEGIN
 FOREACH relation_name IN ARRAY ARRAY['assistant_reminder_generations','assistant_reminder_commands'] LOOP
  EXECUTE format('ALTER TABLE public.%I OWNER TO assistant_workflow_owner',relation_name);
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',relation_name);
  EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',relation_name);
  EXECUTE format('CREATE POLICY assistant_reminder_owner ON public.%I TO assistant_workflow_owner USING(owner=public.assistant_patient_uid()) WITH CHECK(owner=public.assistant_patient_uid())',relation_name);
  EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner',relation_name);
 END LOOP;
END $$;
GRANT SELECT,INSERT,UPDATE ON public.dose_reminders TO assistant_workflow_owner;
GRANT SELECT ON public.dose_occurrences,public.dose_rules,public.regimen_versions TO assistant_workflow_owner;
CREATE POLICY assistant_reminder_native ON public.dose_reminders TO assistant_workflow_owner USING(patient_id=public.assistant_patient_uid()) WITH CHECK(patient_id=public.assistant_patient_uid());
CREATE POLICY assistant_reminder_occurrence ON public.dose_occurrences FOR SELECT TO assistant_workflow_owner USING(patient_id=public.assistant_patient_uid());
CREATE POLICY assistant_reminder_rule ON public.dose_rules FOR SELECT TO assistant_workflow_owner USING(patient_id=public.assistant_patient_uid());

CREATE FUNCTION public.assistant_reminder_epoch_changed() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid;row_json jsonb;
BEGIN
 row_json:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;o:=coalesce((row_json->>'patient_id')::uuid,(row_json->>'user_id')::uuid);
 IF o IS DISTINCT FROM public.assistant_patient_uid() THEN RAISE EXCEPTION 'Owned reminder epoch required' USING ERRCODE='42501'; END IF;
 INSERT INTO public.assistant_reminder_generations(owner,revision) VALUES(o,1) ON CONFLICT(owner) DO UPDATE SET revision=public.assistant_reminder_generations.revision+1;
 RETURN NULL;
END $$;
DO $$ DECLARE relation_name text; BEGIN
 FOREACH relation_name IN ARRAY ARRAY['dose_reminders','dose_occurrences','dose_rules','regimen_versions','patient_profiles'] LOOP
  EXECUTE format('CREATE TRIGGER assistant_reminder_owner_first BEFORE INSERT OR UPDATE OR DELETE ON public.%I FOR EACH STATEMENT EXECUTE FUNCTION public.assistant_medication_owner_fence()',relation_name);
  EXECUTE format('CREATE TRIGGER assistant_reminder_epoch AFTER INSERT OR UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.assistant_reminder_epoch_changed()',relation_name);
 END LOOP;
END $$;
CREATE FUNCTION public.assistant_reminder_revision() RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=public.assistant_patient_uid();n bigint;
BEGIN
 IF o IS NULL OR public.assistant_patient_role() IS DISTINCT FROM 'authenticated' THEN RAISE EXCEPTION 'Verified owner required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 SELECT coalesce((SELECT g.revision FROM public.assistant_reminder_generations g WHERE g.owner=o),0)
 +coalesce((SELECT g.revision FROM public.assistant_enrollment_generations g WHERE g.owner=o),0) INTO n;
 RETURN jsonb_build_object('revision',n);
END $$;

-- Pure projection, no occurrence generation. Enumerate nearby actual zone
-- offsets and retain only exact wall-time round trips. Fold0 uses the earliest
-- matching instant; gap times have no result. Interval anchors require one.
-- Modern transition, midnight, half-hour and cross-zone cases are target gates;
-- source inventory alone does not establish parity with Python ZoneInfo/tzdata.
CREATE FUNCTION public.assistant_reminder_wall_candidates(p_wall timestamp,p_zone text) RETURNS SETOF timestamptz
LANGUAGE sql STABLE SECURITY INVOKER SET search_path='' AS $$
 WITH base AS (SELECT p_wall AT TIME ZONE p_zone AS instant),offsets AS (
  SELECT DISTINCT (g AT TIME ZONE p_zone)-(g AT TIME ZONE 'UTC') AS delta
  FROM base CROSS JOIN LATERAL generate_series(instant-interval '2 days',instant+interval '2 days',interval '6 hours') g
 ),instants AS (SELECT (p_wall-delta) AT TIME ZONE 'UTC' AS instant FROM offsets)
 SELECT DISTINCT instant FROM instants WHERE instant AT TIME ZONE p_zone=p_wall ORDER BY instant
$$;
CREATE FUNCTION public.assistant_reminder_deadline(p_owner uuid,p_occurrence uuid) RETURNS timestamptz
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE occurrence public.dose_occurrences%ROWTYPE;plan public.regimen_versions%ROWTYPE;rule public.dose_rules%ROWTYPE;
 zone text;day_end timestamptz;next_due timestamptz;candidate timestamptz;first timestamptz;step interval;day date;last_day date;
 wall timestamp;frequency jsonb;hours int;count_candidates int;n bigint;
BEGIN
 IF p_owner IS DISTINCT FROM public.assistant_patient_uid() THEN RAISE EXCEPTION 'Owned dose required' USING ERRCODE='42501'; END IF;
 SELECT * INTO occurrence FROM public.dose_occurrences WHERE patient_id=p_owner AND id=p_occurrence;
 IF NOT FOUND THEN RAISE EXCEPTION 'Existing owned occurrence required' USING ERRCODE='P0002'; END IF;
 SELECT * INTO STRICT plan FROM public.regimen_versions WHERE patient_id=p_owner AND id=occurrence.regimen_id;
 SELECT timezone INTO STRICT zone FROM public.patient_profiles WHERE user_id=p_owner;
 IF plan.state<>'active' OR occurrence.status='closed'
 OR (plan.course_end_date IS NOT NULL AND (clock_timestamp() AT TIME ZONE zone)::date>plan.course_end_date) THEN
  RAISE EXCEPTION 'Open occurrence of a current reviewed course required' USING ERRCODE='40001'; END IF;
 wall:=((occurrence.due_at AT TIME ZONE zone)::date+1)::timestamp;
 SELECT min(x) INTO day_end FROM public.assistant_reminder_wall_candidates(wall,zone) x;
 day_end:=coalesce(day_end,wall AT TIME ZONE zone);frequency:=plan.frequency_rule;
 -- Native planned_instants returns no projection for PRN/unanchored plans.
 -- Preserve that fallback for an already-existing occurrence; create no rows.
 IF plan.is_prn OR plan.effective_from IS NULL THEN RETURN least(occurrence.due_at+interval '2 hours',day_end); END IF;
 IF (SELECT count(*) FROM public.dose_rules WHERE patient_id=p_owner AND regimen_id=plan.id AND enabled AND rule_kind='scheduled')>64 THEN
  RAISE EXCEPTION 'Bounded reminder projection required' USING ERRCODE='22023'; END IF;
 FOR rule IN SELECT * FROM public.dose_rules WHERE patient_id=p_owner AND regimen_id=plan.id AND enabled AND rule_kind='scheduled' LOOP
  IF frequency->>'kind'='interval' THEN
   IF jsonb_typeof(frequency->'every_hours') IS DISTINCT FROM 'number' OR frequency->>'every_hours' !~ '^[0-9]+$'
   OR (frequency->>'every_hours')::int NOT BETWEEN 1 AND 720 OR frequency->'interval_anchor'->>'local_time' IS NULL
   OR frequency->'interval_anchor'->>'local_time' !~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'
   OR frequency->'interval_anchor'->>'local_date' IS NULL THEN RAISE EXCEPTION 'Reviewed interval anchor required' USING ERRCODE='22023'; END IF;
   hours:=(frequency->>'every_hours')::int;step:=make_interval(hours=>hours);
   day:=(frequency->'interval_anchor'->>'local_date')::date;
   IF day::text IS DISTINCT FROM frequency->'interval_anchor'->>'local_date' THEN RAISE EXCEPTION 'ISO interval date required' USING ERRCODE='22023'; END IF;
   wall:=day+(frequency->'interval_anchor'->>'local_time')::time;
   SELECT min(x),count(*) INTO first,count_candidates FROM public.assistant_reminder_wall_candidates(wall,rule.timezone) x;
   IF count_candidates<>1 THEN RAISE EXCEPTION 'Interval anchor is missing or ambiguous' USING ERRCODE='22023'; END IF;
   n:=greatest(0,ceil(extract(epoch FROM (occurrence.due_at-first))/(hours*3600))::bigint);candidate:=first+n*step;
   WHILE candidate<day_end LOOP
    day:=(candidate AT TIME ZONE rule.timezone)::date;
    IF candidate>occurrence.due_at AND candidate>=plan.effective_from AND (plan.effective_to IS NULL OR candidate<plan.effective_to)
    AND (plan.course_start_date IS NULL OR day>=plan.course_start_date) AND (plan.course_end_date IS NULL OR day<=plan.course_end_date) THEN
     next_due:=least(next_due,candidate);EXIT; END IF;
    candidate:=candidate+step;
   END LOOP;
  ELSE
   day:=(occurrence.due_at AT TIME ZONE rule.timezone)::date;last_day:=(day_end AT TIME ZONE rule.timezone)::date;
   WHILE day<=last_day LOOP
    IF coalesce(cardinality(rule.days_of_week),0)=0 OR extract(isodow FROM day)::int=ANY(rule.days_of_week) THEN
     -- The native rule DTO exposes HH:MM, not seconds from an old SQL row.
     wall:=day+left(rule.local_time::text,5)::time;
     SELECT min(x) INTO candidate FROM public.assistant_reminder_wall_candidates(wall,rule.timezone) x;
     IF candidate>occurrence.due_at AND candidate<day_end AND candidate>=plan.effective_from AND (plan.effective_to IS NULL OR candidate<plan.effective_to)
     AND (plan.course_start_date IS NULL OR day>=plan.course_start_date) AND (plan.course_end_date IS NULL OR day<=plan.course_end_date) THEN
      next_due:=least(next_due,candidate); END IF;
    END IF;
    day:=day+1;
   END LOOP;
  END IF;
 END LOOP;
 RETURN least(occurrence.due_at+interval '2 hours',coalesce(next_due,day_end),day_end);
END $$;
CREATE FUNCTION public.assistant_reminder_native_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF NEW.patient_id IS DISTINCT FROM public.assistant_patient_uid() OR NEW.remind_at>=public.assistant_reminder_deadline(NEW.patient_id,NEW.occurrence_id) THEN
  RAISE EXCEPTION 'Reminder cannot cross its original attention deadline' USING ERRCODE='40001'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER assistant_reminder_native BEFORE INSERT OR UPDATE ON public.dose_reminders FOR EACH ROW EXECUTE FUNCTION public.assistant_reminder_native_guard();

CREATE FUNCTION public.assistant_reminder_snapshot(p_owner uuid,p_task jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE f jsonb:=p_task->'fields';prefs jsonb:=public.assistant_settings_preferences(p_owner);current jsonb;occurrence jsonb;deadline timestamptz;
BEGIN
 IF p_owner IS DISTINCT FROM public.assistant_patient_uid() THEN RAISE EXCEPTION 'Owned reminder scope required' USING ERRCODE='42501'; END IF;
 IF f->>'previous_timezone' IS DISTINCT FROM prefs->>'timezone' THEN RAISE EXCEPTION 'Reminder timezone changed' USING ERRCODE='40001'; END IF;
 IF p_task->>'capability_id'='reminder.settings' THEN
  IF NOT coalesce(public.assistant_wf_keys(f,ARRAY['reminders_enabled','reminder_lead_minutes','previous_enabled','previous_lead_minutes','previous_timezone']),false)
  OR jsonb_typeof(f->'reminders_enabled') IS DISTINCT FROM 'boolean' OR jsonb_typeof(f->'reminder_lead_minutes') IS DISTINCT FROM 'number'
  OR f->>'reminder_lead_minutes' !~ '^[0-9]+$' OR (f->>'reminder_lead_minutes')::int NOT BETWEEN 0 AND 120
  OR f->'previous_enabled' IS DISTINCT FROM prefs->'reminders_enabled' OR f->'previous_lead_minutes' IS DISTINCT FROM prefs->'reminder_lead_minutes' THEN
   RAISE EXCEPTION 'Complete current reminder settings required' USING ERRCODE='40001'; END IF;
  RETURN prefs;
 ELSIF p_task->>'capability_id'='reminder.snooze' THEN
  IF NOT coalesce(public.assistant_wf_keys(f,ARRAY['occurrence_id','minutes','previous_remind_at','previous_timezone']),false)
  OR (f->>'occurrence_id')::uuid IS NULL OR jsonb_typeof(f->'minutes') IS DISTINCT FROM 'number' OR f->>'minutes' !~ '^[0-9]+$'
  OR (f->>'minutes')::int NOT BETWEEN 1 AND 1440 THEN RAISE EXCEPTION 'Complete occurrence-bound delay required' USING ERRCODE='22023'; END IF;
  SELECT to_jsonb(x) INTO current FROM public.dose_reminders x WHERE patient_id=p_owner AND occurrence_id=(f->>'occurrence_id')::uuid;
  IF (current->>'remind_at')::timestamptz IS DISTINCT FROM (f->>'previous_remind_at')::timestamptz THEN RAISE EXCEPTION 'Current snooze changed' USING ERRCODE='40001'; END IF;
  deadline:=public.assistant_reminder_deadline(p_owner,(f->>'occurrence_id')::uuid);
  IF clock_timestamp()+make_interval(mins=>(f->>'minutes')::int)>=deadline THEN RAISE EXCEPTION 'Delay reaches the original attention deadline' USING ERRCODE='40001'; END IF;
  SELECT to_jsonb(x) INTO STRICT occurrence FROM public.dose_occurrences x WHERE patient_id=p_owner AND id=(f->>'occurrence_id')::uuid;
  RETURN jsonb_build_object('current',current,'occurrence',occurrence,'timezone',prefs->'timezone','deadline',deadline);
 END IF;
 RAISE EXCEPTION 'Closed reminder capability required' USING ERRCODE='22023';
END $$;
CREATE FUNCTION public.assistant_reminder_result(p_owner uuid,p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE c public.assistant_reminder_commands%ROWTYPE;r public.assistant_business_receipts%ROWTYPE;native jsonb:='null';
BEGIN
 SELECT * INTO STRICT c FROM public.assistant_reminder_commands WHERE owner=p_owner AND action_key=(p_command->'binding'->>'action_key')::uuid;
 SELECT * INTO STRICT r FROM public.assistant_business_receipts WHERE owner=p_owner AND action_key=c.action_key;
 IF c.kind='settings' THEN native:=public.assistant_settings_preferences(p_owner);
 ELSIF c.kind='snooze' THEN SELECT to_jsonb(x) INTO native FROM public.dose_reminders x WHERE patient_id=p_owner AND occurrence_id=(r.business_ref->>'id')::uuid; END IF;
 native:=coalesce(native,'null'::jsonb);
 IF c.kind<>'prepare_reminder' AND c.native_hash IS DISTINCT FROM encode(sha256(convert_to(native::text,'UTF8')),'hex') THEN
  RAISE EXCEPTION 'Actual reminder changed; retain immutable receipt' USING ERRCODE='40001'; END IF;
 RETURN jsonb_build_object('receipt',to_jsonb(r),'result',native);
END $$;
CREATE FUNCTION public.assistant_reminder_apply(p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE o uuid:=public.assistant_patient_uid();kind text:=p_command->>'kind';b jsonb:=p_command->'binding';ref jsonb:=b->'prepared_ref';cap text:=b->>'capability_id';
 tid uuid:=(b->>'task_id')::uuid;aid uuid:=(b->>'action_key')::uuid;rev int:=(b->>'task_revision')::int;preparing boolean:=kind='prepare_reminder';
 t jsonb;ctl jsonb;f jsonb;v jsonb:=p_command->'values';snapshot text;digest text;generation bigint;native jsonb:='null';outref jsonb;child jsonb;allowed text[];
 prior public.assistant_reminder_commands%ROWTYPE;prep public.assistant_reminder_commands%ROWTYPE;
BEGIN
 IF o IS NULL OR public.assistant_patient_role() IS DISTINCT FROM 'authenticated' THEN RAISE EXCEPTION 'Verified owner required' USING ERRCODE='42501'; END IF;
 allowed:=CASE kind WHEN 'prepare_reminder' THEN ARRAY['kind','binding'] WHEN 'snooze' THEN ARRAY['kind','binding','values','confirmed']
 WHEN 'settings' THEN ARRAY['kind','binding','values','previous_enabled','previous_lead_minutes','previous_timezone','confirmed'] END;
 IF allowed IS NULL OR NOT coalesce(public.assistant_wf_keys(p_command,allowed) AND p_command ?& allowed,false) OR octet_length(p_command::text)>4096
 OR NOT coalesce(public.assistant_wf_keys(b,ARRAY['task_id','task_revision','capability_id','action_key','prepared_ref','expected_domain_revision','run_binding']),false)
 OR NOT coalesce(public.assistant_wf_keys(ref,ARRAY['kind','id','version']),false) OR tid IS NULL OR aid IS NULL OR rev IS NULL OR rev<1
 OR cap NOT IN ('reminder.snooze','reminder.settings') OR ref->>'kind' IS DISTINCT FROM 'reminder_review' OR ref->'version' IS DISTINCT FROM '1'::jsonb OR (ref->>'id')::uuid IS NULL
 OR (NOT preparing AND p_command->'confirmed' IS DISTINCT FROM 'true'::jsonb) THEN RAISE EXCEPTION 'Closed independently confirmed reminder command required' USING ERRCODE='22023'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));digest:=encode(sha256(convert_to(p_command::text,'UTF8')),'hex');
 SELECT * INTO prior FROM public.assistant_reminder_commands WHERE owner=o AND action_key=aid;
 IF FOUND THEN
  IF prior.command_digest IS DISTINCT FROM digest THEN RAISE EXCEPTION 'Reminder action reused' USING ERRCODE='23505'; END IF;
  RETURN jsonb_build_object('result',public.assistant_reminder_result(o,p_command),'replayed',true); END IF;
 IF EXISTS(SELECT 1 FROM public.assistant_business_receipts WHERE owner=o AND action_key=aid) THEN RAISE EXCEPTION 'Action belongs to another domain' USING ERRCODE='23505'; END IF;
 SELECT data INTO t FROM public.assistant_workflow_tasks WHERE owner=o AND id=tid FOR UPDATE;
 SELECT data INTO ctl FROM public.assistant_workflow_operations WHERE owner=o AND task_id=tid AND id=tid AND record_type='control' FOR UPDATE;
 generation:=(public.assistant_reminder_revision()->>'revision')::bigint;
 IF t IS NULL OR ctl IS NULL OR t->>'capability_id' IS DISTINCT FROM cap OR ctl->>'capability_id' IS DISTINCT FROM cap
 OR (t->>'revision')::int IS DISTINCT FROM rev OR (ctl->>'revision')::int IS DISTINCT FROM rev OR t->>'save_mode' IS DISTINCT FROM 'allowed'
 OR ctl->>'mode' IS DISTINCT FROM 'allowed' OR ctl->'revoked' IS DISTINCT FROM 'false'::jsonb OR ctl->>'status' IS DISTINCT FROM 'idle'
 OR jsonb_array_length(t->'attachment_ids')<>0 OR generation IS DISTINCT FROM (b->>'expected_domain_revision')::bigint THEN
  RAISE EXCEPTION 'Current saved reminder scope changed' USING ERRCODE='40001'; END IF;
 IF nullif(b->'run_binding','null'::jsonb) IS NOT NULL THEN PERFORM public.assistant_run_assert_current(o,b->'run_binding'); END IF;
 f:=t->'fields';snapshot:=encode(sha256(convert_to(public.assistant_reminder_snapshot(o,t)::text,'UTF8')),'hex');
 IF preparing THEN
  SELECT * INTO prep FROM public.assistant_reminder_commands cmd WHERE owner=o AND task_id=tid AND cmd.kind='prepare_reminder' AND prepared_ref=t->'business_refs'->0;
  IF ref->>'id' IS DISTINCT FROM aid::text OR EXISTS(SELECT 1 FROM public.assistant_workflow_operations WHERE owner=o AND record_type='action' AND id=aid)
  OR NOT(t->>'state'='ready_for_review' OR (t->>'state'='awaiting_confirmation' AND prep.owner IS NOT NULL
   AND (prep.binding_revision<rev OR prep.domain_revision<>generation OR prep.snapshot_hash IS DISTINCT FROM snapshot))) THEN
   RAISE EXCEPTION 'Prepare a fresh reminder review' USING ERRCODE='40001'; END IF;
  INSERT INTO public.assistant_workflow_operations(owner,record_type,id,task_id,data) VALUES(o,'action',aid,tid,jsonb_build_object('owner',o,'action_key',aid,'task_id',tid,
   'capability_id',cap,'binding_revision',rev,'state','succeeded','business_ref',ref,'safe_reason','reminder_prepared',
   'clinical_revision',coalesce((SELECT g.revision FROM public.assistant_enrollment_generations g WHERE g.owner=o),0),'updated_at',clock_timestamp()));outref:=ref;
 ELSE
  SELECT * INTO prep FROM public.assistant_reminder_commands cmd WHERE owner=o AND task_id=tid AND action_key=(ref->>'id')::uuid AND cmd.kind='prepare_reminder';
  IF t->>'state' IS DISTINCT FROM 'awaiting_confirmation' OR t->'business_refs' IS DISTINCT FROM jsonb_build_array(ref) OR prep.owner IS NULL
  OR prep.binding_revision<>rev OR prep.domain_revision<>generation OR prep.snapshot_hash IS DISTINCT FROM snapshot
  OR kind IS DISTINCT FROM (CASE cap WHEN 'reminder.snooze' THEN 'snooze' ELSE 'settings' END) THEN RAISE EXCEPTION 'Actual reminder preparation changed' USING ERRCODE='40001'; END IF;
  IF kind='snooze' THEN
   IF NOT coalesce(public.assistant_wf_keys(v,ARRAY['occurrence_id','minutes','previous_remind_at','previous_timezone']),false)
   OR v->'occurrence_id' IS DISTINCT FROM f->'occurrence_id' OR v->'minutes' IS DISTINCT FROM f->'minutes' OR v->'previous_timezone' IS DISTINCT FROM f->'previous_timezone'
   OR (v->>'previous_remind_at')::timestamptz IS DISTINCT FROM (f->>'previous_remind_at')::timestamptz THEN RAISE EXCEPTION 'Confirm exact occurrence and previous snooze' USING ERRCODE='40001'; END IF;
   INSERT INTO public.dose_reminders(patient_id,occurrence_id,remind_at) VALUES(o,(f->>'occurrence_id')::uuid,clock_timestamp()+make_interval(mins=>(f->>'minutes')::int))
   ON CONFLICT(patient_id,occurrence_id) DO UPDATE SET remind_at=EXCLUDED.remind_at;
   SELECT to_jsonb(x) INTO STRICT native FROM public.dose_reminders x WHERE patient_id=o AND occurrence_id=(f->>'occurrence_id')::uuid;
   outref:=jsonb_build_object('kind','dose_occurrence','id',f->'occurrence_id','version',NULL);
  ELSE
   IF v IS DISTINCT FROM jsonb_build_object('reminders_enabled',f->'reminders_enabled','reminder_lead_minutes',f->'reminder_lead_minutes')
   OR p_command->'previous_enabled' IS DISTINCT FROM f->'previous_enabled' OR p_command->'previous_lead_minutes' IS DISTINCT FROM f->'previous_lead_minutes'
   OR p_command->'previous_timezone' IS DISTINCT FROM f->'previous_timezone' THEN RAISE EXCEPTION 'Confirm exact reminder settings and previous state' USING ERRCODE='40001'; END IF;
   UPDATE public.patient_profiles SET reminders_enabled=(v->>'reminders_enabled')::boolean,reminder_lead_minutes=(v->>'reminder_lead_minutes')::int WHERE user_id=o;
   native:=public.assistant_settings_preferences(o);outref:=jsonb_build_object('kind','preference','id',o,'version',NULL);
  END IF;
 END IF;
 IF nullif(b->'run_binding','null'::jsonb) IS NOT NULL THEN PERFORM public.assistant_run_assert_current(o,b->'run_binding'); END IF;
 child:=public.assistant_workflow_command_legacy_035('task_cas',jsonb_build_object('task_id',tid,'expected_revision',rev,'event_id',aid,'request_digest',digest,
  'update',jsonb_build_object('state',CASE WHEN preparing THEN 'awaiting_confirmation' ELSE 'completed' END,'save_mode','allowed','storage_state','saved',
   'fields',f,'missing_fields','[]'::jsonb,'attachment_ids','[]'::jsonb,'business_refs',jsonb_build_array(outref))));
 IF child ? 'error' THEN RAISE EXCEPTION 'Task changed after native reminder publication' USING ERRCODE='40001'; END IF;
 generation:=(public.assistant_reminder_revision()->>'revision')::bigint;
 INSERT INTO public.assistant_business_receipts(owner,action_key,task_id,capability_id,binding_revision,business_ref,domain_revision,outcome)
 VALUES(o,aid,tid,cap,rev+1,outref,generation,CASE WHEN preparing THEN 'prepared' ELSE 'applied' END);
 INSERT INTO public.assistant_reminder_commands(owner,action_key,task_id,capability_id,kind,command_digest,prepared_ref,binding_revision,domain_revision,snapshot_hash,native_hash)
 VALUES(o,aid,tid,cap,kind,digest,ref,rev+1,generation,CASE WHEN preparing THEN snapshot END,CASE WHEN NOT preparing THEN encode(sha256(convert_to(native::text,'UTF8')),'hex') END);
 RETURN jsonb_build_object('result',public.assistant_reminder_result(o,p_command),'replayed',false);
END $$;
CREATE FUNCTION public.assistant_reminder_prepare(p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$ BEGIN
 IF p_command->>'kind' IS DISTINCT FROM 'prepare_reminder' THEN RETURN jsonb_build_object('error','invalid'); END IF;
 RETURN public.assistant_reminder_apply(p_command);
EXCEPTION WHEN SQLSTATE '40001' THEN RETURN jsonb_build_object('error','stale'); WHEN SQLSTATE 'P0002' THEN RETURN jsonb_build_object('error','not_found');
 WHEN unique_violation THEN RETURN jsonb_build_object('error','duplicate'); WHEN invalid_parameter_value OR invalid_text_representation OR check_violation OR not_null_violation OR datetime_field_overflow OR invalid_datetime_format THEN RETURN jsonb_build_object('error','invalid'); END $$;
CREATE FUNCTION public.assistant_reminder_write(p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$ BEGIN
 IF p_command->>'kind' IS NOT DISTINCT FROM 'prepare_reminder' THEN RETURN jsonb_build_object('error','invalid'); END IF;
 RETURN public.assistant_reminder_apply(p_command);
EXCEPTION WHEN SQLSTATE '40001' THEN RETURN jsonb_build_object('error','stale'); WHEN SQLSTATE 'P0002' THEN RETURN jsonb_build_object('error','not_found');
 WHEN unique_violation THEN RETURN jsonb_build_object('error','duplicate'); WHEN invalid_parameter_value OR invalid_text_representation OR check_violation OR not_null_violation OR datetime_field_overflow OR invalid_datetime_format THEN RETURN jsonb_build_object('error','invalid'); END $$;
CREATE FUNCTION public.assistant_reminder_read(p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=public.assistant_patient_uid();c public.assistant_reminder_commands%ROWTYPE;
BEGIN
 IF o IS NULL OR public.assistant_patient_role() IS DISTINCT FROM 'authenticated' THEN RAISE EXCEPTION 'Verified owner required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 SELECT * INTO c FROM public.assistant_reminder_commands WHERE owner=o AND action_key=(p_command->'binding'->>'action_key')::uuid;
 IF NOT FOUND THEN RETURN jsonb_build_object('error','not_found'); END IF;
 IF c.command_digest IS DISTINCT FROM encode(sha256(convert_to(p_command::text,'UTF8')),'hex') THEN RETURN jsonb_build_object('error','duplicate'); END IF;
 RETURN jsonb_build_object('result',public.assistant_reminder_result(o,p_command),'replayed',true);
EXCEPTION WHEN SQLSTATE '40001' THEN RETURN jsonb_build_object('error','stale'); WHEN SQLSTATE 'P0002' THEN RETURN jsonb_build_object('error','stale'); END $$;
DO $$ DECLARE signature text; BEGIN
 FOREACH signature IN ARRAY ARRAY['assistant_reminder_epoch_changed()','assistant_reminder_revision()','assistant_reminder_wall_candidates(timestamp,text)',
 'assistant_reminder_deadline(uuid,uuid)','assistant_reminder_native_guard()','assistant_reminder_snapshot(uuid,jsonb)','assistant_reminder_result(uuid,jsonb)',
 'assistant_reminder_apply(jsonb)','assistant_reminder_prepare(jsonb)','assistant_reminder_write(jsonb)','assistant_reminder_read(jsonb)'] LOOP
  EXECUTE 'ALTER FUNCTION public.'||signature||' OWNER TO assistant_workflow_owner';
  EXECUTE 'REVOKE ALL ON FUNCTION public.'||signature||' FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner';
 END LOOP;
END $$;
GRANT EXECUTE ON FUNCTION public.assistant_reminder_revision(),public.assistant_reminder_prepare(jsonb),public.assistant_reminder_write(jsonb),public.assistant_reminder_read(jsonb) TO authenticated;
COMMIT;
