-- REVIEW ONLY / NOT APPLIED. I12 after I02-I11, never automatic migrations.
-- No Auth writes, delivery, contact verification, role provisioning or history deletion.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';
CREATE TABLE public.assistant_settings_generations(owner uuid PRIMARY KEY,revision bigint NOT NULL DEFAULT 0 CHECK(revision>=0));
CREATE TABLE public.assistant_settings_commands (
 owner uuid NOT NULL,action_key uuid NOT NULL,task_id uuid NOT NULL,capability_id text NOT NULL,kind text NOT NULL,
 command_digest text NOT NULL CHECK(command_digest ~ '^[a-f0-9]{64}$'),prepared_ref jsonb NOT NULL,
 binding_revision integer NOT NULL CHECK(binding_revision>0),domain_revision bigint NOT NULL CHECK(domain_revision>=0),
 snapshot_hash text CHECK(snapshot_hash ~ '^[a-f0-9]{64}$'),native_hash text CHECK(native_hash ~ '^[a-f0-9]{64}$'),
 PRIMARY KEY(owner,action_key),FOREIGN KEY(owner,action_key) REFERENCES public.assistant_business_receipts(owner,action_key) DEFERRABLE INITIALLY DEFERRED
);
DO $$ DECLARE relation_name text; BEGIN
 FOREACH relation_name IN ARRAY ARRAY['assistant_settings_generations','assistant_settings_commands'] LOOP
  EXECUTE format('ALTER TABLE public.%I OWNER TO assistant_workflow_owner',relation_name);
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',relation_name);
  EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',relation_name);
  EXECUTE format('CREATE POLICY assistant_settings_owner ON public.%I TO assistant_workflow_owner USING(owner=public.assistant_patient_uid()) WITH CHECK(owner=public.assistant_patient_uid())',relation_name);
  EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner',relation_name);
 END LOOP;
END $$;
GRANT SELECT(user_id,display_name,language,speech_locale,text_size,text_scale_percent,voice_enabled,tts_autoplay,
 conversation_history_enabled,reminders_enabled,reminder_lead_minutes,timezone,created_at,updated_at) ON public.patient_profiles TO assistant_workflow_owner;
GRANT UPDATE(display_name,language,text_size,text_scale_percent,voice_enabled,tts_autoplay,conversation_history_enabled,
 reminders_enabled,reminder_lead_minutes,timezone) ON public.patient_profiles TO assistant_workflow_owner;
CREATE POLICY assistant_settings_profile ON public.patient_profiles TO assistant_workflow_owner USING(user_id=public.assistant_patient_uid()) WITH CHECK(user_id=public.assistant_patient_uid());
GRANT SELECT,INSERT,UPDATE,DELETE ON public.caregiver_contacts TO assistant_workflow_owner;
GRANT SELECT,INSERT ON public.patient_feedback TO assistant_workflow_owner;
CREATE POLICY assistant_settings_contact ON public.caregiver_contacts TO assistant_workflow_owner USING(patient_id=public.assistant_patient_uid()) WITH CHECK(patient_id=public.assistant_patient_uid());
CREATE POLICY assistant_settings_feedback ON public.patient_feedback TO assistant_workflow_owner USING(patient_id=public.assistant_patient_uid()) WITH CHECK(patient_id=public.assistant_patient_uid());

CREATE FUNCTION public.assistant_settings_epoch_changed() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid;row_json jsonb;
BEGIN
 row_json:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
 o:=coalesce((row_json->>'patient_id')::uuid,(row_json->>'user_id')::uuid);
 IF o IS DISTINCT FROM public.assistant_patient_uid() THEN RAISE EXCEPTION 'Owned settings epoch required' USING ERRCODE='42501'; END IF;
 INSERT INTO public.assistant_settings_generations(owner,revision) VALUES(o,1)
 ON CONFLICT(owner) DO UPDATE SET revision=public.assistant_settings_generations.revision+1;
 -- Profile language/timezone and other reviewed preferences are shared inputs
 -- to enrollment/record/media reviews, not just to this settings family.
 IF TG_TABLE_NAME='patient_profiles' THEN
  INSERT INTO public.assistant_enrollment_generations(owner,revision) VALUES(o,1)
  ON CONFLICT(owner) DO UPDATE SET revision=public.assistant_enrollment_generations.revision+1;
 END IF;
 RETURN NULL;
END $$;
-- Ordinary native profile/contact/feedback DML shares the message/clinical fence
-- before row locks, and advances the settings family epoch. No body is copied.
DO $$ DECLARE relation_name text; BEGIN
 FOREACH relation_name IN ARRAY ARRAY['patient_profiles','caregiver_contacts','patient_feedback'] LOOP
  EXECUTE format('CREATE TRIGGER assistant_settings_owner_first BEFORE INSERT OR UPDATE OR DELETE ON public.%I FOR EACH STATEMENT EXECUTE FUNCTION public.assistant_medication_owner_fence()',relation_name);
  EXECUTE format('CREATE TRIGGER assistant_settings_epoch AFTER INSERT OR UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.assistant_settings_epoch_changed()',relation_name);
 END LOOP;
END $$;
CREATE FUNCTION public.assistant_settings_revision() RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=public.assistant_patient_uid();n bigint;
BEGIN
 IF o IS NULL OR public.assistant_patient_role() IS DISTINCT FROM 'authenticated' THEN RAISE EXCEPTION 'Verified owner required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 SELECT coalesce((SELECT g.revision FROM public.assistant_settings_generations g WHERE g.owner=o),0)
 +coalesce((SELECT g.revision FROM public.assistant_enrollment_generations g WHERE g.owner=o),0) INTO n;
 RETURN jsonb_build_object('revision',n);
END $$;
CREATE FUNCTION public.assistant_settings_preferences(p_owner uuid) RETURNS jsonb
LANGUAGE sql SECURITY INVOKER SET search_path='' AS $$
 SELECT jsonb_build_object('patient_id',user_id,'display_name',display_name,'preferred_language',language,'speech_locale',speech_locale,
 'text_size',text_size,'text_scale_percent',text_scale_percent,'voice_enabled',voice_enabled,'tts_autoplay',tts_autoplay,
 'conversation_history_enabled',conversation_history_enabled,'reminders_enabled',reminders_enabled,'reminder_lead_minutes',reminder_lead_minutes,
 'timezone',timezone,'created_at',created_at,'updated_at',updated_at) FROM public.patient_profiles WHERE user_id=p_owner AND user_id=public.assistant_patient_uid()
$$;
CREATE FUNCTION public.assistant_settings_contact_values(p_values jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE SECURITY INVOKER SET search_path='' AS $$
DECLARE name text:=btrim(p_values->>'name');relationship text:=nullif(btrim(p_values->>'relationship'),'');kind text:=p_values->>'contact_type';value text:=btrim(p_values->>'contact_value');
BEGIN
 IF NOT coalesce(public.assistant_wf_keys(p_values,ARRAY['name','relationship','contact_type','contact_value','storage_consent']),false)
 OR p_values->'storage_consent' IS DISTINCT FROM 'true'::jsonb OR name IS NULL OR length(name) NOT BETWEEN 1 AND 80
 OR length(relationship)>80 OR kind IS NULL OR kind NOT IN ('email','phone') OR value IS NULL THEN
  RAISE EXCEPTION 'Consented bounded contact fields required' USING ERRCODE='22023'; END IF;
 IF kind='email' THEN
  value:=lower(value);
  IF octet_length(value)<>length(value) OR value !~ '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$' THEN
   RAISE EXCEPTION 'Valid ASCII contact email required' USING ERRCODE='22023'; END IF;
 ELSE
  value:=regexp_replace(value,'[ ()-]','','g');
  IF value !~ '^\+[1-9][0-9]{7,14}$' THEN RAISE EXCEPTION 'Valid international contact phone required' USING ERRCODE='22023'; END IF;
 END IF;
 IF length(value) NOT BETWEEN 3 AND 254 THEN RAISE EXCEPTION 'Bounded contact value required' USING ERRCODE='22023'; END IF;
 RETURN jsonb_build_object('name',name,'relationship',relationship,'contact_type',kind,'contact_value',value,'storage_consent',true);
END $$;
CREATE FUNCTION public.assistant_settings_snapshot(p_owner uuid,p_task jsonb,p_review uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE cap text:=p_task->>'capability_id';f jsonb:=p_task->'fields';row_json jsonb;before jsonb;fields text[];payload jsonb;
BEGIN
 IF p_owner IS DISTINCT FROM public.assistant_patient_uid() THEN RAISE EXCEPTION 'Owned settings review required' USING ERRCODE='42501'; END IF;
 IF cap LIKE 'preference.%' OR cap='profile.edit' THEN
  fields:=CASE cap WHEN 'preference.language' THEN ARRAY['preferred_language'] WHEN 'preference.text' THEN ARRAY['text_size','text_scale_percent']
   WHEN 'preference.voice' THEN ARRAY['voice_enabled','tts_autoplay'] WHEN 'preference.reminder' THEN ARRAY['reminders_enabled','reminder_lead_minutes']
   WHEN 'preference.privacy' THEN ARRAY['conversation_history_enabled'] WHEN 'preference.timezone' THEN ARRAY['timezone'] WHEN 'profile.edit' THEN ARRAY['display_name'] END;
  IF fields IS NULL OR NOT coalesce(public.assistant_wf_keys(f,fields||ARRAY['previous']),false) THEN RAISE EXCEPTION 'Closed preference scope required' USING ERRCODE='22023'; END IF;
  row_json:=public.assistant_settings_preferences(p_owner)-ARRAY['patient_id','created_at','updated_at'];
  before:=jsonb_build_object('display_name',NULL)||(f->'previous');
  IF row_json IS NULL OR before IS DISTINCT FROM row_json THEN RAISE EXCEPTION 'Current preference snapshot changed' USING ERRCODE='40001'; END IF;
  SELECT coalesce(jsonb_object_agg(key,value),'{}'::jsonb) INTO payload FROM jsonb_each(f-'previous') WHERE value<>'null'::jsonb;
  IF payload='{}'::jsonb THEN RAISE EXCEPTION 'Choose a preference change' USING ERRCODE='22023'; END IF;
  IF (payload ? 'preferred_language' AND payload->>'preferred_language' NOT IN ('en','zh'))
  OR (payload ? 'text_size' AND payload->>'text_size' NOT IN ('standard','large'))
  OR (payload ? 'text_scale_percent' AND (jsonb_typeof(payload->'text_scale_percent')<>'number' OR payload->>'text_scale_percent' !~ '^[0-9]+$' OR (payload->>'text_scale_percent')::int NOT BETWEEN 100 AND 150))
  OR (payload ? 'reminder_lead_minutes' AND (jsonb_typeof(payload->'reminder_lead_minutes')<>'number' OR payload->>'reminder_lead_minutes' !~ '^[0-9]+$' OR (payload->>'reminder_lead_minutes')::int NOT BETWEEN 0 AND 120))
  OR EXISTS(SELECT 1 FROM jsonb_each(payload) WHERE key IN ('voice_enabled','tts_autoplay','conversation_history_enabled','reminders_enabled') AND jsonb_typeof(value)<>'boolean')
  OR (payload ? 'timezone' AND NOT EXISTS(SELECT 1 FROM pg_catalog.pg_timezone_names WHERE name=payload->>'timezone'))
  OR (payload ? 'display_name' AND (jsonb_typeof(payload->'display_name')<>'string' OR length(btrim(payload->>'display_name')) NOT BETWEEN 1 AND 80)) THEN
   RAISE EXCEPTION 'Typed native preference value required' USING ERRCODE='22023'; END IF;
  RETURN row_json;
 ELSIF cap IN ('caregiver.add','caregiver.edit','caregiver.delete') THEN
  fields:=ARRAY['contact_id','previous','previous_updated_at'];
  IF cap<>'caregiver.delete' THEN fields:=fields||ARRAY['name','relationship','contact_type','contact_value','storage_consent']; END IF;
  IF NOT coalesce(public.assistant_wf_keys(f,fields),false) THEN RAISE EXCEPTION 'Closed contact fields required' USING ERRCODE='22023'; END IF;
  IF cap='caregiver.add' THEN
   IF f->>'contact_id' IS NOT NULL OR f->>'previous' IS NOT NULL OR EXISTS(SELECT 1 FROM public.caregiver_contacts WHERE patient_id=p_owner AND id=p_review) THEN
    RAISE EXCEPTION 'New contact cannot overwrite existing details' USING ERRCODE='40001'; END IF;
  ELSE
   SELECT to_jsonb(x)-'patient_id' INTO row_json FROM public.caregiver_contacts x WHERE patient_id=p_owner AND id=(f->>'contact_id')::uuid;
   before:=public.assistant_settings_contact_values(f->'previous');
   IF row_json IS NULL OR row_json->>'updated_at' IS NULL OR (row_json->>'updated_at')::timestamptz IS DISTINCT FROM (f->>'previous_updated_at')::timestamptz
   OR (row_json-ARRAY['id','verification_status','notifications_enabled','sharing_enabled','created_at','updated_at','demo_only']) IS DISTINCT FROM before THEN
    RAISE EXCEPTION 'Current contact snapshot changed' USING ERRCODE='40001'; END IF;
  END IF;
  IF cap<>'caregiver.delete' THEN PERFORM public.assistant_settings_contact_values(f-ARRAY['contact_id','previous','previous_updated_at']); END IF;
  RETURN coalesce(row_json,'null'::jsonb);
 ELSIF cap='feedback.submit' THEN
  IF NOT coalesce(public.assistant_wf_keys(f,ARRAY['category','message']),false) OR coalesce(f->>'category','issue') NOT IN ('issue','suggestion')
  OR jsonb_typeof(f->'message') IS DISTINCT FROM 'string' OR length(btrim(f->>'message')) NOT BETWEEN 5 AND 2000
  OR EXISTS(SELECT 1 FROM public.patient_feedback WHERE patient_id=p_owner AND id=p_review) THEN
   RAISE EXCEPTION 'Complete new feedback or inspect its actual prior result' USING ERRCODE='40001'; END IF;
  RETURN 'null'::jsonb;
 END IF;
 RAISE EXCEPTION 'Closed settings capability required' USING ERRCODE='22023';
END $$;
CREATE FUNCTION public.assistant_settings_result(p_owner uuid,p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE c public.assistant_settings_commands%ROWTYPE;r public.assistant_business_receipts%ROWTYPE;native jsonb:='null';
BEGIN
 SELECT * INTO STRICT c FROM public.assistant_settings_commands WHERE owner=p_owner AND action_key=(p_command->'binding'->>'action_key')::uuid;
 SELECT * INTO STRICT r FROM public.assistant_business_receipts WHERE owner=p_owner AND action_key=c.action_key;
 IF c.kind='preferences' THEN native:=public.assistant_settings_preferences(p_owner);
 ELSIF c.kind IN ('create_contact','edit_contact','delete_contact') THEN
  SELECT to_jsonb(x) INTO native FROM public.caregiver_contacts x WHERE patient_id=p_owner AND id=(r.business_ref->>'id')::uuid;
  IF (c.kind='delete_contact') IS DISTINCT FROM (native IS NULL) THEN RAISE EXCEPTION 'Actual contact result changed' USING ERRCODE='40001'; END IF;
 ELSIF c.kind='feedback' THEN SELECT to_jsonb(x) INTO native FROM public.patient_feedback x WHERE patient_id=p_owner AND id=(r.business_ref->>'id')::uuid; END IF;
 native:=coalesce(native,'null'::jsonb);
 IF c.kind<>'prepare_settings' AND c.native_hash IS DISTINCT FROM encode(sha256(convert_to(native::text,'UTF8')),'hex') THEN
  RAISE EXCEPTION 'Actual native settings changed; retain immutable receipt' USING ERRCODE='40001'; END IF;
 RETURN jsonb_build_object('receipt',to_jsonb(r),'result',native);
END $$;
CREATE FUNCTION public.assistant_settings_apply(p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE o uuid:=public.assistant_patient_uid();b jsonb:=p_command->'binding';ref jsonb:=b->'prepared_ref';kind text:=p_command->>'kind';cap text:=b->>'capability_id';
 tid uuid:=(b->>'task_id')::uuid;aid uuid:=(b->>'action_key')::uuid;rev int:=(b->>'task_revision')::int;preparing boolean:=kind='prepare_settings';
 t jsonb;ctl jsonb;f jsonb;v jsonb:=p_command->'values';expected jsonb;native jsonb:='null';outref jsonb;child jsonb;generation bigint;snapshot text;digest text;allowed text[];
 prior public.assistant_settings_commands%ROWTYPE;prep public.assistant_settings_commands%ROWTYPE;target uuid;
BEGIN
 IF o IS NULL OR public.assistant_patient_role() IS DISTINCT FROM 'authenticated' THEN RAISE EXCEPTION 'Verified owner required' USING ERRCODE='42501'; END IF;
 allowed:=CASE kind WHEN 'prepare_settings' THEN ARRAY['kind','binding'] WHEN 'preferences' THEN ARRAY['kind','binding','values','previous','confirmed']
 WHEN 'create_contact' THEN ARRAY['kind','binding','values','confirmed'] WHEN 'edit_contact' THEN ARRAY['kind','binding','values','contact_id','previous','previous_updated_at','confirmed']
 WHEN 'delete_contact' THEN ARRAY['kind','binding','contact_id','previous','previous_updated_at','confirmed'] WHEN 'feedback' THEN ARRAY['kind','binding','values','confirmed'] END;
 IF allowed IS NULL OR NOT coalesce(public.assistant_wf_keys(p_command,allowed) AND p_command ?& allowed,false) OR octet_length(p_command::text)>16384
 OR NOT coalesce(public.assistant_wf_keys(b,ARRAY['task_id','task_revision','capability_id','action_key','prepared_ref','expected_domain_revision','run_binding']),false)
 OR NOT coalesce(public.assistant_wf_keys(ref,ARRAY['kind','id','version']),false) OR tid IS NULL OR aid IS NULL OR rev IS NULL OR rev<1
 OR ref->>'kind' IS DISTINCT FROM 'settings_review' OR ref->'version' IS DISTINCT FROM '1'::jsonb OR (ref->>'id')::uuid IS NULL
 OR (NOT preparing AND p_command->'confirmed' IS DISTINCT FROM 'true'::jsonb) THEN RAISE EXCEPTION 'Closed independent settings confirmation required' USING ERRCODE='22023'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));digest:=encode(sha256(convert_to(p_command::text,'UTF8')),'hex');
 SELECT * INTO prior FROM public.assistant_settings_commands WHERE owner=o AND action_key=aid;
 IF FOUND THEN
  IF prior.command_digest IS DISTINCT FROM digest THEN RAISE EXCEPTION 'Settings action reused' USING ERRCODE='23505'; END IF;
  RETURN jsonb_build_object('result',public.assistant_settings_result(o,p_command),'replayed',true); END IF;
 IF EXISTS(SELECT 1 FROM public.assistant_business_receipts WHERE owner=o AND action_key=aid) THEN RAISE EXCEPTION 'Action belongs to another command' USING ERRCODE='23505'; END IF;
 SELECT data INTO t FROM public.assistant_workflow_tasks WHERE owner=o AND id=tid FOR UPDATE;
 SELECT data INTO ctl FROM public.assistant_workflow_operations WHERE owner=o AND task_id=tid AND id=tid AND record_type='control' FOR UPDATE;
 generation:=(public.assistant_settings_revision()->>'revision')::bigint;
 IF t IS NULL OR ctl IS NULL OR t->>'capability_id' IS DISTINCT FROM cap OR ctl->>'capability_id' IS DISTINCT FROM cap
 OR (t->>'revision')::int IS DISTINCT FROM rev OR (ctl->>'revision')::int IS DISTINCT FROM rev OR t->>'save_mode' IS DISTINCT FROM 'allowed'
 OR ctl->>'mode' IS DISTINCT FROM 'allowed' OR ctl->'revoked' IS DISTINCT FROM 'false'::jsonb OR ctl->>'status' IS DISTINCT FROM 'idle'
 OR jsonb_array_length(t->'attachment_ids')<>0 OR generation IS DISTINCT FROM (b->>'expected_domain_revision')::bigint THEN
  RAISE EXCEPTION 'Current saved settings scope changed' USING ERRCODE='40001'; END IF;
 IF nullif(b->'run_binding','null'::jsonb) IS NOT NULL THEN PERFORM public.assistant_run_assert_current(o,b->'run_binding'); END IF;
 f:=t->'fields';snapshot:=encode(sha256(convert_to(public.assistant_settings_snapshot(o,t,(ref->>'id')::uuid)::text,'UTF8')),'hex');
 IF preparing THEN
  SELECT * INTO prep FROM public.assistant_settings_commands cmd WHERE owner=o AND task_id=tid AND cmd.kind='prepare_settings' AND prepared_ref=t->'business_refs'->0;
  IF ref->>'id' IS DISTINCT FROM aid::text OR EXISTS(SELECT 1 FROM public.assistant_workflow_operations WHERE owner=o AND id=aid AND record_type='action')
  OR NOT(t->>'state'='ready_for_review' OR (t->>'state'='awaiting_confirmation' AND prep.owner IS NOT NULL
   AND (prep.binding_revision<rev OR prep.domain_revision<>generation OR prep.snapshot_hash IS DISTINCT FROM snapshot))) THEN
   RAISE EXCEPTION 'Prepare a fresh current settings review' USING ERRCODE='40001'; END IF;
  INSERT INTO public.assistant_workflow_operations(owner,record_type,id,task_id,data) VALUES(o,'action',aid,tid,jsonb_build_object('owner',o,'action_key',aid,
   'task_id',tid,'capability_id',cap,'binding_revision',rev,'state','succeeded','business_ref',ref,'safe_reason','settings_prepared',
   'clinical_revision',coalesce((SELECT g.revision FROM public.assistant_enrollment_generations g WHERE g.owner=o),0),'updated_at',clock_timestamp()));
  outref:=ref;
 ELSE
  SELECT * INTO prep FROM public.assistant_settings_commands cmd WHERE owner=o AND task_id=tid AND action_key=(ref->>'id')::uuid AND cmd.kind='prepare_settings';
  IF t->>'state' IS DISTINCT FROM 'awaiting_confirmation' OR t->'business_refs' IS DISTINCT FROM jsonb_build_array(ref)
  OR prep.owner IS NULL OR prep.binding_revision<>rev OR prep.domain_revision<>generation OR prep.snapshot_hash IS DISTINCT FROM snapshot
  OR kind IS DISTINCT FROM (CASE WHEN cap LIKE 'preference.%' OR cap='profile.edit' THEN 'preferences' WHEN cap='caregiver.add' THEN 'create_contact'
   WHEN cap='caregiver.edit' THEN 'edit_contact' WHEN cap='caregiver.delete' THEN 'delete_contact' WHEN cap='feedback.submit' THEN 'feedback' END) THEN
   RAISE EXCEPTION 'Current independent settings review changed' USING ERRCODE='40001'; END IF;
  IF kind='preferences' THEN
   SELECT jsonb_object_agg(key,value) INTO expected FROM jsonb_each(f-'previous') WHERE value<>'null'::jsonb;
   IF v IS DISTINCT FROM expected OR p_command->'previous' IS DISTINCT FROM public.assistant_settings_preferences(o)-ARRAY['patient_id','created_at','updated_at'] THEN
    RAISE EXCEPTION 'Confirm exact preference snapshot and changes' USING ERRCODE='40001'; END IF;
   UPDATE public.patient_profiles SET display_name=coalesce(v->>'display_name',display_name),language=coalesce(v->>'preferred_language',language),
    text_scale_percent=CASE WHEN v ? 'text_scale_percent' THEN (v->>'text_scale_percent')::int WHEN v ? 'text_size' THEN CASE v->>'text_size' WHEN 'large' THEN 125 ELSE 100 END ELSE text_scale_percent END,
    text_size=CASE WHEN v ? 'text_scale_percent' THEN CASE WHEN (v->>'text_scale_percent')::int>=125 THEN 'large' ELSE 'standard' END ELSE coalesce(v->>'text_size',text_size) END,
    voice_enabled=coalesce((v->>'voice_enabled')::boolean,voice_enabled),tts_autoplay=coalesce((v->>'tts_autoplay')::boolean,tts_autoplay),
    conversation_history_enabled=coalesce((v->>'conversation_history_enabled')::boolean,conversation_history_enabled),
    reminders_enabled=coalesce((v->>'reminders_enabled')::boolean,reminders_enabled),reminder_lead_minutes=coalesce((v->>'reminder_lead_minutes')::int,reminder_lead_minutes),timezone=coalesce(v->>'timezone',timezone)
   WHERE user_id=o;
   native:=public.assistant_settings_preferences(o);outref:=jsonb_build_object('kind','preference','id',o,'version',NULL);
  ELSIF kind IN ('create_contact','edit_contact','delete_contact') THEN
   target:=CASE WHEN kind='create_contact' THEN (ref->>'id')::uuid ELSE (f->>'contact_id')::uuid END;
   IF kind<>'create_contact' AND ((p_command->>'contact_id')::uuid IS DISTINCT FROM target OR p_command->'previous' IS DISTINCT FROM public.assistant_settings_contact_values(f->'previous')
    OR (p_command->>'previous_updated_at')::timestamptz IS DISTINCT FROM (f->>'previous_updated_at')::timestamptz) THEN
    RAISE EXCEPTION 'Confirm current owned contact and timestamp' USING ERRCODE='40001'; END IF;
   IF kind<>'delete_contact' THEN
    expected:=public.assistant_settings_contact_values(f-ARRAY['contact_id','previous','previous_updated_at']);
    IF kind='create_contact' THEN expected:=expected||jsonb_build_object('id',target); END IF;
    IF v IS DISTINCT FROM expected THEN RAISE EXCEPTION 'Confirm exact consented contact details' USING ERRCODE='40001'; END IF;
   END IF;
   IF kind='create_contact' THEN
    IF (SELECT count(*) FROM public.caregiver_contacts WHERE patient_id=o)>=20 THEN RAISE EXCEPTION 'Contact limit reached' USING ERRCODE='22023'; END IF;
    INSERT INTO public.caregiver_contacts(patient_id,id,name,relationship,contact_type,contact_value,storage_consent)
    VALUES(o,target,v->>'name',v->>'relationship',v->>'contact_type',v->>'contact_value',true);
   ELSIF kind='edit_contact' THEN
    UPDATE public.caregiver_contacts SET name=v->>'name',relationship=v->>'relationship',contact_type=v->>'contact_type',contact_value=v->>'contact_value',storage_consent=true,updated_at=clock_timestamp()
    WHERE patient_id=o AND id=target;
   ELSE DELETE FROM public.caregiver_contacts WHERE patient_id=o AND id=target; END IF;
   SELECT to_jsonb(x) INTO native FROM public.caregiver_contacts x WHERE patient_id=o AND id=target;native:=coalesce(native,'null'::jsonb);
   outref:=jsonb_build_object('kind','contact','id',target,'version',NULL);
  ELSE
   target:=(ref->>'id')::uuid;expected:=jsonb_build_object('id',target,'category',coalesce(f->>'category','issue'),'message',f->'message');
   IF v IS DISTINCT FROM expected THEN RAISE EXCEPTION 'Confirm exact bounded feedback' USING ERRCODE='40001'; END IF;
   INSERT INTO public.patient_feedback(patient_id,id,category,message) VALUES(o,target,v->>'category',v->>'message');
   SELECT to_jsonb(x) INTO STRICT native FROM public.patient_feedback x WHERE patient_id=o AND id=target;
   outref:=jsonb_build_object('kind','feedback','id',target,'version',NULL);
  END IF;
 END IF;
 IF nullif(b->'run_binding','null'::jsonb) IS NOT NULL THEN PERFORM public.assistant_run_assert_current(o,b->'run_binding'); END IF;
 child:=public.assistant_workflow_command_legacy_035('task_cas',jsonb_build_object('task_id',tid,'expected_revision',rev,'event_id',aid,'request_digest',digest,
  'update',jsonb_build_object('state',CASE WHEN preparing THEN 'awaiting_confirmation' ELSE 'completed' END,'save_mode','allowed','storage_state','saved',
   'fields',f,'missing_fields','[]'::jsonb,'attachment_ids','[]'::jsonb,'business_refs',jsonb_build_array(outref))));
 IF child ? 'error' THEN RAISE EXCEPTION 'Task changed after native settings publication' USING ERRCODE='40001'; END IF;
 generation:=(public.assistant_settings_revision()->>'revision')::bigint;
 INSERT INTO public.assistant_business_receipts(owner,action_key,task_id,capability_id,binding_revision,business_ref,domain_revision,outcome)
 VALUES(o,aid,tid,cap,rev+1,outref,generation,CASE WHEN preparing THEN 'prepared' ELSE 'applied' END);
 INSERT INTO public.assistant_settings_commands(owner,action_key,task_id,capability_id,kind,command_digest,prepared_ref,binding_revision,domain_revision,snapshot_hash,native_hash)
 VALUES(o,aid,tid,cap,kind,digest,ref,rev+1,generation,CASE WHEN preparing THEN snapshot END,CASE WHEN NOT preparing THEN encode(sha256(convert_to(native::text,'UTF8')),'hex') END);
 RETURN jsonb_build_object('result',public.assistant_settings_result(o,p_command),'replayed',false);
END $$;
CREATE FUNCTION public.assistant_settings_prepare(p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF p_command->>'kind' IS DISTINCT FROM 'prepare_settings' THEN RETURN jsonb_build_object('error','invalid'); END IF;
 RETURN public.assistant_settings_apply(p_command);
EXCEPTION WHEN SQLSTATE '40001' THEN RETURN jsonb_build_object('error','stale'); WHEN unique_violation THEN RETURN jsonb_build_object('error','duplicate');
 WHEN SQLSTATE 'P0002' THEN RETURN jsonb_build_object('error','not_found'); WHEN invalid_parameter_value OR invalid_text_representation OR check_violation OR not_null_violation THEN RETURN jsonb_build_object('error','invalid'); END $$;
CREATE FUNCTION public.assistant_settings_write(p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF p_command->>'kind' IS NOT DISTINCT FROM 'prepare_settings' THEN RETURN jsonb_build_object('error','invalid'); END IF;
 RETURN public.assistant_settings_apply(p_command);
EXCEPTION WHEN SQLSTATE '40001' THEN RETURN jsonb_build_object('error','stale'); WHEN unique_violation THEN RETURN jsonb_build_object('error','duplicate');
 WHEN SQLSTATE 'P0002' THEN RETURN jsonb_build_object('error','not_found'); WHEN invalid_parameter_value OR invalid_text_representation OR check_violation OR not_null_violation THEN RETURN jsonb_build_object('error','invalid'); END $$;
CREATE FUNCTION public.assistant_settings_read(p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=public.assistant_patient_uid();c public.assistant_settings_commands%ROWTYPE;
BEGIN
 IF o IS NULL OR public.assistant_patient_role() IS DISTINCT FROM 'authenticated' THEN RAISE EXCEPTION 'Verified owner required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 SELECT * INTO c FROM public.assistant_settings_commands WHERE owner=o AND action_key=(p_command->'binding'->>'action_key')::uuid;
 IF NOT FOUND THEN RETURN jsonb_build_object('error','not_found'); END IF;
 IF c.command_digest IS DISTINCT FROM encode(sha256(convert_to(p_command::text,'UTF8')),'hex') THEN RETURN jsonb_build_object('error','duplicate'); END IF;
 RETURN jsonb_build_object('result',public.assistant_settings_result(o,p_command),'replayed',true);
EXCEPTION WHEN SQLSTATE '40001' THEN RETURN jsonb_build_object('error','stale'); WHEN SQLSTATE 'P0002' THEN RETURN jsonb_build_object('error','stale'); END $$;
DO $$ DECLARE signature text; BEGIN
 FOREACH signature IN ARRAY ARRAY['assistant_settings_epoch_changed()','assistant_settings_revision()','assistant_settings_preferences(uuid)',
 'assistant_settings_contact_values(jsonb)','assistant_settings_snapshot(uuid,jsonb,uuid)','assistant_settings_result(uuid,jsonb)',
 'assistant_settings_apply(jsonb)','assistant_settings_prepare(jsonb)','assistant_settings_write(jsonb)','assistant_settings_read(jsonb)'] LOOP
  EXECUTE 'ALTER FUNCTION public.'||signature||' OWNER TO assistant_workflow_owner';
  EXECUTE 'REVOKE ALL ON FUNCTION public.'||signature||' FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner';
 END LOOP;
END $$;
GRANT EXECUTE ON FUNCTION public.assistant_settings_revision(),public.assistant_settings_prepare(jsonb),public.assistant_settings_write(jsonb),public.assistant_settings_read(jsonb) TO authenticated;
COMMIT;
