-- REVIEW ONLY / NOT APPLIED. Requires035/036 and metadata/messages/runs/originals candidates.
-- No provisioning, Storage HTTP, providers, scheduling or feature enablement.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';

CREATE TABLE public.assistant_medication_commands (
 owner uuid NOT NULL REFERENCES public.patient_profiles(user_id), action_key uuid NOT NULL,
 task_id uuid NOT NULL, binding_revision integer NOT NULL CHECK(binding_revision>0),
 kind text NOT NULL CHECK(kind IN ('prepare','review_source','review_identity','request_challenge','activate',
 'change_plan','end_plan','delete_draft','prepare_maintenance','prepare_source','save_source','review_registration')),
 command_digest text NOT NULL CHECK(command_digest ~ '^[a-f0-9]{64}$'),
 native_result_id uuid, state text NOT NULL CHECK(state IN ('pending','applied')),
 PRIMARY KEY(owner,action_key),
 FOREIGN KEY(owner,action_key) REFERENCES public.assistant_business_receipts(owner,action_key)
 DEFERRABLE INITIALLY DEFERRED
);
ALTER TABLE public.assistant_medication_commands OWNER TO assistant_workflow_owner;
ALTER TABLE public.assistant_medication_commands ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assistant_medication_commands FORCE ROW LEVEL SECURITY;
CREATE POLICY assistant_medication_command_owner ON public.assistant_medication_commands TO assistant_workflow_owner
 USING(owner=auth.uid()) WITH CHECK(owner=auth.uid());
REVOKE ALL ON public.assistant_medication_commands FROM PUBLIC,anon,authenticated,service_role,
 assistant_evidence_login,assistant_evidence_owner;

ALTER TABLE public.assistant_enrollment_operations
 ADD COLUMN attachment_ids uuid[] NOT NULL DEFAULT '{}' CHECK(cardinality(attachment_ids)<=10),
 ADD COLUMN source_candidate_index integer CHECK(source_candidate_index BETWEEN 0 AND 19);
CREATE TABLE public.assistant_enrollment_originals (
 owner uuid NOT NULL, attachment_id uuid NOT NULL, action_key uuid NOT NULL,
 PRIMARY KEY(owner,attachment_id),
 FOREIGN KEY(owner,action_key) REFERENCES public.assistant_enrollment_operations(owner,action_key)
);
ALTER TABLE public.assistant_enrollment_originals OWNER TO assistant_workflow_owner;
ALTER TABLE public.assistant_enrollment_originals ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assistant_enrollment_originals FORCE ROW LEVEL SECURITY;
CREATE POLICY assistant_enrollment_original_internal ON public.assistant_enrollment_originals TO assistant_workflow_owner
 USING(owner=auth.uid()) WITH CHECK(owner=auth.uid());
CREATE POLICY assistant_enrollment_original_patient ON public.assistant_enrollment_originals FOR SELECT TO authenticated
 USING(owner=(SELECT auth.uid()));
REVOKE ALL ON public.assistant_enrollment_originals FROM PUBLIC,anon,authenticated,service_role,
 assistant_evidence_login,assistant_evidence_owner;
GRANT SELECT ON public.assistant_enrollment_originals TO authenticated;
GRANT SELECT,INSERT,UPDATE ON public.assistant_enrollment_operations,public.assistant_enrollment_generations
 TO assistant_workflow_owner;
CREATE POLICY assistant_enrollment_operation_command ON public.assistant_enrollment_operations TO assistant_workflow_owner
 USING(owner=auth.uid()) WITH CHECK(owner=auth.uid());
CREATE POLICY assistant_enrollment_generation_command ON public.assistant_enrollment_generations TO assistant_workflow_owner
 USING(owner=auth.uid()) WITH CHECK(owner=auth.uid());

-- Explicit normal-command owner only. The verifier receives no clinical grants.
GRANT SELECT,INSERT,UPDATE ON public.source_documents,public.source_fields,public.patient_medications,
 public.regimen_versions,public.confirmation_challenges TO assistant_workflow_owner;
GRANT SELECT ON public.agent_sessions,public.patient_profiles,public.medication_evidence_tasks,
 public.medication_images,public.medication_source_links,public.draft_deletion_receipts TO assistant_workflow_owner;
GRANT INSERT,UPDATE ON public.medication_evidence_tasks,public.medication_images,public.medication_source_links
 TO assistant_workflow_owner;
DO $$ DECLARE relation_name text; BEGIN
 FOREACH relation_name IN ARRAY ARRAY['source_documents','source_fields','patient_medications','regimen_versions',
 'confirmation_challenges','agent_sessions','medication_evidence_tasks','medication_images','medication_source_links',
 'draft_deletion_receipts'] LOOP
  EXECUTE format('CREATE POLICY assistant_medication_owned_command ON public.%I TO assistant_workflow_owner USING(patient_id=auth.uid()) WITH CHECK(patient_id=auth.uid())',relation_name);
 END LOOP;
END $$;
CREATE POLICY assistant_medication_profile_read ON public.patient_profiles FOR SELECT TO assistant_workflow_owner
 USING(user_id=auth.uid());

-- BEFORE STATEMENT is deliberate:036 BEFORE ROW hooks are too late to acquire
-- the owner fence before a legacy UPDATE has acquired its clinical row lock.
CREATE FUNCTION public.assistant_medication_owner_fence() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF auth.uid() IS NOT NULL THEN
  PERFORM pg_advisory_xact_lock(hashtextextended(auth.uid()::text,35035));
 END IF;
 RETURN NULL;
END $$;
ALTER FUNCTION public.assistant_medication_owner_fence() OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_medication_owner_fence() FROM PUBLIC,anon,authenticated,service_role,
 assistant_evidence_login,assistant_evidence_owner;
DO $$ DECLARE relation_name text; BEGIN
 FOREACH relation_name IN ARRAY ARRAY['source_documents','source_fields','patient_medications','regimen_versions',
 'confirmation_challenges','medication_evidence_tasks','medication_images','medication_source_links'] LOOP
  EXECUTE format('CREATE TRIGGER assistant_medication_owner_first BEFORE INSERT OR UPDATE OR DELETE ON public.%I FOR EACH STATEMENT EXECUTE FUNCTION public.assistant_medication_owner_fence()',relation_name);
 END LOOP;
END $$;

-- These legacy functions lock profile/domain rows before their first DML.
-- Preserve native signatures and policy, adding the shared owner fence first.
ALTER FUNCTION public.activate_medication_regimen_version(uuid,uuid,text) RENAME TO assistant_medication_activate_legacy_030;
REVOKE ALL ON FUNCTION public.assistant_medication_activate_legacy_030(uuid,uuid,text)
 FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;
GRANT EXECUTE ON FUNCTION public.assistant_medication_activate_legacy_030(uuid,uuid,text) TO assistant_workflow_owner;
CREATE FUNCTION public.activate_medication_regimen_version(p_regimen_id uuid,p_challenge_id uuid,p_timezone text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=auth.uid(); binding public.assistant_enrollment_operations%ROWTYPE; task jsonb;
BEGIN
 IF o IS NULL OR auth.role() IS DISTINCT FROM 'authenticated' THEN RAISE EXCEPTION 'Verified patient required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 SELECT * INTO binding FROM public.assistant_enrollment_operations WHERE owner=o AND regimen_id=p_regimen_id;
 IF FOUND THEN
  SELECT data INTO task FROM public.assistant_workflow_tasks WHERE owner=o AND id=binding.workflow_task_id;
  IF task IS NULL OR NOT EXISTS(SELECT 1 FROM public.assistant_medication_commands c
   WHERE c.owner=o AND c.task_id=binding.workflow_task_id AND c.kind='request_challenge'
   AND c.native_result_id=p_challenge_id AND c.state='applied'
   AND c.binding_revision=(task->>'revision')::integer) THEN
   RAISE EXCEPTION 'Request a new independent confirmation for the current task' USING ERRCODE='40001'; END IF;
 END IF;
 RETURN public.assistant_medication_activate_legacy_030(p_regimen_id,p_challenge_id,p_timezone);
END $$;
ALTER FUNCTION public.activate_medication_regimen_version(uuid,uuid,text) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.activate_medication_regimen_version(uuid,uuid,text) FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION public.activate_medication_regimen_version(uuid,uuid,text) TO authenticated;

ALTER FUNCTION public.delete_unconfirmed_medication(text,uuid,boolean) RENAME TO assistant_medication_delete_legacy_027;
REVOKE ALL ON FUNCTION public.assistant_medication_delete_legacy_027(text,uuid,boolean)
 FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;
GRANT EXECUTE ON FUNCTION public.assistant_medication_delete_legacy_027(text,uuid,boolean) TO assistant_workflow_owner;
CREATE FUNCTION public.delete_unconfirmed_medication(p_kind text,p_id uuid,p_confirmed boolean) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF auth.uid() IS NULL OR auth.role() IS DISTINCT FROM 'authenticated' OR p_confirmed IS DISTINCT FROM true THEN
  RAISE EXCEPTION 'Verified explicit patient confirmation required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(auth.uid()::text,35035));
 -- Existing native history, FK and reviewed-source protections still apply.
 RETURN public.assistant_medication_delete_legacy_027(p_kind,p_id,p_confirmed);
END $$;
ALTER FUNCTION public.delete_unconfirmed_medication(text,uuid,boolean) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.delete_unconfirmed_medication(text,uuid,boolean) FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION public.delete_unconfirmed_medication(text,uuid,boolean) TO authenticated;

CREATE FUNCTION public.assistant_medication_projection(p_value jsonb,p_kind text) RETURNS jsonb
LANGUAGE sql IMMUTABLE SECURITY INVOKER SET search_path='' AS $$
 SELECT jsonb_object_agg(key,value) FROM jsonb_each(p_value) WHERE key=ANY(CASE p_kind
 WHEN 'regimen' THEN ARRAY['id','patient_id','patient_medication_id','source_id','version_no','state','dose_amount','dose_unit',
 'frequency_rule','is_prn','route','food_instruction','effective_from','effective_to','course_start_date','course_end_date',
 'patient_edited','supersedes_id','confirmation_challenge_id','created_at','evidence_task_id','demo_only']
 WHEN 'source' THEN ARRAY['id','patient_id','source_kind','review_status','reviewed_at','dose_basis','extraction_evidence','demo_only']
 WHEN 'challenge' THEN ARRAY['id','patient_id','session_id','session_state_version','action','regimen_id','occurrence_id',
 'intended_intake_status','idempotency_key','token_hash','issued_at','expires_at','confirmed_at','consumed_at']
 WHEN 'enrollment' THEN ARRAY['workflow_task_id','version_no','binding_digest','regimen_id','medication_id','source_id',
 'attachment_ids','source_candidate_index'] ELSE ARRAY[]::text[] END)
$$;
ALTER FUNCTION public.assistant_medication_projection(jsonb,text) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_medication_projection(jsonb,text) FROM PUBLIC,anon,authenticated,service_role,
 assistant_evidence_login,assistant_evidence_owner;

CREATE FUNCTION public.assistant_medication_rule_matches(p_rule jsonb,p_input jsonb,p_start text) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SECURITY INVOKER SET search_path='' AS $$
DECLARE times jsonb; clock_time text; anchor jsonb;
BEGIN
 IF nullif(p_rule,'null'::jsonb) IS NULL OR nullif(p_input,'null'::jsonb) IS NULL THEN
  RETURN nullif(p_rule,'null'::jsonb) IS NOT DISTINCT FROM nullif(p_input,'null'::jsonb); END IF;
 IF p_input->>'kind'<>'interval' THEN RETURN jsonb_strip_nulls(p_rule)=jsonb_strip_nulls(p_input); END IF;
 times:=coalesce(p_input->'local_times','[]'::jsonb);
 IF jsonb_typeof(times)<>'array' OR jsonb_array_length(times)>1 OR p_start IS NULL THEN RETURN false; END IF;
 clock_time:=CASE WHEN jsonb_array_length(times)=0 THEN '08:00'
 ELSE to_char((times->>0)::time,'HH24:MI') END;
 anchor:=jsonb_build_object('local_date',p_start,'local_time',clock_time,
 'time_source',CASE WHEN jsonb_array_length(times)=0 THEN 'default_0800' ELSE 'patient_entered' END);
 RETURN p_rule->>'kind'='interval' AND p_rule->'every_hours'=p_input->'every_hours'
 AND p_rule->'local_times'=jsonb_build_array(clock_time) AND p_rule->'interval_anchor'=anchor;
EXCEPTION WHEN invalid_datetime_format OR datetime_field_overflow THEN RETURN false;
END $$;
ALTER FUNCTION public.assistant_medication_rule_matches(jsonb,jsonb,text) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_medication_rule_matches(jsonb,jsonb,text) FROM PUBLIC,anon,authenticated,service_role;

CREATE FUNCTION public.assistant_medication_printed_matches(p_draft jsonb,p_parts jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SECURITY INVOKER SET search_path='' AS $$
DECLARE capture text[]; printed text[]:='{}'; entered text[]; hour integer; clock_time text; rule jsonb:=p_draft->'frequency_rule';
BEGIN
 IF p_parts IS NULL OR p_parts='null'::jsonb THEN RETURN true; END IF;
 FOR capture IN SELECT regexp_matches(p_parts->>'text',
 '(?:\mat[[:space:]]+|[在于][[:space:]]*)([01]?[0-9]|2[0-3]):([0-5][0-9])(?![0-9])(?:[[:space:]]*([ap])\.?m\.?)?','gi') LOOP
  hour:=capture[1]::int;
  IF capture[3] IS NOT NULL THEN
   IF hour NOT BETWEEN 1 AND 12 THEN RETURN false; END IF;
   hour:=hour%12+CASE WHEN lower(capture[3])='p' THEN 12 ELSE 0 END;
  END IF;
  printed:=array_append(printed,lpad(hour::text,2,'0')||':'||capture[2]);
 END LOOP;
 IF cardinality(printed)>0 AND coalesce((p_parts->>'as_needed')::boolean,false)=false THEN
  SELECT coalesce(array_agg(DISTINCT value ORDER BY value),'{}') INTO entered FROM jsonb_array_elements_text(rule->'local_times');
  IF NOT (entered @> printed AND printed @> entered) THEN RETURN false; END IF;
 END IF;
 IF p_parts->'dose'->>'amount_max' IS NOT NULL THEN RETURN false; END IF;
 IF p_parts->'dose'->>'amount' IS NOT NULL AND
 ((p_draft->>'dose_amount')::numeric IS DISTINCT FROM (p_parts->'dose'->>'amount')::numeric
 OR p_parts->'dose'->>'unit' IS NOT NULL AND p_draft->>'dose_unit' IS DISTINCT FROM p_parts->'dose'->>'unit') THEN RETURN false; END IF;
 IF coalesce((p_parts->>'as_needed')::boolean,false) AND p_draft->>'is_prn' IS DISTINCT FROM 'true' THEN RETURN false; END IF;
 IF p_parts->>'food' IS NOT NULL AND lower(btrim(coalesce(p_draft->>'food_instruction','')))
 <>replace(p_parts->>'food','_',' ') THEN RETURN false; END IF;
 IF p_parts->>'every_hours' IS NOT NULL AND NOT coalesce((p_parts->>'as_needed')::boolean,false) THEN
  IF rule->>'kind' IS DISTINCT FROM 'interval' OR (rule->>'every_hours')::numeric IS DISTINCT FROM (p_parts->>'every_hours')::numeric
  OR jsonb_array_length(rule->'local_times')>1 OR p_draft->>'course_start_date' IS NULL THEN RETURN false; END IF;
 ELSIF p_parts->>'times_per_day' IS NOT NULL AND NOT coalesce((p_parts->>'as_needed')::boolean,false) THEN
  IF coalesce((p_draft->>'is_prn')::boolean,false) OR rule->>'kind' IS DISTINCT FROM 'daily'
  OR jsonb_array_length(rule->'local_times') IS DISTINCT FROM (p_parts->>'times_per_day')::integer THEN RETURN false; END IF;
 END IF;
 RETURN true;
END $$;
ALTER FUNCTION public.assistant_medication_printed_matches(jsonb,jsonb) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_medication_printed_matches(jsonb,jsonb) FROM PUBLIC,anon,authenticated,service_role;

-- Narrow independent name-only review of the product's original source. A
-- transaction-local pending fixed command is required; arbitrary GUCs grant nothing.
CREATE OR REPLACE FUNCTION public.assistant_enrollment_review_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE rid uuid; sid uuid;
BEGIN
 IF TG_TABLE_NAME='source_fields' THEN
 IF NEW.field_name='medication_name' AND TG_OP='UPDATE'
 AND NEW.patient_id=OLD.patient_id AND NEW.source_id=OLD.source_id AND NEW.id=OLD.id
 AND NEW.field_value=OLD.field_value AND OLD.review_status='extracted' AND NEW.review_status='user_reviewed'
 AND EXISTS(SELECT 1 FROM public.assistant_medication_commands cmd
 JOIN public.assistant_workflow_tasks t ON t.owner=cmd.owner AND t.id=cmd.task_id
 JOIN public.assistant_workflow_operations ctl ON ctl.owner=cmd.owner AND ctl.task_id=cmd.task_id AND ctl.record_type='control'
 JOIN public.regimen_versions r ON r.patient_id=cmd.owner AND r.id=cmd.native_result_id
 JOIN public.patient_medications m ON m.patient_id=r.patient_id AND m.id=r.patient_medication_id
 WHERE cmd.owner=NEW.patient_id AND cmd.kind='review_identity' AND cmd.state='pending'
 AND cmd.binding_revision=(t.data->>'revision')::int AND t.data->>'state'='awaiting_confirmation'
 AND ctl.data->>'mode'='allowed' AND ctl.data->>'revoked'='false' AND ctl.data->>'status'='idle'
 AND t.data->'business_refs' @> jsonb_build_array(jsonb_build_object('kind','regimen','id',r.id,'version',r.version_no))
 AND m.source_id=NEW.source_id AND NEW.field_value=to_jsonb(m.display_name)) THEN RETURN NEW; END IF;
 END IF;
 IF TG_TABLE_NAME='confirmation_challenges' THEN
  IF NEW.action='activate_regimen' THEN PERFORM public.assistant_enrollment_assert_current(NEW.patient_id,NEW.regimen_id); END IF;
 ELSIF TG_TABLE_NAME='regimen_versions' THEN
  IF NEW.state='active' THEN PERFORM public.assistant_enrollment_assert_current(NEW.patient_id,NEW.id); END IF;
 ELSE
  sid:=CASE WHEN TG_TABLE_NAME='source_documents' THEN NEW.id ELSE NEW.source_id END;
  FOR rid IN SELECT regimen_id FROM public.assistant_enrollment_operations WHERE owner=NEW.patient_id AND source_id=sid LOOP
   PERFORM public.assistant_enrollment_assert_current(NEW.patient_id,rid);
  END LOOP;
 END IF;
 RETURN NEW;
END $$;
-- Keep036's original function ownership/ACL. Actual target inspection is mandatory.

CREATE FUNCTION public.assistant_medication_prepared_fields(p_prepared jsonb,p_expected jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SECURITY INVOKER SET search_path='' AS $$
DECLARE r jsonb:=p_prepared->'result'->'regimen'; s jsonb:=p_prepared->'source'; m jsonb:=p_prepared->'result'->'medication';
 f jsonb; actual jsonb; expected jsonb; name text;
BEGIN
 IF NOT public.assistant_wf_keys(p_prepared,ARRAY['workflow_revision','source_candidate_index','attachment_ids',
 'workflow_task_id','source','result','create_medication','already_persisted'])
 OR NOT public.assistant_wf_keys(p_prepared->'result',ARRAY['medication','regimen','source_fields','missing_instructions'])
 OR r->>'state' NOT IN ('draft','pending_clarification') OR r->>'effective_from' IS NOT NULL
 OR r->>'effective_to' IS NOT NULL OR r->>'confirmation_challenge_id' IS NOT NULL
 OR s->>'review_status' IS DISTINCT FROM 'extracted' OR s->>'reviewed_at' IS NOT NULL
 OR r->>'source_id' IS DISTINCT FROM s->>'id' OR r->>'patient_medication_id' IS DISTINCT FROM m->>'id'
 OR jsonb_typeof(p_prepared->'result'->'source_fields') IS DISTINCT FROM 'array'
 OR jsonb_array_length(p_prepared->'result'->'source_fields')>20 THEN RETURN false; END IF;
 FOREACH name IN ARRAY ARRAY['dose_amount','dose_unit','route','food_instruction','course_start_date','course_end_date'] LOOP
  IF nullif(r->name,'null'::jsonb) IS DISTINCT FROM nullif(p_expected->name,'null'::jsonb) THEN RETURN false; END IF;
 END LOOP;
 IF coalesce((r->>'is_prn')::boolean,false) IS DISTINCT FROM coalesce((p_expected->>'is_prn')::boolean,false)
 OR NOT public.assistant_medication_rule_matches(r->'frequency_rule',p_expected->'frequency_rule',p_expected->>'course_start_date') THEN RETURN false; END IF;
 expected:=jsonb_build_object('medication_name',m->'display_name');
 FOREACH name IN ARRAY ARRAY['dose_amount','dose_unit','frequency_rule','route','food_instruction','course_start_date','course_end_date'] LOOP
  IF r->>name IS NOT NULL THEN expected:=expected||jsonb_build_object(name,r->name); END IF;
 END LOOP;
 IF r->>'is_prn'='true' THEN expected:=expected||jsonb_build_object('is_prn',true); END IF;
 IF coalesce(s->'dose_basis'->>'strength_text','')<>'' THEN expected:=expected||jsonb_build_object('strength',s->'dose_basis'->'strength_text'); END IF;
 IF s->'dose_basis'->>'form' IS NOT NULL AND s->'dose_basis'->>'form'<>'unknown' THEN expected:=expected||jsonb_build_object('form',s->'dose_basis'->'form'); END IF;
 actual:='{}'::jsonb;
 FOR f IN SELECT value FROM jsonb_array_elements(p_prepared->'result'->'source_fields') LOOP
  IF f->>'source_id' IS DISTINCT FROM s->>'id' OR f->>'patient_id' IS DISTINCT FROM s->>'patient_id'
  OR f->>'review_status' IS DISTINCT FROM 'extracted' OR f->>'reviewed_at' IS NOT NULL
  OR (f->>'field_name') IS NULL OR actual ? (f->>'field_name') THEN RETURN false; END IF;
  actual:=actual||jsonb_build_object(f->>'field_name',f->'field_value');
 END LOOP;
 RETURN actual=expected;
END $$;
ALTER FUNCTION public.assistant_medication_prepared_fields(jsonb,jsonb) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_medication_prepared_fields(jsonb,jsonb) FROM PUBLIC,anon,authenticated,service_role;

CREATE FUNCTION public.assistant_medication_native_enrollment(p_owner uuid,p_binding jsonb,p_prepared jsonb,
 p_expected jsonb,p_digest text) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE s jsonb:=p_prepared->'source'; m jsonb:=p_prepared->'result'->'medication';
 r jsonb:=p_prepared->'result'->'regimen'; f jsonb; sid uuid; mid uuid; rid uuid; attachment uuid;
 already boolean; current_row public.regimen_versions%ROWTYPE; new_version integer; clinical_revision bigint;
BEGIN
 IF auth.uid() IS DISTINCT FROM p_owner OR p_digest IS NULL OR p_digest !~ '^[a-f0-9]{64}$'
 OR p_prepared->>'workflow_task_id' IS DISTINCT FROM p_binding->>'task_id'
 OR p_prepared->>'workflow_revision' IS DISTINCT FROM p_binding->>'task_revision'
 OR s->>'patient_id' IS DISTINCT FROM p_owner::text OR m->>'patient_id' IS DISTINCT FROM p_owner::text
 OR r->>'patient_id' IS DISTINCT FROM p_owner::text THEN
  RAISE EXCEPTION 'Invalid owned native preparation' USING ERRCODE='22023'; END IF;
 sid:=(s->>'id')::uuid; mid:=(m->>'id')::uuid; rid:=(r->>'id')::uuid;
 IF sid IS NULL OR mid IS NULL OR rid IS NULL OR jsonb_typeof(p_prepared->'already_persisted') IS DISTINCT FROM 'boolean'
 OR jsonb_typeof(p_prepared->'create_medication') IS DISTINCT FROM 'boolean' THEN
  RAISE EXCEPTION 'Incomplete native preparation' USING ERRCODE='22023'; END IF;
 already:=(p_prepared->>'already_persisted')::boolean;
 IF already THEN
  SELECT * INTO current_row FROM public.regimen_versions WHERE patient_id=p_owner AND id=rid FOR UPDATE;
  IF NOT FOUND OR current_row.state NOT IN ('draft','pending_clarification') OR current_row.source_id<>sid
  OR current_row.patient_medication_id<>mid OR current_row.version_no IS DISTINCT FROM (r->>'version_no')::int
  OR EXISTS(SELECT 1 FROM public.assistant_enrollment_operations WHERE owner=p_owner AND regimen_id=rid) THEN
   RAISE EXCEPTION 'Existing native draft changed or has another saved review' USING ERRCODE='40001'; END IF;
  INSERT INTO public.assistant_enrollment_generations(owner,revision) VALUES(p_owner,1)
   ON CONFLICT(owner) DO UPDATE SET revision=public.assistant_enrollment_generations.revision+1;
 ELSE
  IF NOT public.assistant_medication_prepared_fields(p_prepared,p_expected)
  OR lower(btrim(m->>'display_name')) IS DISTINCT FROM lower(btrim(p_expected->>'medication_name'))
  OR s->>'source_kind' NOT IN ('user_manual','package','pharmacy_label','prescription')
  OR s->>'demo_only' IS DISTINCT FROM 'true' OR m->>'demo_only' IS DISTINCT FROM 'true'
  OR r->>'demo_only' IS DISTINCT FROM 'true' THEN
   RAISE EXCEPTION 'Prepared fields differ from current patient inputs' USING ERRCODE='22023'; END IF;
  IF (p_prepared->>'create_medication')::boolean THEN
   IF m->>'source_id' IS DISTINCT FROM sid::text OR m->>'identity_status' IS DISTINCT FROM 'unverified'
   OR m->>'archived_at' IS NOT NULL OR m->>'product_id' IS NOT NULL THEN
    RAISE EXCEPTION 'New product cannot claim reviewed identity' USING ERRCODE='22023'; END IF;
  ELSE
   IF NOT EXISTS(SELECT 1 FROM public.patient_medications WHERE patient_id=p_owner AND id=mid AND archived_at IS NULL
    AND display_name=m->>'display_name' AND source_id IS NOT DISTINCT FROM (m->>'source_id')::uuid
    AND product_id IS NOT DISTINCT FROM (m->>'product_id')::uuid AND identity_status=m->>'identity_status') THEN
    RAISE EXCEPTION 'Selected native product changed' USING ERRCODE='40001'; END IF;
  END IF;
  SELECT coalesce(max(version_no),0)+1 INTO new_version FROM public.regimen_versions WHERE patient_id=p_owner AND patient_medication_id=mid;
  IF new_version IS DISTINCT FROM (r->>'version_no')::integer THEN RAISE EXCEPTION 'Native version changed' USING ERRCODE='40001'; END IF;
  INSERT INTO public.source_documents(id,patient_id,source_kind,review_status,reviewed_at,checksum,dose_basis,extraction_evidence)
   VALUES(sid,p_owner,s->>'source_kind','extracted',NULL,
    encode(sha256(convert_to('pharmascan-synthetic-source::'||p_owner::text||'::'||sid::text,'UTF8')),'hex'),
    nullif(s->'dose_basis','null'::jsonb),nullif(s->'extraction_evidence','null'::jsonb));
  FOR f IN SELECT value FROM jsonb_array_elements(p_prepared->'result'->'source_fields') LOOP
   IF f->>'demo_only' IS DISTINCT FROM 'true' THEN RAISE EXCEPTION 'Synthetic fixture scope required' USING ERRCODE='22023'; END IF;
   INSERT INTO public.source_fields(id,patient_id,source_id,field_name,field_value,evidence_locator,extraction_method,review_status)
    VALUES((f->>'id')::uuid,p_owner,sid,f->>'field_name',f->'field_value','synthetic:field:'||(f->>'id'),'manual','extracted');
  END LOOP;
  IF (p_prepared->>'create_medication')::boolean THEN
   INSERT INTO public.patient_medications(id,patient_id,display_name,source_id,identity_status)
    VALUES(mid,p_owner,m->>'display_name',sid,'unverified');
  END IF;
  INSERT INTO public.regimen_versions(id,patient_id,patient_medication_id,source_id,version_no,state,dose_amount,dose_unit,
   frequency_rule,is_prn,route,food_instruction,effective_from,effective_to,course_start_date,course_end_date,
   patient_edited,supersedes_id,confirmation_challenge_id,created_at,evidence_task_id)
  VALUES(rid,p_owner,mid,sid,new_version,r->>'state',(r->>'dose_amount')::numeric,r->>'dose_unit',nullif(r->'frequency_rule','null'::jsonb),
   (r->>'is_prn')::boolean,r->>'route',r->>'food_instruction',NULL,NULL,(r->>'course_start_date')::date,(r->>'course_end_date')::date,
   (r->>'patient_edited')::boolean,(r->>'supersedes_id')::uuid,NULL,(r->>'created_at')::timestamptz,(r->>'evidence_task_id')::uuid);
 END IF;
 INSERT INTO public.assistant_enrollment_operations(owner,action_key,workflow_task_id,binding_revision,binding_digest,
  regimen_id,medication_id,source_id,version_no,attachment_ids,source_candidate_index)
 VALUES(p_owner,(p_binding->>'action_key')::uuid,(p_binding->>'task_id')::uuid,(p_binding->>'task_revision')::int+1,p_digest,
  rid,mid,sid,(r->>'version_no')::int,
  ARRAY(SELECT value::uuid FROM jsonb_array_elements_text(p_prepared->'attachment_ids')),
  (p_prepared->>'source_candidate_index')::int);
 FOR attachment IN SELECT value::uuid FROM jsonb_array_elements_text(p_prepared->'attachment_ids') LOOP
  INSERT INTO public.assistant_enrollment_originals(owner,attachment_id,action_key)
   VALUES(p_owner,attachment,(p_binding->>'action_key')::uuid) ON CONFLICT(owner,attachment_id) DO NOTHING;
  -- Keep the first formal source link. Later unactivated versions retain their
  -- own native receipt/attachment associations, never replace original evidence.
  UPDATE public.assistant_workflow_attachments SET data=data||jsonb_build_object('source_ref',jsonb_build_object('kind','source','id',sid))
   WHERE owner=p_owner AND id=attachment AND task_id=(p_binding->>'task_id')::uuid
   AND (data->'source_ref' IS NULL OR data->'source_ref'='null'::jsonb);
 END LOOP;
 RETURN jsonb_build_object('kind','regimen','id',rid,'version',(r->>'version_no')::int);
END $$;
ALTER FUNCTION public.assistant_medication_native_enrollment(uuid,jsonb,jsonb,jsonb,text) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_medication_native_enrollment(uuid,jsonb,jsonb,jsonb,text)
 FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;

CREATE FUNCTION public.assistant_medication_native_result(p_owner uuid,p_action uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE c public.assistant_medication_commands%ROWTYPE; b public.assistant_business_receipts%ROWTYPE; result jsonb;
BEGIN
 SELECT * INTO STRICT c FROM public.assistant_medication_commands WHERE owner=p_owner AND action_key=p_action;
 SELECT * INTO STRICT b FROM public.assistant_business_receipts WHERE owner=p_owner AND action_key=p_action;
 IF c.state<>'applied' THEN RAISE EXCEPTION 'Native transaction has not settled' USING ERRCODE='40001'; END IF;
 CASE c.kind
 WHEN 'prepare' THEN SELECT public.assistant_medication_projection(to_jsonb(x),'enrollment') INTO result
  FROM public.assistant_enrollment_operations x
  JOIN public.regimen_versions r ON r.patient_id=x.owner AND r.id=x.regimen_id AND r.version_no=x.version_no
   AND r.source_id=x.source_id AND r.patient_medication_id=x.medication_id
  JOIN public.patient_medications m ON m.patient_id=x.owner AND m.id=x.medication_id
  JOIN public.source_documents s ON s.patient_id=x.owner AND s.id=x.source_id
  WHERE x.owner=p_owner AND x.action_key=p_action;
 WHEN 'review_source' THEN SELECT public.assistant_medication_projection(to_jsonb(x),'source') INTO result
  FROM public.source_documents x WHERE patient_id=p_owner AND id=c.native_result_id;
 WHEN 'request_challenge' THEN SELECT public.assistant_medication_projection(to_jsonb(x),'challenge') INTO result
  FROM public.confirmation_challenges x WHERE patient_id=p_owner AND id=c.native_result_id;
 WHEN 'activate' THEN SELECT jsonb_build_object('regimen',public.assistant_medication_projection(to_jsonb(x),'regimen'),
  'superseded_regimen_ids',CASE WHEN x.supersedes_id IS NULL THEN '[]'::jsonb ELSE jsonb_build_array(x.supersedes_id) END)
  INTO result FROM public.regimen_versions x WHERE patient_id=p_owner AND id=c.native_result_id AND state='active';
 WHEN 'change_plan','end_plan' THEN SELECT public.assistant_medication_projection(to_jsonb(x),'regimen') INTO result
  FROM public.regimen_versions x WHERE patient_id=p_owner AND id=c.native_result_id;
 WHEN 'save_source','review_registration' THEN SELECT data INTO result FROM public.medication_evidence_tasks
  WHERE patient_id=p_owner AND id=c.native_result_id;
 WHEN 'delete_draft' THEN SELECT jsonb_build_object('deleted',true,'medication_deleted',medication_deleted,
  'cleanup_pending',cardinality(storage_paths)>0) INTO result FROM public.draft_deletion_receipts
  WHERE patient_id=p_owner AND target_id=c.native_result_id
  AND kind=CASE WHEN b.business_ref->>'kind'='regimen' THEN 'draft' ELSE 'source' END;
 WHEN 'prepare_source','prepare_maintenance','review_identity' THEN result:='null'::jsonb;
 ELSE RAISE EXCEPTION 'Unknown native command' USING ERRCODE='22023';
 END CASE;
 IF result IS NULL THEN RAISE EXCEPTION 'Native result unavailable; retain applied receipt' USING ERRCODE='40001'; END IF;
 RETURN jsonb_build_object('receipt',to_jsonb(b),'result',result);
END $$;
ALTER FUNCTION public.assistant_medication_native_result(uuid,uuid) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_medication_native_result(uuid,uuid)
 FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;

CREATE FUNCTION public.assistant_medication_assert_original(p_owner uuid,p_task uuid,p_attachment uuid,
 p_reference jsonb DEFAULT NULL) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE a jsonb;
BEGIN
 SELECT data INTO a FROM public.assistant_workflow_attachments
 WHERE owner=p_owner AND task_id=p_task AND id=p_attachment;
 IF auth.uid() IS DISTINCT FROM p_owner OR a IS NULL OR a->>'state' IS DISTINCT FROM 'saved'
 OR a->'object_written' IS DISTINCT FROM 'true'::jsonb OR a->>'extraction_status' IS DISTINCT FROM 'succeeded'
 OR a->>'source_kind' NOT IN ('package','pharmacy_label','prescription')
 OR EXISTS(SELECT 1 FROM public.assistant_original_deletions WHERE owner=p_owner AND attachment_id=p_attachment)
 OR NOT EXISTS(SELECT 1 FROM public.assistant_storage_tickets t
 JOIN public.assistant_verified_operations v ON v.owner=t.owner AND v.ticket_id=t.id AND v.generation=t.generation
 WHERE t.owner=p_owner AND t.task_id=p_task AND t.attachment_id=p_attachment AND t.operation='upload'
 AND NOT t.deleting AND NOT t.revoked AND v.result='bytes_verified'
 AND t.object_ref=a->>'object_ref' AND t.expected_checksum=a->>'original_checksum'
 AND v.checksum=t.expected_checksum AND v.byte_size=t.byte_size AND t.byte_size=(a->>'byte_size')::int
 AND (p_reference IS NULL OR (p_reference->>'result'='bytes_verified'
 AND p_reference->>'ticket_id'=t.id::text AND p_reference->>'verification_id'=v.id::text
 AND (p_reference->>'generation')::int=v.generation))) THEN
  RAISE EXCEPTION 'An owned independently verified original is required' USING ERRCODE='40001'; END IF;
 RETURN a;
END $$;
ALTER FUNCTION public.assistant_medication_assert_original(uuid,uuid,uuid,jsonb) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_medication_assert_original(uuid,uuid,uuid,jsonb)
 FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;

-- Copy attestation is deliberately an I11 dependency. Its fixed proof resolver
-- checks technical object tickets, not clinical rows, and returns no user content.
-- Missing resolver is unavailable, never an upload-ACK/metadata fallback.
CREATE FUNCTION public.assistant_medication_native_source(p_owner uuid,p_binding jsonb,p_materialized jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE m jsonb:=p_materialized->'metadata'; a jsonb; old_task jsonb; native_task jsonb:=m->'task';
 s jsonb:=m->'source'; product jsonb:=m->'medication'; image jsonb:=m->'image'; link jsonb:=m->'link';
 f jsonb; mid uuid; sid uuid; tid uuid; copy_ok boolean;
BEGIN
 a:=public.assistant_medication_assert_original(p_owner,(p_binding->>'task_id')::uuid,
  (p_materialized->>'attachment_id')::uuid,p_materialized->'original_verification');
 IF to_regprocedure('public.assistant_native_image_assert_verified(uuid,jsonb,jsonb,uuid)') IS NULL THEN
  RAISE EXCEPTION 'Independent native image verification is unavailable' USING ERRCODE='55000'; END IF;
 EXECUTE 'SELECT public.assistant_native_image_assert_verified($1,$2,$3,$4)' INTO copy_ok
  USING p_owner,image,p_materialized->'copy_verification',(p_binding->>'task_id')::uuid;
 IF copy_ok IS DISTINCT FROM true THEN RAISE EXCEPTION 'Native copy proof changed' USING ERRCODE='40001'; END IF;
 mid:=(product->>'id')::uuid; sid:=(s->>'id')::uuid; tid:=(native_task->>'id')::uuid;
 IF mid IS NULL OR sid IS NULL OR tid IS NULL
 OR s->>'patient_id' IS DISTINCT FROM p_owner::text OR product->>'patient_id' IS DISTINCT FROM p_owner::text
 OR native_task->>'patient_id' IS DISTINCT FROM p_owner::text OR native_task->>'medication_id' IS DISTINCT FROM mid::text
 OR image->>'patient_id' IS DISTINCT FROM p_owner::text OR image->>'medication_id' IS DISTINCT FROM mid::text
 OR image->>'source_id' IS DISTINCT FROM sid::text OR link->>'patient_id' IS DISTINCT FROM p_owner::text
 OR link->>'medication_id' IS DISTINCT FROM mid::text OR link->>'source_id' IS DISTINCT FROM sid::text
 THEN RAISE EXCEPTION 'Owned native source identity required' USING ERRCODE='22023'; END IF;
 IF p_materialized->'duplicate'='true'::jsonb THEN
  SELECT data INTO old_task FROM public.medication_evidence_tasks WHERE patient_id=p_owner AND id=tid FOR UPDATE;
  IF old_task IS NULL OR (old_task-'updated_at') IS DISTINCT FROM (native_task-'updated_at')
  OR (old_task->>'updated_at')::timestamptz IS DISTINCT FROM (native_task->>'updated_at')::timestamptz
  OR (old_task-'updated_at') IS DISTINCT FROM (m->'prior_task'-'updated_at')
  OR old_task->>'medication_id' IS DISTINCT FROM mid::text OR old_task->>'draft_regimen_id' IS NOT NULL
  OR NOT(old_task->'source_ids' @> jsonb_build_array(sid)) OR m->'create_medication' IS DISTINCT FROM 'false'::jsonb
  OR s->>'source_kind' IS DISTINCT FROM a->>'source_kind'
  OR NOT EXISTS(SELECT 1 FROM public.source_documents x WHERE x.patient_id=p_owner AND x.id=sid
   AND x.source_kind=a->>'source_kind' AND public.assistant_medication_projection(to_jsonb(x),'source')=s)
  OR NOT EXISTS(SELECT 1 FROM public.patient_medications x WHERE x.patient_id=p_owner AND x.id=mid AND archived_at IS NULL)
  OR NOT EXISTS(SELECT 1 FROM public.medication_images x WHERE x.patient_id=p_owner AND x.id=(image->>'id')::uuid
   AND x.medication_id=mid AND x.source_id=sid AND (x.data-'created_at')=(image-'created_at')
   AND (x.data->>'created_at')::timestamptz=(image->>'created_at')::timestamptz)
  OR NOT EXISTS(SELECT 1 FROM public.medication_source_links x WHERE x.patient_id=p_owner AND x.medication_id=mid AND x.source_id=sid)
  OR (a->'source_ref' IS NOT NULL AND a->'source_ref'<>'null'::jsonb
   AND (a->'source_ref'->>'kind' IS DISTINCT FROM 'source' OR a->'source_ref'->>'id' IS DISTINCT FROM sid::text)) THEN
   RAISE EXCEPTION 'Actual duplicate source facts or original protection changed' USING ERRCODE='40001'; END IF;
  UPDATE public.assistant_workflow_attachments SET data=data||jsonb_build_object('source_ref',
   jsonb_build_object('kind','source','id',sid,'version',NULL)) WHERE owner=p_owner AND id=(p_materialized->>'attachment_id')::uuid
   AND (data->'source_ref' IS NULL OR data->'source_ref'='null'::jsonb);
  RETURN jsonb_build_object('kind','enrollment_task','id',tid,'version',(old_task->>'version')::int);
 END IF;
 IF p_materialized->'duplicate' IS DISTINCT FROM 'false'::jsonb THEN
  RAISE EXCEPTION 'Closed source materialization outcome required' USING ERRCODE='22023'; END IF;
 IF s->>'review_status' IS DISTINCT FROM 'extracted' OR s->>'reviewed_at' IS NOT NULL
 OR s->>'source_kind' IS DISTINCT FROM a->>'source_kind'
 OR s->'extraction_evidence' IS DISTINCT FROM a->'extraction'
 OR native_task->>'draft_regimen_id' IS NOT NULL OR image->'reviewed' IS DISTINCT FROM 'false'::jsonb
 OR image->>'eligibility' IS DISTINCT FROM 'associated'
 OR image->>'storage_path' IS DISTINCT FROM p_owner::text||'/'||mid::text||'/'||(image->>'checksum')||'.png'
 OR jsonb_typeof(m->'fields') IS DISTINCT FROM 'array' OR jsonb_array_length(m->'fields')>20
 OR jsonb_typeof(m->'create_medication') IS DISTINCT FROM 'boolean' THEN
  RAISE EXCEPTION 'Invalid native source metadata' USING ERRCODE='22023'; END IF;
 SELECT data INTO old_task FROM public.medication_evidence_tasks WHERE patient_id=p_owner AND id=tid FOR UPDATE;
 IF old_task IS DISTINCT FROM nullif(m->'prior_task','null'::jsonb)
 OR (native_task->>'version')::int IS DISTINCT FROM coalesce((old_task->>'version')::int,1)+1
 OR (old_task IS NOT NULL AND (old_task->>'medication_id' IS DISTINCT FROM mid::text
  OR old_task->>'draft_regimen_id' IS NOT NULL)) THEN
  RAISE EXCEPTION 'Native source registration changed' USING ERRCODE='40001'; END IF;
 IF (m->>'create_medication')::boolean THEN
  IF old_task IS NOT NULL OR product->>'source_id' IS DISTINCT FROM sid::text
  OR product->>'identity_status' IS DISTINCT FROM 'unverified' OR product->>'product_id' IS NOT NULL
  OR product->>'archived_at' IS NOT NULL THEN RAISE EXCEPTION 'Unreviewed product required' USING ERRCODE='22023'; END IF;
 ELSE
  IF NOT EXISTS(SELECT 1 FROM public.patient_medications WHERE patient_id=p_owner AND id=mid
   AND archived_at IS NULL AND display_name=product->>'display_name') THEN
   RAISE EXCEPTION 'Owned product changed' USING ERRCODE='40001'; END IF;
 END IF;
 IF a->'source_ref' IS NOT NULL AND a->'source_ref'<>'null'::jsonb
 AND (a->'source_ref'->>'kind' IS DISTINCT FROM 'source' OR a->'source_ref'->>'id' IS DISTINCT FROM sid::text) THEN
  RAISE EXCEPTION 'Formal original source cannot be replaced' USING ERRCODE='40001'; END IF;
 INSERT INTO public.source_documents(id,patient_id,source_kind,review_status,checksum,dose_basis,extraction_evidence)
 VALUES(sid,p_owner,s->>'source_kind','extracted',a->>'original_checksum',nullif(s->'dose_basis','null'::jsonb),s->'extraction_evidence');
 FOR f IN SELECT value FROM jsonb_array_elements(m->'fields') LOOP
  IF f->>'patient_id' IS DISTINCT FROM p_owner::text OR f->>'source_id' IS DISTINCT FROM sid::text
  OR f->>'review_status' IS DISTINCT FROM 'extracted' OR f->>'reviewed_at' IS NOT NULL THEN
   RAISE EXCEPTION 'Unreviewed source fields required' USING ERRCODE='22023'; END IF;
  INSERT INTO public.source_fields(id,patient_id,source_id,field_name,field_value,evidence_locator,extraction_method,review_status)
  VALUES((f->>'id')::uuid,p_owner,sid,f->>'field_name',f->'field_value','synthetic:field:'||(f->>'id'),'manual','extracted');
 END LOOP;
 IF (m->>'create_medication')::boolean THEN
  INSERT INTO public.patient_medications(id,patient_id,display_name,source_id,identity_status)
  VALUES(mid,p_owner,product->>'display_name',sid,'unverified'); END IF;
 IF old_task IS NULL THEN
  INSERT INTO public.medication_evidence_tasks(id,patient_id,medication_id,data,version)
  VALUES(tid,p_owner,mid,native_task,(native_task->>'version')::int);
 ELSE
  UPDATE public.medication_evidence_tasks SET data=native_task,version=(native_task->>'version')::int
  WHERE patient_id=p_owner AND id=tid AND version=(old_task->>'version')::int;
  IF NOT FOUND THEN RAISE EXCEPTION 'Source registration changed' USING ERRCODE='40001'; END IF;
 END IF;
 INSERT INTO public.medication_images(id,patient_id,medication_id,source_id,data,version)
 VALUES((image->>'id')::uuid,p_owner,mid,sid,image,(image->>'metadata_version')::int);
 INSERT INTO public.medication_source_links(id,patient_id,medication_id,source_id,data)
 VALUES((link->>'id')::uuid,p_owner,mid,sid,link);
 UPDATE public.assistant_workflow_attachments SET data=data||jsonb_build_object('source_ref',
  jsonb_build_object('kind','source','id',sid,'version',NULL))
 WHERE owner=p_owner AND id=(p_materialized->>'attachment_id')::uuid
 AND (data->'source_ref' IS NULL OR data->'source_ref'='null'::jsonb);
 RETURN jsonb_build_object('kind','enrollment_task','id',tid,'version',(native_task->>'version')::int);
END $$;
ALTER FUNCTION public.assistant_medication_native_source(uuid,jsonb,jsonb) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_medication_native_source(uuid,jsonb,jsonb)
 FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;

CREATE FUNCTION public.assistant_medication_registration(p_owner uuid,p_binding jsonb,p_command jsonb,
 p_prepared jsonb,p_existing jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE t jsonb; other_product jsonb; duplicate_id uuid; sid uuid; source_row public.source_documents%ROWTYPE;
 draft jsonb:=p_command->'draft'; candidate jsonb; lhs text[]; rhs text[]; different boolean;
 ref jsonb; product jsonb; r public.regimen_versions%ROWTYPE; key text; link_id uuid:=gen_random_uuid();
BEGIN
 SELECT data INTO t FROM public.medication_evidence_tasks
 WHERE patient_id=p_owner AND id=(p_binding->'prepared_ref'->>'id')::uuid FOR UPDATE;
 IF t IS NULL OR (t->>'version')::int IS DISTINCT FROM (p_binding->'prepared_ref'->>'version')::int
 OR p_binding->'prepared_ref'->>'kind' IS DISTINCT FROM 'enrollment_task' THEN
  RAISE EXCEPTION 'Owned source review changed' USING ERRCODE='40001'; END IF;
 IF t->'conflicts' IS DISTINCT FROM '[]'::jsonb OR p_command->'confirmed' IS DISTINCT FROM 'true'::jsonb
 OR lower(draft->>'medication_name') IS DISTINCT FROM lower(t->'product'->>'name')
 OR p_command->>'product_category' NOT IN ('unknown','POM','P','GSL','supplement') THEN
  RAISE EXCEPTION 'Review current product conflicts first' USING ERRCODE='22023'; END IF;
 IF t->>'printed_course_days' IS NOT NULL AND (draft->>'course_start_date' IS NULL OR draft->>'course_end_date' IS NULL
 OR (draft->>'course_end_date')::date-(draft->>'course_start_date')::date+1<>(t->>'printed_course_days')::int) THEN
  RAISE EXCEPTION 'Printed course dates require review' USING ERRCODE='22023'; END IF;
 FOR sid IN SELECT value::uuid FROM jsonb_array_elements_text(t->'source_ids') LOOP
  SELECT * INTO source_row FROM public.source_documents WHERE patient_id=p_owner AND id=sid;
  IF NOT FOUND THEN RAISE EXCEPTION 'Native source unavailable' USING ERRCODE='40001'; END IF;
  IF source_row.source_kind<>'package' AND source_row.extraction_evidence->>'label_kind'='dispensing' THEN
   FOR candidate IN SELECT value FROM jsonb_array_elements(source_row.extraction_evidence->'candidates') LOOP
    IF NOT public.assistant_medication_printed_matches(draft,candidate->'regimen_evidence'->'instructions') THEN
     RAISE EXCEPTION 'Entered instructions differ from printed evidence' USING ERRCODE='22023'; END IF;
   END LOOP;
  END IF;
 END LOOP;
 FOR duplicate_id IN SELECT value::uuid FROM jsonb_array_elements_text(t->'possible_duplicate_ids') LOOP
  SELECT data->'product' INTO other_product FROM public.medication_evidence_tasks
   WHERE patient_id=p_owner AND medication_id=duplicate_id ORDER BY created_at,id LIMIT 1;
  IF other_product IS NULL THEN RAISE EXCEPTION 'Missing product evidence cannot distinguish duplicates' USING ERRCODE='22023'; END IF;
  lhs:=regexp_match(regexp_replace(lower(normalize(coalesce(t->'product'->>'strength',''),NFKC)),'[[:space:]]','','g'),
   '^([0-9]+(?:\.[0-9]+)?)(mg|g|mcg|ug|μg|iu|mg/ml|mcg/ml|units/ml)$');
  rhs:=regexp_match(regexp_replace(lower(normalize(coalesce(other_product->>'strength',''),NFKC)),'[[:space:]]','','g'),
   '^([0-9]+(?:\.[0-9]+)?)(mg|g|mcg|ug|μg|iu|mg/ml|mcg/ml|units/ml)$');
  different:=coalesce(lhs[2]=rhs[2] AND lhs[1]::numeric>0 AND rhs[1]::numeric>0 AND lhs[1]::numeric<>rhs[1]::numeric,false);
  FOREACH key IN ARRAY ARRAY['dose_form','formulation'] LOOP
   different:=different OR (coalesce(btrim(t->'product'->>key),'')<>'' AND coalesce(btrim(other_product->>key),'')<>''
    AND lower(btrim(t->'product'->>key))<>lower(btrim(other_product->>key)));
  END LOOP;
  IF NOT different THEN RAISE EXCEPTION 'Choose existing product or provide distinct recorded product evidence' USING ERRCODE='22023'; END IF;
 END LOOP;
 IF t->>'draft_regimen_id' IS NOT NULL THEN
  SELECT * INTO r FROM public.regimen_versions WHERE patient_id=p_owner AND id=(t->>'draft_regimen_id')::uuid;
  IF NOT FOUND OR p_existing IS DISTINCT FROM t OR p_prepared IS NOT NULL
  OR r.patient_medication_id IS DISTINCT FROM (t->>'medication_id')::uuid
  OR t->'product'->>'category' IS DISTINCT FROM p_command->>'product_category' THEN
   RAISE EXCEPTION 'Saved native source details changed' USING ERRCODE='40001'; END IF;
  FOREACH key IN ARRAY ARRAY['dose_amount','dose_unit','is_prn','route','food_instruction','course_start_date','course_end_date'] LOOP
   IF nullif(to_jsonb(r)->key,'null'::jsonb) IS DISTINCT FROM nullif(draft->key,'null'::jsonb) THEN
    RAISE EXCEPTION 'Saved source instructions differ' USING ERRCODE='22023'; END IF;
  END LOOP;
  IF NOT public.assistant_medication_rule_matches(r.frequency_rule,draft->'frequency_rule',draft->>'course_start_date')
  OR r.supersedes_id IS DISTINCT FROM (draft->>'supersedes_regimen_id')::uuid
  OR (draft->'patient_edited'='true'::jsonb AND NOT r.patient_edited) THEN
   RAISE EXCEPTION 'Saved source schedule differs' USING ERRCODE='22023'; END IF;
  IF NOT EXISTS(SELECT 1 FROM public.assistant_enrollment_operations WHERE owner=p_owner AND regimen_id=r.id
   AND workflow_task_id=(p_binding->>'task_id')::uuid) THEN
   RAISE EXCEPTION 'Continue original source workflow' USING ERRCODE='40001'; END IF;
  RETURN jsonb_build_object('kind','regimen','id',r.id,'version',r.version_no);
 END IF;
 IF p_prepared IS NULL OR p_existing IS NOT NULL OR p_prepared->'already_persisted' IS DISTINCT FROM 'false'::jsonb
 OR p_prepared->'create_medication' IS DISTINCT FROM 'false'::jsonb
 OR p_prepared->'result'->'regimen'->>'patient_medication_id' IS DISTINCT FROM t->>'medication_id'
 OR p_prepared->'result'->'regimen'->>'evidence_task_id' IS DISTINCT FROM t->>'id'
 OR p_prepared->'result'->'missing_instructions' IS DISTINCT FROM '[]'::jsonb
 OR p_prepared->'source'->>'source_kind' IS DISTINCT FROM 'user_manual'
 OR p_prepared->'source'->>'extraction_evidence' IS NOT NULL
 OR p_prepared->'attachment_ids' IS DISTINCT FROM '[]'::jsonb
 OR EXISTS(SELECT 1 FROM public.regimen_versions WHERE patient_id=p_owner
  AND patient_medication_id=(t->>'medication_id')::uuid AND state='active') THEN
  RAISE EXCEPTION 'Source review requires a complete inactive owned proposal' USING ERRCODE='22023'; END IF;
 ref:=public.assistant_medication_native_enrollment(p_owner,p_binding,p_prepared,draft,
  encode(sha256(convert_to(p_command::text,'UTF8')),'hex'));
 -- The parent must associate this actual regimen before reviewing its fields;
 --036 rejects review of a newly bound regimen missing from the current task.
 UPDATE public.assistant_workflow_tasks SET data=data||jsonb_build_object('business_refs',jsonb_build_array(ref))
 WHERE owner=p_owner AND id=(p_binding->>'task_id')::uuid;
 FOR sid IN SELECT value::uuid FROM jsonb_array_elements_text(t->'source_ids')
  UNION SELECT (p_prepared->'source'->>'id')::uuid LOOP
  IF EXISTS(SELECT 1 FROM public.source_documents WHERE patient_id=p_owner AND id=sid AND review_status='extracted') THEN
   UPDATE public.source_fields SET review_status='user_reviewed',reviewed_at=clock_timestamp()
    WHERE patient_id=p_owner AND source_id=sid;
   UPDATE public.source_documents SET review_status='user_reviewed',reviewed_at=clock_timestamp() WHERE patient_id=p_owner AND id=sid;
   UPDATE public.patient_medications SET identity_status='user_reviewed_document'
    WHERE patient_id=p_owner AND source_id=sid AND identity_status='unverified'
    AND EXISTS(SELECT 1 FROM public.source_fields WHERE patient_id=p_owner AND source_id=sid AND field_name='medication_name'
     AND review_status='user_reviewed');
  END IF;
 END LOOP;
 sid:=(p_prepared->'source'->>'id')::uuid;
 INSERT INTO public.medication_source_links(id,patient_id,medication_id,source_id,data)
 VALUES(link_id,p_owner,(t->>'medication_id')::uuid,sid,jsonb_build_object('id',link_id,'patient_id',p_owner,
  'medication_id',t->'medication_id','source_id',sid,'recorded_at',clock_timestamp()));
 product:=t->'product'||jsonb_build_object('verification','patient_reviewed','category',p_command->>'product_category',
  'category_basis',CASE WHEN p_command->>'product_category'='unknown' THEN 'unknown' ELSE 'patient_entered' END);
 t:=t||jsonb_build_object('product',product,'status','draft_created','draft_regimen_id',ref->'id',
  'version',(t->>'version')::int+1,'updated_at',clock_timestamp(),'missing','[]'::jsonb);
 UPDATE public.medication_evidence_tasks SET data=t,version=(t->>'version')::int
 WHERE patient_id=p_owner AND id=(t->>'id')::uuid;
 RETURN ref;
END $$;
ALTER FUNCTION public.assistant_medication_registration(uuid,jsonb,jsonb,jsonb,jsonb) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_medication_registration(uuid,jsonb,jsonb,jsonb,jsonb)
 FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;

CREATE FUNCTION public.assistant_medication_write(p_request jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=auth.uid(); cmd jsonb:=p_request->'command'; b jsonb:=cmd->'binding'; kind text:=cmd->>'kind';
 tid uuid; action_id uuid; revision integer; digest text; prior public.assistant_medication_commands%ROWTYPE;
 t jsonb; ctl jsonb; ref jsonb:=b->'prepared_ref'; result_ref jsonb; prepared jsonb; expected jsonb; a jsonb;
 candidate jsonb; evidence jsonb; source_row public.source_documents%ROWTYPE; regimen public.regimen_versions%ROWTYPE;
 medication public.patient_medications%ROWTYPE; challenge public.confirmation_challenges%ROWTYPE;
 session_row public.agent_sessions%ROWTYPE; current_generation bigint; native_id uuid; selected_source_id uuid; field_id uuid;
 next_state text:='awaiting_confirmation'; outcome text:='prepared'; advance boolean:=true; child jsonb;
 allowed text[]; attachment uuid; key text; timezone_name text; stamped timestamptz; native_task jsonb;
BEGIN
 IF o IS NULL OR auth.role() IS DISTINCT FROM 'authenticated' THEN
  RAISE EXCEPTION 'Verified patient required' USING ERRCODE='42501'; END IF;
 IF NOT public.assistant_wf_keys(p_request,ARRAY['command','prepared','existing_review','materialized_source','prepared_digest'])
 OR octet_length(p_request::text)>262144 OR NOT public.assistant_wf_keys(b,ARRAY['task_id','task_revision',
 'capability_id','action_key','prepared_ref','expected_domain_revision','run_binding'])
 OR NOT (b ?& ARRAY['task_id','task_revision','capability_id','action_key','prepared_ref','expected_domain_revision'])
 OR jsonb_typeof(b->'task_revision') IS DISTINCT FROM 'number' OR b->>'task_revision' !~ '^[1-9][0-9]*$'
 OR jsonb_typeof(b->'expected_domain_revision') IS DISTINCT FROM 'number' OR b->>'expected_domain_revision' !~ '^(0|[1-9][0-9]*)$'
 OR NOT public.assistant_wf_keys(ref,ARRAY['kind','id','version']) OR ref->>'kind' IS NULL OR ref->>'id' IS NULL THEN
  RAISE EXCEPTION 'Invalid fixed medication request' USING ERRCODE='22023'; END IF;
 allowed:=CASE kind
 WHEN 'prepare' THEN ARRAY['kind','binding','prepared','binding_digest']
 WHEN 'prepare_maintenance' THEN ARRAY['kind','binding']
 WHEN 'review_source' THEN ARRAY['kind','binding','confirmed','source_id','field_ids']
 WHEN 'review_identity' THEN ARRAY['kind','binding','confirmed']
 WHEN 'request_challenge' THEN ARRAY['kind','binding','session_id','session_state_version']
 WHEN 'activate' THEN ARRAY['kind','binding','confirmed','challenge_id','session_state_version']
 WHEN 'change_plan' THEN ARRAY['kind','binding','values']
 WHEN 'end_plan' THEN ARRAY['kind','binding','confirmed']
 WHEN 'delete_draft' THEN ARRAY['kind','binding','confirmed','draft_kind']
 WHEN 'prepare_source' THEN ARRAY['kind','binding']
 WHEN 'save_source' THEN ARRAY['kind','binding','confirmed','attachment_id']
 WHEN 'review_registration' THEN ARRAY['kind','binding','confirmed','draft','distinct_product_confirmed','product_category','replace_active_plan']
 ELSE NULL END;
 IF allowed IS NULL OR NOT public.assistant_wf_keys(cmd,allowed)
 OR (kind IN ('review_source','review_identity','activate','end_plan','delete_draft','save_source','review_registration')
  AND cmd->'confirmed' IS DISTINCT FROM 'true'::jsonb)
 OR (kind NOT IN ('change_plan','review_registration') AND nullif(p_request->'prepared','null'::jsonb) IS NOT NULL)
 OR (kind<>'review_registration' AND nullif(p_request->'existing_review','null'::jsonb) IS NOT NULL)
 OR (kind<>'save_source' AND nullif(p_request->'materialized_source','null'::jsonb) IS NOT NULL) THEN
  RAISE EXCEPTION 'Invalid medication command or independent confirmation' USING ERRCODE='22023'; END IF;
 tid:=(b->>'task_id')::uuid; action_id:=(b->>'action_key')::uuid; revision:=(b->>'task_revision')::int;
 IF tid IS NULL OR action_id IS NULL THEN RAISE EXCEPTION 'Missing medication binding' USING ERRCODE='22023'; END IF;
 -- Derived preparation allocates fresh IDs on a response-loss retry. Only the
 -- unchanged typed command fingerprints the action; reread actual native IDs.
 digest:=encode(sha256(convert_to(cmd::text,'UTF8')),'hex');
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 SELECT data INTO t FROM public.assistant_workflow_tasks WHERE owner=o AND id=tid FOR UPDATE;
 SELECT data INTO ctl FROM public.assistant_workflow_operations
  WHERE owner=o AND task_id=tid AND id=tid AND record_type='control' FOR UPDATE;
 SELECT * INTO prior FROM public.assistant_medication_commands WHERE owner=o AND action_key=action_id;
 IF FOUND THEN
  IF prior.command_digest IS DISTINCT FROM digest OR prior.task_id IS DISTINCT FROM tid THEN
   RAISE EXCEPTION 'Action reused with different inputs' USING ERRCODE='23505'; END IF;
  RETURN jsonb_build_object('result',public.assistant_medication_native_result(o,action_id),'replayed',true);
 END IF;
 IF EXISTS(SELECT 1 FROM public.assistant_business_receipts WHERE owner=o AND action_key=action_id) THEN
  RAISE EXCEPTION 'Action belongs to another transaction' USING ERRCODE='23505'; END IF;
 SELECT coalesce((SELECT g.revision FROM public.assistant_enrollment_generations g WHERE owner=o),0) INTO current_generation;
 IF t IS NULL OR ctl IS NULL OR (t->>'revision')::int IS DISTINCT FROM revision
 OR (ctl->>'revision')::int IS DISTINCT FROM revision OR t->>'capability_id' IS DISTINCT FROM b->>'capability_id'
 OR ctl->>'capability_id' IS DISTINCT FROM b->>'capability_id' OR ctl->>'mode' IS DISTINCT FROM 'allowed'
 OR ctl->'revoked' IS DISTINCT FROM 'false'::jsonb OR ctl->>'status' IS DISTINCT FROM 'idle'
 OR t->>'save_mode' IS DISTINCT FROM 'allowed' OR current_generation IS DISTINCT FROM (b->>'expected_domain_revision')::bigint THEN
  RAISE EXCEPTION 'Saved medication task or records changed' USING ERRCODE='40001'; END IF;
 IF nullif(b->'run_binding','null'::jsonb) IS NOT NULL THEN PERFORM public.assistant_run_assert_current(o,b->'run_binding'); END IF;
 IF kind='prepare_source' THEN
  IF t->>'capability_id' NOT IN ('medication.source.add','medication.source.review')
  OR NOT (t->>'state' IN ('ready_for_review','collecting') OR (t->>'state'='awaiting_confirmation'
   AND t->>'capability_id'='medication.source.add' AND jsonb_array_length(t->'business_refs')=1
   AND t->'business_refs'->0->>'kind'='media_review' AND t->'business_refs'->0->>'id'=tid::text
   AND (t->'business_refs'->0->>'version')::int<revision)) THEN
   RAISE EXCEPTION 'Source review changed' USING ERRCODE='40001'; END IF;
 ELSIF kind IN ('prepare','change_plan','prepare_maintenance') THEN
  IF t->>'state' IS DISTINCT FROM 'ready_for_review' THEN RAISE EXCEPTION 'Prepare the current inputs first' USING ERRCODE='40001'; END IF;
 ELSE
  IF t->>'state' IS DISTINCT FROM 'awaiting_confirmation' OR NOT (t->'business_refs' @> jsonb_build_array(ref)) THEN
   RAISE EXCEPTION 'Independent current review required' USING ERRCODE='40001'; END IF;
 END IF;
 IF (kind='prepare_maintenance' AND t->>'capability_id' NOT IN ('medication.plan.end','medication.draft.delete'))
 OR (kind='end_plan' AND t->>'capability_id'<>'medication.plan.end')
 OR (kind='delete_draft' AND t->>'capability_id'<>'medication.draft.delete')
 OR (kind='change_plan' AND t->>'capability_id'<>'medication.plan.change')
 OR (kind='save_source' AND t->>'capability_id'<>'medication.source.add')
 OR (kind='review_registration' AND t->>'capability_id' NOT IN ('medication.source.add','medication.source.review'))
 OR (kind IN ('prepare','review_source','review_identity','request_challenge','activate')
  AND t->>'capability_id' NOT IN ('medication.enroll','medication.plan.change','medication.draft.resume','medication.source.add','medication.source.review')) THEN
  RAISE EXCEPTION 'Capability cannot perform this medication command' USING ERRCODE='22023'; END IF;
 INSERT INTO public.assistant_medication_commands(owner,action_key,task_id,binding_revision,kind,command_digest,state)
 VALUES(o,action_id,tid,revision,kind,digest,'pending');
 result_ref:=ref;
 IF kind IN ('review_source','review_identity','request_challenge','activate','change_plan','end_plan') THEN
  SELECT * INTO regimen FROM public.regimen_versions WHERE patient_id=o AND id=(ref->>'id')::uuid FOR UPDATE;
  IF NOT FOUND OR ref->>'kind'<>'regimen' OR regimen.version_no IS DISTINCT FROM (ref->>'version')::int THEN
   RAISE EXCEPTION 'Owned medication version changed' USING ERRCODE='40001'; END IF;
  native_id:=regimen.id;
 END IF;
 IF kind='prepare_maintenance' THEN
  expected:=t->'fields';
  IF t->>'capability_id'='medication.plan.end' THEN
   IF ref->>'kind'<>'regimen' OR expected->>'regimen_id' IS DISTINCT FROM ref->>'id'
   OR expected->'expected_version' IS DISTINCT FROM ref->'version'
   OR NOT EXISTS(SELECT 1 FROM public.regimen_versions WHERE patient_id=o AND id=(ref->>'id')::uuid
    AND version_no=(ref->>'version')::int AND state='active') THEN
    RAISE EXCEPTION 'Choose current active plan' USING ERRCODE='40001'; END IF;
  ELSE
   IF expected->>'target_id' IS DISTINCT FROM ref->>'id' OR expected->'expected_version' IS DISTINCT FROM ref->'version'
   OR ref->>'kind' IS DISTINCT FROM CASE WHEN expected->>'kind'='draft' THEN 'regimen' ELSE 'enrollment_task' END THEN
    RAISE EXCEPTION 'Saved unfinished target changed' USING ERRCODE='40001'; END IF;
   IF expected->>'kind'='draft' THEN
    IF NOT EXISTS(SELECT 1 FROM public.regimen_versions WHERE patient_id=o AND id=(ref->>'id')::uuid
     AND version_no=(ref->>'version')::int AND state IN ('draft','pending_clarification')) THEN
     RAISE EXCEPTION 'Unfinished draft changed' USING ERRCODE='40001'; END IF;
   ELSIF expected->>'kind'='source' THEN
    IF NOT EXISTS(SELECT 1 FROM public.medication_evidence_tasks WHERE patient_id=o AND id=(ref->>'id')::uuid
     AND version=(ref->>'version')::int AND data->>'status' IN ('pending_information','conflict','ready_for_review','draft_created')) THEN
     RAISE EXCEPTION 'Unfinished source changed' USING ERRCODE='40001'; END IF;
   ELSE RAISE EXCEPTION 'Closed draft kind required' USING ERRCODE='22023'; END IF;
  END IF;
  INSERT INTO public.assistant_workflow_operations(owner,record_type,id,task_id,data) VALUES(o,'action',action_id,tid,
   jsonb_build_object('owner',o,'action_key',action_id,'task_id',tid,'capability_id',t->>'capability_id',
    'binding_revision',revision+1,'state','succeeded','business_ref',ref,'clinical_revision',current_generation,
    'updated_at',clock_timestamp()));
 ELSIF kind='prepare' THEN
  prepared:=cmd->'prepared'; expected:=t->'fields';
  IF t->>'capability_id'='medication.draft.resume' THEN
   IF prepared->'already_persisted' IS DISTINCT FROM 'true'::jsonb
   OR expected->>'regimen_id' IS DISTINCT FROM prepared->'result'->'regimen'->>'id'
   OR expected->'expected_version' IS DISTINCT FROM prepared->'result'->'regimen'->'version_no' THEN
    RAISE EXCEPTION 'Selected unfinished draft changed' USING ERRCODE='40001'; END IF;
  ELSIF t->>'capability_id'='medication.enroll' THEN
   IF prepared->'already_persisted' IS DISTINCT FROM 'false'::jsonb
   OR prepared->'result'->'regimen'->>'evidence_task_id' IS NOT NULL
   OR nullif(prepared->'source'->'dose_basis','null'::jsonb) IS DISTINCT FROM nullif(expected->'dose_basis','null'::jsonb) THEN
    RAISE EXCEPTION 'Use current enrollment inputs' USING ERRCODE='22023'; END IF;
   IF expected->>'method'='manual' THEN
    IF prepared->'attachment_ids' IS DISTINCT FROM '[]'::jsonb OR prepared->'source'->>'source_kind'<>'user_manual'
    OR prepared->'source'->>'extraction_evidence' IS NOT NULL THEN
     RAISE EXCEPTION 'Manual enrollment cannot claim photo evidence' USING ERRCODE='22023'; END IF;
   ELSIF expected->>'method'='photo' THEN
    attachment:=(expected->>'source_attachment_id')::uuid;
    IF prepared->'attachment_ids' IS DISTINCT FROM jsonb_build_array(attachment)
    OR prepared->'source_candidate_index' IS DISTINCT FROM expected->'source_candidate_index'
    OR NOT (t->'attachment_ids' @> jsonb_build_array(attachment)) THEN
     RAISE EXCEPTION 'Selected source original changed' USING ERRCODE='40001'; END IF;
    a:=public.assistant_medication_assert_original(o,tid,attachment);
    candidate:=a->'extraction'->'candidates'->((expected->>'source_candidate_index')::int);
    evidence:=a->'extraction'||jsonb_build_object('candidates',jsonb_build_array(candidate));
    IF candidate IS NULL OR prepared->'source'->>'source_kind' IS DISTINCT FROM a->>'source_kind'
    OR prepared->'source'->'extraction_evidence' IS DISTINCT FROM evidence
    OR lower(btrim(regexp_replace(expected->>'medication_name','[[:space:]]+',' ','g')))
     IS DISTINCT FROM lower(btrim(regexp_replace(candidate->'product'->>'name','[[:space:]]+',' ','g')))
    OR (coalesce(candidate->'product'->>'strength','')<>'' AND
     regexp_replace(lower(coalesce(expected->'dose_basis'->>'strength_text','')),'[[:space:]]','','g')
     <>regexp_replace(lower(candidate->'product'->>'strength'),'[[:space:]]','','g')) THEN
     RAISE EXCEPTION 'Photo provenance or product changed' USING ERRCODE='22023'; END IF;
    IF a->>'source_kind' IN ('pharmacy_label','prescription') AND a->'extraction'->>'label_kind' NOT IN ('package','none')
    AND NOT public.assistant_medication_printed_matches(expected,candidate->'regimen_evidence'->'instructions') THEN
     RAISE EXCEPTION 'Review the printed instructions' USING ERRCODE='22023'; END IF;
   ELSE RAISE EXCEPTION 'Choose an enrollment method' USING ERRCODE='22023'; END IF;
   IF expected->>'existing_medication_id' IS NOT NULL THEN
    SELECT * INTO medication FROM public.patient_medications WHERE patient_id=o AND id=(expected->>'existing_medication_id')::uuid;
    IF NOT FOUND OR prepared->'create_medication' IS DISTINCT FROM 'false'::jsonb
    OR prepared->'result'->'medication'->>'id' IS DISTINCT FROM medication.id::text THEN
     RAISE EXCEPTION 'Selected product changed' USING ERRCODE='40001'; END IF;
    expected:=expected||jsonb_build_object('medication_name',medication.display_name);
   ELSIF prepared->'create_medication' IS DISTINCT FROM 'true'::jsonb THEN
    RAISE EXCEPTION 'Choose the owned existing medication first' USING ERRCODE='22023'; END IF;
  ELSE RAISE EXCEPTION 'Use the dedicated plan/source preparation command' USING ERRCODE='22023'; END IF;
  result_ref:=public.assistant_medication_native_enrollment(o,b,prepared,expected,cmd->>'binding_digest');
  IF result_ref IS DISTINCT FROM ref THEN RAISE EXCEPTION 'Prepared plan binding differs' USING ERRCODE='22023'; END IF;
  native_id:=(result_ref->>'id')::uuid;
 ELSIF kind='change_plan' THEN
  IF regimen.state NOT IN ('active','ended','superseded') OR regimen.state IS DISTINCT FROM cmd->'values'->>'expected_state'
  OR cmd->'values'->>'action_key' IS DISTINCT FROM action_id::text OR cmd->'values'->>'workflow_task_id' IS DISTINCT FROM tid::text
  OR (cmd->'values'->>'workflow_revision')::int IS DISTINCT FROM revision
  OR cmd->'values'->>'predecessor_id' IS DISTINCT FROM regimen.id::text
  OR (cmd->'values'->>'expected_version')::int IS DISTINCT FROM regimen.version_no
  OR t->'fields'->>'regimen_id' IS DISTINCT FROM regimen.id::text
  OR (t->'fields'->>'expected_version')::int IS DISTINCT FROM regimen.version_no
  OR t->'fields'->>'expected_state' IS DISTINCT FROM regimen.state
  OR t->'fields'->'details' IS DISTINCT FROM cmd->'values'->'fields' THEN
   RAISE EXCEPTION 'Current changed instructions differ' USING ERRCODE='40001'; END IF;
  SELECT * INTO medication FROM public.patient_medications WHERE patient_id=o AND id=regimen.patient_medication_id;
  expected:=to_jsonb(regimen)||jsonb_build_object('medication_name',medication.display_name);
  expected:=expected||(cmd->'values'->'fields'); prepared:=p_request->'prepared';
  IF prepared->'already_persisted' IS DISTINCT FROM 'false'::jsonb
  OR prepared->'create_medication' IS DISTINCT FROM 'false'::jsonb
  OR prepared->'result'->'regimen'->>'patient_medication_id' IS DISTINCT FROM regimen.patient_medication_id::text
  OR prepared->'result'->'regimen'->'patient_edited' IS DISTINCT FROM 'true'::jsonb
  OR (prepared->'result'->'regimen'->>'supersedes_id')::uuid IS DISTINCT FROM CASE WHEN regimen.state='active' THEN regimen.id ELSE NULL END
  OR prepared->'source'->>'source_kind' IS DISTINCT FROM 'user_manual'
  OR prepared->'source'->>'extraction_evidence' IS NOT NULL OR prepared->'attachment_ids' IS DISTINCT FROM '[]'::jsonb THEN
   RAISE EXCEPTION 'Inactive successor proposal required' USING ERRCODE='22023'; END IF;
  result_ref:=public.assistant_medication_native_enrollment(o,b,prepared,expected,p_request->>'prepared_digest');
  native_id:=(result_ref->>'id')::uuid;
 ELSIF kind='review_source' THEN
  selected_source_id:=(cmd->>'source_id')::uuid;
  SELECT * INTO source_row FROM public.source_documents WHERE patient_id=o AND id=selected_source_id FOR UPDATE;
  IF NOT FOUND OR selected_source_id IS DISTINCT FROM regimen.source_id OR source_row.review_status<>'extracted' THEN
   RAISE EXCEPTION 'Unreviewed current source required' USING ERRCODE='40001'; END IF;
  IF nullif(cmd->'field_ids','null'::jsonb) IS NOT NULL THEN
   IF jsonb_typeof(cmd->'field_ids')<>'array' OR jsonb_array_length(cmd->'field_ids')>20 THEN
    RAISE EXCEPTION 'Invalid source field selection' USING ERRCODE='22023'; END IF;
   FOR field_id IN SELECT value::uuid FROM jsonb_array_elements_text(cmd->'field_ids') LOOP
    IF NOT EXISTS(SELECT 1 FROM public.source_fields WHERE patient_id=o AND source_id=selected_source_id AND id=field_id) THEN
     RAISE EXCEPTION 'Field does not belong to source' USING ERRCODE='22023'; END IF;
   END LOOP;
  END IF;
  UPDATE public.source_fields f SET review_status='user_reviewed',reviewed_at=clock_timestamp()
  WHERE f.patient_id=o AND f.source_id=selected_source_id AND (nullif(cmd->'field_ids','null'::jsonb) IS NULL
   OR cmd->'field_ids' @> jsonb_build_array(f.id));
  UPDATE public.source_documents SET review_status='user_reviewed',reviewed_at=clock_timestamp() WHERE patient_id=o AND id=selected_source_id;
  UPDATE public.patient_medications SET identity_status='user_reviewed_document'
  WHERE patient_id=o AND source_id=selected_source_id AND identity_status='unverified'
   AND EXISTS(SELECT 1 FROM public.source_fields f WHERE f.patient_id=o AND f.source_id=selected_source_id
    AND f.field_name='medication_name' AND f.review_status='user_reviewed');
  native_id:=selected_source_id;
 ELSIF kind='review_identity' THEN
  IF regimen.state NOT IN ('draft','pending_clarification') THEN RAISE EXCEPTION 'Unfinished plan required' USING ERRCODE='22023'; END IF;
  SELECT * INTO medication FROM public.patient_medications WHERE patient_id=o AND id=regimen.patient_medication_id FOR UPDATE;
  UPDATE public.assistant_medication_commands SET native_result_id=regimen.id WHERE owner=o AND action_key=action_id;
  IF medication.identity_status='unverified' AND medication.source_id IS DISTINCT FROM regimen.source_id THEN
   IF (SELECT count(*) FROM public.source_fields WHERE patient_id=o AND source_id=medication.source_id
    AND field_name='medication_name')<>1 OR NOT EXISTS(SELECT 1 FROM public.source_fields WHERE patient_id=o
    AND source_id=medication.source_id AND field_name='medication_name' AND field_value=to_jsonb(medication.display_name)) THEN
    RAISE EXCEPTION 'Original identity evidence needs reconciliation' USING ERRCODE='22023'; END IF;
   UPDATE public.source_fields SET review_status='user_reviewed',reviewed_at=clock_timestamp() WHERE patient_id=o
    AND source_id=medication.source_id AND field_name='medication_name' AND review_status='extracted';
   UPDATE public.patient_medications SET identity_status='user_reviewed_document' WHERE patient_id=o AND id=medication.id;
  END IF;
 ELSIF kind='request_challenge' THEN
  SELECT * INTO session_row FROM public.agent_sessions WHERE patient_id=o AND id=(cmd->>'session_id')::uuid FOR UPDATE;
  IF NOT FOUND OR session_row.state<>'awaiting_confirmation' OR session_row.state_version IS DISTINCT FROM (cmd->>'session_state_version')::int
  OR session_row.expires_at<=clock_timestamp() OR regimen.state NOT IN ('draft','pending_clarification') THEN
   RAISE EXCEPTION 'Independent confirmation session changed' USING ERRCODE='40001'; END IF;
  native_id:=gen_random_uuid(); stamped:=clock_timestamp(); advance:=false;
  INSERT INTO public.confirmation_challenges(id,patient_id,session_id,session_state_version,action,regimen_id,
   idempotency_key,token_hash,request_hash,issued_at,expires_at)
  VALUES(native_id,o,session_row.id,session_row.state_version,'activate_regimen',regimen.id,
   'activate:'||regimen.id::text||':'||session_row.id::text||':'||session_row.state_version::text,
   encode(sha256(convert_to(gen_random_uuid()::text||gen_random_uuid()::text,'UTF8')),'hex'),
   encode(sha256(convert_to(cmd::text,'UTF8')),'hex'),stamped,stamped+interval '10 minutes');
 ELSIF kind='activate' THEN
  SELECT * INTO challenge FROM public.confirmation_challenges WHERE patient_id=o AND id=(cmd->>'challenge_id')::uuid FOR UPDATE;
  SELECT * INTO session_row FROM public.agent_sessions WHERE patient_id=o AND id=challenge.session_id FOR UPDATE;
  IF NOT FOUND OR challenge.regimen_id IS DISTINCT FROM regimen.id OR challenge.action IS DISTINCT FROM 'activate_regimen'
  OR challenge.session_state_version IS DISTINCT FROM (cmd->>'session_state_version')::int
  OR session_row.state<>'awaiting_confirmation' OR session_row.state_version IS DISTINCT FROM challenge.session_state_version
  OR session_row.expires_at<=clock_timestamp() OR challenge.expires_at<=clock_timestamp()
  OR challenge.consumed_at IS NOT NULL OR NOT EXISTS(SELECT 1 FROM public.assistant_medication_commands c
   WHERE c.owner=o AND c.task_id=tid AND c.kind='request_challenge' AND c.native_result_id=challenge.id
   AND c.binding_revision=revision AND c.state='applied') THEN
   RAISE EXCEPTION 'Independent current patient confirmation required' USING ERRCODE='40001'; END IF;
  UPDATE public.confirmation_challenges SET confirmed_at=clock_timestamp() WHERE patient_id=o AND id=challenge.id;
  SELECT timezone INTO timezone_name FROM public.patient_profiles WHERE user_id=o;
  PERFORM public.activate_medication_regimen_version(regimen.id,challenge.id,timezone_name);
  outcome:='applied'; next_state:='completed';
 ELSIF kind='end_plan' THEN
  IF regimen.state<>'active' THEN RAISE EXCEPTION 'Only an active current plan can end' USING ERRCODE='40001'; END IF;
  UPDATE public.regimen_versions SET state='ended',effective_to=clock_timestamp() WHERE patient_id=o AND id=regimen.id;
  outcome:='applied'; next_state:='completed';
 ELSIF kind='delete_draft' THEN
  IF cmd->>'draft_kind' NOT IN ('draft','source') OR ref->>'kind' IS DISTINCT FROM
   CASE WHEN cmd->>'draft_kind'='draft' THEN 'regimen' ELSE 'enrollment_task' END THEN
   RAISE EXCEPTION 'Choose an owned unfinished registration' USING ERRCODE='22023'; END IF;
  IF cmd->>'draft_kind'='draft' THEN
   IF NOT EXISTS(SELECT 1 FROM public.regimen_versions WHERE patient_id=o AND id=(ref->>'id')::uuid
    AND version_no=(ref->>'version')::int AND state IN ('draft','pending_clarification')) THEN
    RAISE EXCEPTION 'Unfinished medication version changed' USING ERRCODE='40001'; END IF;
  ELSE
   IF NOT EXISTS(SELECT 1 FROM public.medication_evidence_tasks WHERE patient_id=o AND id=(ref->>'id')::uuid
    AND version=(ref->>'version')::int AND data->>'draft_regimen_id' IS NULL) THEN
    RAISE EXCEPTION 'Unfinished source version changed' USING ERRCODE='40001'; END IF;
  END IF;
  native_id:=(ref->>'id')::uuid;
  PERFORM public.delete_unconfirmed_medication(cmd->>'draft_kind',native_id,true);
  outcome:='applied';
  SELECT CASE WHEN cardinality(storage_paths)>0 THEN 'outcome_unknown' ELSE 'completed' END INTO next_state
   FROM public.draft_deletion_receipts WHERE patient_id=o AND kind=cmd->>'draft_kind' AND target_id=native_id;
 ELSIF kind='prepare_source' THEN
  IF t->'fields'->>'source_task_id' IS NOT NULL THEN
   SELECT data INTO native_task FROM public.medication_evidence_tasks WHERE patient_id=o
    AND id=(t->'fields'->>'source_task_id')::uuid;
   IF native_task IS NULL OR (native_task->>'version')::int IS DISTINCT FROM (t->'fields'->>'expected_version')::int THEN
    RAISE EXCEPTION 'Owned source registration changed' USING ERRCODE='40001'; END IF;
   result_ref:=jsonb_build_object('kind','enrollment_task','id',native_task->'id','version',native_task->'version');
  ELSE
   IF t->>'capability_id'<>'medication.source.add' OR NOT EXISTS(SELECT 1 FROM public.assistant_workflow_attachments w
    WHERE w.owner=o AND w.task_id=tid AND t->'attachment_ids' @> jsonb_build_array(w.id)
    AND w.data->>'state'='saved' AND w.data->>'extraction_status'='succeeded'
    AND (t->'fields'->>'source_attachment_id' IS NULL OR t->'fields'->>'source_attachment_id'=w.id::text)) THEN
    RAISE EXCEPTION 'Choose a successful owned source original' USING ERRCODE='22023'; END IF;
   result_ref:=jsonb_build_object('kind','media_review','id',tid,'version',revision+1);
  END IF;
  IF result_ref IS DISTINCT FROM ref THEN RAISE EXCEPTION 'Source marker differs from current inputs' USING ERRCODE='22023'; END IF;
 ELSIF kind='save_source' THEN
  IF ref->>'kind' NOT IN ('media_review','enrollment_task') OR NOT (t->'attachment_ids' @> jsonb_build_array(cmd->'attachment_id'))
  OR p_request->'materialized_source'->>'attachment_id' IS DISTINCT FROM cmd->>'attachment_id'
  OR (ref->>'kind'='media_review' AND (ref->>'id' IS DISTINCT FROM tid::text
   OR (ref->>'version')::int IS DISTINCT FROM revision
   OR nullif(p_request->'materialized_source'->'metadata'->'prior_task','null'::jsonb) IS NOT NULL))
  OR (ref->>'kind'='enrollment_task' AND (p_request->'materialized_source'->'metadata'->'task'->>'id' IS DISTINCT FROM ref->>'id'
   OR (p_request->'materialized_source'->'metadata'->'prior_task'->>'version')::int IS DISTINCT FROM (ref->>'version')::int)) THEN
   RAISE EXCEPTION 'Saved original/source marker changed' USING ERRCODE='40001'; END IF;
  result_ref:=public.assistant_medication_native_source(o,b,p_request->'materialized_source');
  native_id:=(result_ref->>'id')::uuid; outcome:='applied';
 ELSIF kind='review_registration' THEN
  result_ref:=public.assistant_medication_registration(o,b,cmd,nullif(p_request->'prepared','null'::jsonb),
   nullif(p_request->'existing_review','null'::jsonb));
  native_id:=(ref->>'id')::uuid;
 ELSE RAISE EXCEPTION 'Unknown fixed medication command' USING ERRCODE='22023'; END IF;
 IF nullif(b->'run_binding','null'::jsonb) IS NOT NULL THEN PERFORM public.assistant_run_assert_current(o,b->'run_binding'); END IF;
 IF advance THEN
  child:=public.assistant_workflow_command_legacy_035('task_cas',jsonb_build_object('task_id',tid,
   'expected_revision',revision,'event_id',action_id,'request_digest',digest,'update',jsonb_build_object(
    'state',next_state,'save_mode','allowed','storage_state',CASE WHEN kind='delete_draft' AND next_state='outcome_unknown' THEN 'cleanup_pending' ELSE 'saved' END,'fields',t->'fields','missing_fields','[]'::jsonb,
    'attachment_ids',t->'attachment_ids','business_refs',jsonb_build_array(result_ref))));
  IF child ? 'error' THEN RAISE EXCEPTION 'Task changed after native mutation' USING ERRCODE='40001'; END IF;
 END IF;
 IF nullif(b->'run_binding','null'::jsonb) IS NOT NULL THEN PERFORM public.assistant_run_assert_current(o,b->'run_binding'); END IF;
 SELECT coalesce((SELECT g.revision FROM public.assistant_enrollment_generations g WHERE owner=o),0) INTO current_generation;
 INSERT INTO public.assistant_business_receipts(owner,action_key,task_id,capability_id,binding_revision,business_ref,domain_revision,outcome)
 VALUES(o,action_id,tid,b->>'capability_id',revision+CASE WHEN advance THEN 1 ELSE 0 END,result_ref,current_generation,outcome);
 UPDATE public.assistant_medication_commands SET state='applied',native_result_id=native_id WHERE owner=o AND action_key=action_id;
 RETURN jsonb_build_object('result',public.assistant_medication_native_result(o,action_id),'replayed',false);
EXCEPTION
 WHEN SQLSTATE '40001' THEN RETURN jsonb_build_object('error','stale');
 WHEN unique_violation THEN RETURN jsonb_build_object('error','duplicate');
 WHEN invalid_parameter_value OR invalid_text_representation OR check_violation OR not_null_violation
 OR invalid_datetime_format OR datetime_field_overflow THEN RETURN jsonb_build_object('error','invalid');
 WHEN no_data_found THEN RETURN jsonb_build_object('error','not_found');
 WHEN object_not_in_prerequisite_state OR undefined_function THEN RETURN jsonb_build_object('error','unavailable');
END $$;
ALTER FUNCTION public.assistant_medication_write(jsonb) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_medication_write(jsonb)
 FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;
GRANT EXECUTE ON FUNCTION public.assistant_medication_write(jsonb) TO authenticated;

-- Response-loss reconciliation is read-only. It cannot allocate new preparation
-- IDs, copy an image, advance a task, or reinterpret absence as no business effect.
CREATE FUNCTION public.assistant_medication_read(p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=auth.uid(); c public.assistant_medication_commands%ROWTYPE;
BEGIN
 IF o IS NULL OR auth.role() IS DISTINCT FROM 'authenticated' THEN
  RAISE EXCEPTION 'Verified patient required' USING ERRCODE='42501'; END IF;
 IF jsonb_typeof(p_command) IS DISTINCT FROM 'object' OR octet_length(p_command::text)>262144 THEN
  RAISE EXCEPTION 'Invalid command fingerprint input' USING ERRCODE='22023'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 SELECT * INTO c FROM public.assistant_medication_commands
 WHERE owner=o AND action_key=(p_command->'binding'->>'action_key')::uuid;
 IF NOT FOUND THEN RETURN jsonb_build_object('error','not_found'); END IF;
 IF c.command_digest IS DISTINCT FROM encode(sha256(convert_to(p_command::text,'UTF8')),'hex')
 OR c.task_id IS DISTINCT FROM (p_command->'binding'->>'task_id')::uuid THEN
  RETURN jsonb_build_object('error','duplicate'); END IF;
 RETURN jsonb_build_object('result',public.assistant_medication_native_result(o,c.action_key),'replayed',true);
EXCEPTION WHEN SQLSTATE '40001' THEN RETURN jsonb_build_object('error','stale');
 WHEN no_data_found THEN RETURN jsonb_build_object('error','not_found');
 WHEN invalid_text_representation OR invalid_parameter_value THEN RETURN jsonb_build_object('error','invalid');
END $$;
ALTER FUNCTION public.assistant_medication_read(jsonb) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_medication_read(jsonb)
 FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;
GRANT EXECUTE ON FUNCTION public.assistant_medication_read(jsonb) TO authenticated;
-- Closed owned result projection; cannot delete a draft or acknowledge a file.
CREATE FUNCTION public.assistant_draft_deletion_result(p_kind text,p_target uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=auth.uid(); result jsonb;
BEGIN
 IF o IS NULL OR auth.role() IS DISTINCT FROM 'authenticated' THEN
  RAISE EXCEPTION 'Verified patient required' USING ERRCODE='42501'; END IF;
 IF p_kind IS NULL OR p_kind NOT IN ('draft','source') OR p_target IS NULL THEN
  RAISE EXCEPTION 'Invalid deletion selector' USING ERRCODE='22023'; END IF;
 SELECT jsonb_build_object('deleted',true,'medication_deleted',medication_deleted,
  'cleanup_pending',cardinality(storage_paths)>0) INTO result FROM public.draft_deletion_receipts
  WHERE patient_id=o AND kind=p_kind AND target_id=p_target;
 RETURN result;
END $$;
ALTER FUNCTION public.assistant_draft_deletion_result(text,uuid) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_draft_deletion_result(text,uuid) FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;
GRANT EXECUTE ON FUNCTION public.assistant_draft_deletion_result(text,uuid) TO authenticated;

COMMIT;
