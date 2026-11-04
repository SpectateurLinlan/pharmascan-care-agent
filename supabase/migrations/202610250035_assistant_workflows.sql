-- REVIEW DRAFT: do not apply without the scoped SQL/Storage approval record.
-- This migration does not provision Storage, enable a feature, or modify clinical history.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';

CREATE FUNCTION public.assistant_wf_keys(v jsonb, allowed text[]) RETURNS boolean
LANGUAGE sql IMMUTABLE SECURITY INVOKER SET search_path='' AS $$
 SELECT jsonb_typeof(v)='object' AND NOT EXISTS
 (SELECT 1 FROM jsonb_object_keys(v) AS keys(k) WHERE NOT k=ANY(allowed))
$$;

CREATE FUNCTION public.assistant_wf_ref(v jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SECURITY INVOKER SET search_path='' AS $$
 SELECT v IS NULL OR v='null'::jsonb OR coalesce(public.assistant_wf_keys(v,ARRAY['kind','id','version'])
 AND v->>'kind'=ANY(ARRAY['medication','regimen','source','dose_event','observation','stock','barrier',
 'care_task','contact','file','conversation','feedback','preference']) AND (v->>'id')::uuid IS NOT NULL
 AND (v->>'version' IS NULL OR (v->>'version')::int>0),false)
$$;

CREATE FUNCTION public.assistant_wf_writer_ids(v jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SECURITY INVOKER SET search_path='' AS $$
 SELECT CASE WHEN jsonb_typeof(v)='array' AND jsonb_array_length(v)<=64 THEN
 NOT EXISTS(SELECT 1 FROM jsonb_array_elements_text(v) AS writers(id) WHERE id::uuid IS NULL) ELSE false END
$$;

CREATE TABLE public.assistant_workflow_tasks (
 owner uuid NOT NULL REFERENCES public.patient_profiles(user_id), id uuid NOT NULL,
 data jsonb NOT NULL,
 conversation_id uuid GENERATED ALWAYS AS ((data->>'conversation_id')::uuid) STORED,
 PRIMARY KEY(owner,id),
 CHECK(data ?& ARRAY['id','workspace_id','capability_id','capability_version','revision','state',
 'save_mode','storage_state','fields','missing_fields','attachment_ids','business_refs','updated_at']),
 CHECK((data->>'workspace_id')::uuid IS NOT NULL AND data->>'updated_at' IS NOT NULL),
 CHECK(public.assistant_wf_keys(data,ARRAY['id','workspace_id','conversation_id','capability_id','capability_version',
 'revision','state','save_mode','storage_state','fields','missing_fields','attachment_ids','business_refs','updated_at'])),
 CHECK(data->>'id'=id::text AND data->>'save_mode'='allowed'),
 CHECK((data->>'revision')::int>0 AND (data->>'capability_version')::int>0),
 CHECK(data->>'capability_id' ~ '^[a-z][a-z0-9_.]{1,119}$'),
 CHECK(data->>'state'=ANY(ARRAY['choose_method','collecting','validating','ready_for_review','awaiting_confirmation',
 'executing','completed','failed_recoverable','suspended','cancelled','outcome_unknown'])),
 CHECK(data->>'storage_state'=ANY(ARRAY['saving','saved','save_failed','cleanup_pending'])),
 CHECK(jsonb_typeof(data->'fields')='object' AND octet_length(convert_to((data->'fields')::text,'UTF8'))<=16384),
 CHECK(jsonb_typeof(data->'missing_fields')='array' AND jsonb_array_length(data->'missing_fields')<=100),
 CHECK(jsonb_typeof(data->'attachment_ids')='array' AND jsonb_array_length(data->'attachment_ids')<=10),
 CHECK(jsonb_typeof(data->'business_refs')='array' AND jsonb_array_length(data->'business_refs')<=20),
 CHECK(octet_length(convert_to(data::text,'UTF8'))<=24576),
 FOREIGN KEY(owner,conversation_id) REFERENCES public.conversations(patient_id,id)
);

CREATE TABLE public.assistant_workflow_operations (
 owner uuid NOT NULL REFERENCES public.patient_profiles(user_id), record_type text NOT NULL,
 id uuid NOT NULL, task_id uuid NOT NULL, data jsonb NOT NULL,
 conversation_id uuid GENERATED ALWAYS AS (CASE WHEN record_type='control' THEN (data->>'conversation_id')::uuid ELSE NULL END) STORED,
 PRIMARY KEY(owner,record_type,task_id,id),
 FOREIGN KEY(owner,conversation_id) REFERENCES public.conversations(patient_id,id),
 CHECK(record_type=ANY(ARRAY['control','used_event','event','action','cleanup'])),
 CHECK(jsonb_typeof(data)='object' AND octet_length(convert_to(data::text,'UTF8'))<=4096),
 CHECK(coalesce(CASE record_type
 WHEN 'control' THEN id=task_id AND public.assistant_wf_keys(data,ARRAY['task_id','revision','capability_id',
 'workspace_id','conversation_id','status','mode','revoked','processing_event_id','lease_until'])
 AND data->>'task_id'=task_id::text AND (data->>'revision')::int>0
 AND data->>'mode'=ANY(ARRAY['allowed','ephemeral'])
 AND data->>'status'=ANY(ARRAY['idle','processing','interrupted','suspended','cancelled','completed'])
 AND jsonb_typeof(data->'revoked')='boolean' AND data->>'capability_id' ~ '^[a-z][a-z0-9_.]{1,119}$'
 AND (data->>'workspace_id' IS NULL OR (data->>'workspace_id')::uuid IS NOT NULL)
 AND (data->>'processing_event_id' IS NULL OR (data->>'processing_event_id')::uuid IS NOT NULL)
 AND (data->>'lease_until' IS NULL OR (data->>'lease_until')::timestamptz IS NOT NULL)
 WHEN 'used_event' THEN data='{}'::jsonb
 WHEN 'event' THEN public.assistant_wf_keys(data,ARRAY['request_digest','result_revision'])
 AND (data->>'result_revision')::int>0
 AND (data->>'request_digest' IS NULL OR data->>'request_digest' ~ '^[a-f0-9]{64}(:[a-z_]{1,40})?$')
 WHEN 'action' THEN public.assistant_wf_keys(data,ARRAY['action_key','task_id','capability_id','binding_revision',
 'state','business_ref','safe_reason','updated_at']) AND data->>'action_key'=id::text
 AND data->>'task_id'=task_id::text AND (data->>'binding_revision')::int>0
 AND data->>'state'=ANY(ARRAY['pending','succeeded','failed','outcome_unknown'])
 AND data->>'capability_id' ~ '^[a-z][a-z0-9_.]{1,119}$' AND public.assistant_wf_ref(data->'business_ref')
 AND (data->>'safe_reason' IS NULL OR data->>'safe_reason' ~ '^[a-z_]{1,80}$')
 WHEN 'cleanup' THEN public.assistant_wf_keys(data,ARRAY['id','task_id','object_ref','content_type','source_ref',
 'state','writer_pending','reason','pending_writer_ids','multiple_writers']) AND data->>'id'=id::text AND data->>'task_id'=task_id::text
 AND data->>'object_ref'=owner::text||'/workflow-originals/'||task_id::text||'/'||id::text
 AND data->>'state'=ANY(ARRAY['pending','deleted','protected','failed'])
 AND data->>'content_type'=ANY(ARRAY['image/png','image/jpeg']) AND jsonb_typeof(data->'writer_pending')='boolean'
 AND public.assistant_wf_ref(data->'source_ref')
 AND public.assistant_wf_writer_ids(data->'pending_writer_ids') AND jsonb_typeof(data->'multiple_writers')='boolean'
 AND (data->>'reason' IS NULL OR data->>'reason'=ANY(ARRAY['upload_inflight','storage_unavailable',
 'protection_unavailable','formal_source','reference_unresolved','shared_reference','operation_unknown','business_record','removed']))
 ELSE false END,false))
);
CREATE INDEX assistant_workflow_operations_task ON public.assistant_workflow_operations(owner,task_id,record_type);
CREATE UNIQUE INDEX assistant_workflow_operation_identity ON public.assistant_workflow_operations(owner,record_type,id)
 WHERE record_type IN ('control','action','cleanup');

CREATE TABLE public.assistant_workflow_attachments (
 owner uuid NOT NULL, id uuid NOT NULL, task_id uuid NOT NULL, upload_id uuid NOT NULL,
 data jsonb NOT NULL,
 source_id uuid GENERATED ALWAYS AS ((data->'source_ref'->>'id')::uuid) STORED,
 PRIMARY KEY(owner,id), UNIQUE(owner,task_id,upload_id),
 FOREIGN KEY(owner,task_id) REFERENCES public.assistant_workflow_tasks(owner,id),
 FOREIGN KEY(owner,source_id) REFERENCES public.source_documents(patient_id,id),
 CHECK(data ?& ARRAY['id','task_id','upload_id','binding_revision','object_ref','original_checksum',
 'content_type','source_kind','byte_size','state','extraction_status','cleanup_pending','object_written']),
 CHECK(public.assistant_wf_ref(data->'source_ref') AND (data->'source_ref' IS NULL OR data->'source_ref'='null'::jsonb OR data->'source_ref'->>'kind'='source')),
 CHECK(public.assistant_wf_keys(data,ARRAY['id','task_id','upload_id','binding_revision','object_ref',
 'original_checksum','content_type','source_kind','byte_size','state','extraction_status','extraction','reason',
 'source_ref','cleanup_pending','object_written','operation_event_id','pending_writer_ids','multiple_writers'])),
 CHECK(public.assistant_wf_writer_ids(data->'pending_writer_ids') AND jsonb_typeof(data->'multiple_writers')='boolean'),
 CHECK(data->>'operation_event_id' IS NULL OR (data->>'operation_event_id')::uuid IS NOT NULL),
 CHECK(data->>'id'=id::text AND data->>'task_id'=task_id::text AND data->>'upload_id'=upload_id::text),
 CHECK(data->>'object_ref'=owner::text||'/workflow-originals/'||task_id::text||'/'||id::text),
 CHECK(data->>'original_checksum' ~ '^[a-f0-9]{64}$' AND (data->>'binding_revision')::int>0),
 CHECK(data->>'content_type'=ANY(ARRAY['image/png','image/jpeg'])),
 CHECK(data->>'source_kind'=ANY(ARRAY['package','pharmacy_label','prescription'])),
 CHECK((data->>'byte_size')::int BETWEEN 1 AND 8000000),
 CHECK(data->>'state'=ANY(ARRAY['reserved','saved'])),
 CHECK(data->>'extraction_status'=ANY(ARRAY['pending','consent_required','succeeded','failed','interrupted'])),
 CHECK(jsonb_typeof(data->'object_written')='boolean' AND jsonb_typeof(data->'cleanup_pending')='boolean'),
 CHECK(data->>'reason' IS NULL OR data->>'reason'=ANY(ARRAY['provider_unavailable','processing_consent_required','extraction_rejected','extraction_interrupted'])),
 CHECK(octet_length(convert_to(data::text,'UTF8'))<=131072)
);

-- All mutating application access uses the single fixed command below.
-- Direct authenticated writes are denied; the command derives owner only from auth.uid().
ALTER TABLE public.assistant_workflow_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assistant_workflow_tasks FORCE ROW LEVEL SECURITY;
ALTER TABLE public.assistant_workflow_operations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assistant_workflow_operations FORCE ROW LEVEL SECURITY;
ALTER TABLE public.assistant_workflow_attachments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assistant_workflow_attachments FORCE ROW LEVEL SECURITY;
CREATE POLICY assistant_workflow_tasks_owner ON public.assistant_workflow_tasks FOR SELECT TO authenticated USING(owner=(SELECT auth.uid()));
CREATE POLICY assistant_workflow_operations_owner ON public.assistant_workflow_operations FOR SELECT TO authenticated USING(owner=(SELECT auth.uid()));
CREATE POLICY assistant_workflow_attachments_owner ON public.assistant_workflow_attachments FOR SELECT TO authenticated USING(owner=(SELECT auth.uid()));
REVOKE ALL ON public.assistant_workflow_tasks,public.assistant_workflow_operations,public.assistant_workflow_attachments FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT ON public.assistant_workflow_tasks,public.assistant_workflow_operations,public.assistant_workflow_attachments TO authenticated;

CREATE FUNCTION public.assistant_workflow_command(p_operation text,p_input jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE
 o uuid:=auth.uid(); tid uuid; eid uuid; aid uuid; rev int; ctx jsonb; v jsonb; c jsonb; a jsonb; previous jsonb;
 result jsonb; child jsonb; r record; terminal boolean; desired text; digest text;
BEGIN
 IF o IS NULL OR coalesce(nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'role',
  current_setting('request.jwt.claim.role',true),'')<>'authenticated' THEN
  RAISE EXCEPTION 'Patient authentication required' USING ERRCODE='42501';
 END IF;
 IF jsonb_typeof(p_input)<>'object' OR p_input ? 'owner' OR octet_length(convert_to(p_input::text,'UTF8'))>163840
 THEN RETURN jsonb_build_object('error','invalid'); END IF;
 -- Serialize this owner's foreground, event and original transactions, including concurrent first creation.
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 ctx:=p_input->'context';
 IF ctx ? 'owner' THEN RETURN jsonb_build_object('error','invalid'); END IF;
 tid:=coalesce(p_input->>'task_id',ctx->>'task_id')::uuid;
 eid:=(p_input->>'event_id')::uuid;
 rev:=coalesce(p_input->>'expected_revision',ctx->>'revision')::int;
 SELECT data INTO c FROM public.assistant_workflow_operations WHERE owner=o AND record_type='control' AND id=tid;
 IF c->>'processing_event_id' IS NOT NULL AND (c->>'lease_until')::timestamptz<=clock_timestamp()
 THEN c:=c||'{"status":"interrupted"}'::jsonb; END IF;
 SELECT data INTO v FROM public.assistant_workflow_tasks WHERE owner=o AND id=tid;
 terminal:=c->>'status' IN ('cancelled','completed');

 IF p_operation='task_list' THEN
  SELECT coalesce(jsonb_agg(data||jsonb_build_object('owner',o)),'[]') INTO result FROM
  (SELECT data FROM public.assistant_workflow_tasks WHERE owner=o
   AND (p_input->>'workspace_id' IS NULL OR data->>'workspace_id'=p_input->>'workspace_id') ORDER BY id LIMIT 2001) s;
  RETURN jsonb_build_object('result',result);
 ELSIF p_operation='control_list' THEN
  SELECT coalesce(jsonb_agg(data||jsonb_build_object('owner',o)),'[]') INTO result FROM
  (SELECT CASE WHEN data->>'processing_event_id' IS NOT NULL AND (data->>'lease_until')::timestamptz<=clock_timestamp()
   THEN data||'{"status":"interrupted"}'::jsonb ELSE data END data
   FROM public.assistant_workflow_operations WHERE owner=o AND record_type='control' ORDER BY id LIMIT 2001) s;
  RETURN jsonb_build_object('result',result);
 ELSIF p_operation='task_get' THEN
  IF v IS NULL THEN RETURN jsonb_build_object('error','not_found'); END IF;
  RETURN jsonb_build_object('result',v||jsonb_build_object('owner',o));
 ELSIF p_operation='control_get' THEN
  IF c IS NULL THEN RETURN jsonb_build_object('error','not_found'); END IF;
  RETURN jsonb_build_object('result',c||jsonb_build_object('owner',o));
 ELSIF p_operation='task_event' THEN
  IF v IS NULL THEN RETURN jsonb_build_object('error','not_found'); END IF;
  SELECT data INTO previous FROM public.assistant_workflow_operations WHERE owner=o AND task_id=tid AND record_type='event' AND id=eid;
  IF previous IS NULL THEN RETURN jsonb_build_object('result',NULL); END IF;
  IF previous->>'request_digest' IS DISTINCT FROM p_input->>'request_digest' THEN RETURN jsonb_build_object('error','duplicate'); END IF;
  -- Saved event receipts contain no body snapshot. Replays return current owned state, never reapply an old update.
  RETURN jsonb_build_object('result',v||jsonb_build_object('owner',o));
 END IF;

 IF p_operation IN ('task_create','control_create') THEN
  a:=CASE WHEN p_operation='task_create' THEN p_input->'task' ELSE p_input->'receipt' END;
  IF a ? 'owner' OR a->>'id' IS DISTINCT FROM tid::text AND p_operation='task_create'
     OR a->>'task_id' IS DISTINCT FROM tid::text AND p_operation='control_create'
  THEN RETURN jsonb_build_object('error','invalid'); END IF;
  IF p_operation='task_create' AND v IS NOT NULL THEN
   IF eid IS NULL THEN RETURN jsonb_build_object('error','duplicate'); END IF;
   RETURN public.assistant_workflow_command('task_event',p_input);
  END IF;
  IF p_operation='control_create' AND c IS NOT NULL THEN RETURN jsonb_build_object('error','duplicate'); END IF;
  IF c IS NOT NULL AND (c->>'mode'<>'allowed' OR (c->>'revoked')::boolean OR c->>'revision'<>a->>'revision')
  THEN RETURN jsonb_build_object('error','stale'); END IF;
  IF c IS NULL THEN
   c:=CASE WHEN p_operation='control_create' THEN a ELSE jsonb_build_object('task_id',tid,'revision',(a->>'revision')::int,
    'capability_id',a->>'capability_id','workspace_id',a->'workspace_id','conversation_id',a->'conversation_id',
    'status','idle','mode','allowed','revoked',false,'processing_event_id',NULL,'lease_until',NULL) END;
   IF c->>'status'<>'idle' OR c->>'processing_event_id' IS NOT NULL OR (c->>'revision')::int<>1
   THEN RETURN jsonb_build_object('error','invalid'); END IF;
  END IF;
  IF (p_input->>'suspend_foreground')::boolean THEN
   FOR r IN SELECT id,data FROM public.assistant_workflow_operations WHERE owner=o AND record_type='control' AND id<>tid
    AND data->>'status' NOT IN ('suspended','cancelled','completed')
    AND (CASE WHEN c->>'conversation_id' IS NOT NULL THEN data->>'conversation_id'=c->>'conversation_id'
     ELSE data->>'conversation_id' IS NULL AND data->>'workspace_id'=c->>'workspace_id' END)
   LOOP
    UPDATE public.assistant_workflow_operations SET data=data||jsonb_build_object('status','suspended','revision',(data->>'revision')::int+1,
     'processing_event_id',NULL,'lease_until',NULL) WHERE owner=o AND record_type='control' AND id=r.id;
    UPDATE public.assistant_workflow_tasks SET data=data||jsonb_build_object('state','suspended','revision',(data->>'revision')::int+1,
     'updated_at',clock_timestamp()) WHERE owner=o AND id=r.id;
   END LOOP;
  END IF;
  INSERT INTO public.assistant_workflow_operations(owner,record_type,id,task_id,data) VALUES(o,'control',tid,tid,c)
   ON CONFLICT(owner,record_type,task_id,id) DO UPDATE SET data=EXCLUDED.data;
  IF p_operation='control_create' THEN RETURN jsonb_build_object('result',c||jsonb_build_object('owner',o)); END IF;
  INSERT INTO public.assistant_workflow_tasks(owner,id,data) VALUES(o,tid,a);
  IF eid IS NOT NULL THEN
   INSERT INTO public.assistant_workflow_operations(owner,record_type,id,task_id,data) VALUES(o,'used_event',eid,tid,'{}');
   INSERT INTO public.assistant_workflow_operations(owner,record_type,id,task_id,data) VALUES(o,'event',eid,tid,
    jsonb_build_object('request_digest',p_input->>'request_digest','result_revision',(a->>'revision')::int));
  END IF;
  RETURN jsonb_build_object('result',a||jsonb_build_object('owner',o));
 END IF;

 IF p_operation IN ('task_cas','task_bind') OR p_operation LIKE 'control_%' THEN
  IF c IS NULL THEN RETURN jsonb_build_object('error','not_found'); END IF;
  IF p_operation='task_cas' THEN
   SELECT data INTO previous FROM public.assistant_workflow_operations WHERE owner=o AND record_type='event' AND id=eid AND task_id=tid;
   IF previous IS NOT NULL THEN RETURN public.assistant_workflow_command('task_event',p_input); END IF;
  END IF;
  IF (c->>'revision')::int IS DISTINCT FROM rev THEN RETURN jsonb_build_object('error','stale'); END IF;
  terminal:=c->>'status' IN ('cancelled','completed');
  IF p_operation='control_claim' THEN
   IF c->>'capability_id' IS DISTINCT FROM p_input->>'capability_id' OR c->>'mode' IS DISTINCT FROM p_input->>'mode'
    OR terminal THEN RETURN jsonb_build_object('error','invalid'); END IF;
   IF c->>'processing_event_id' IS NOT NULL THEN RETURN jsonb_build_object('error','stale'); END IF;
   INSERT INTO public.assistant_workflow_operations(owner,record_type,id,task_id,data) VALUES(o,'used_event',eid,tid,'{}');
   c:=c||jsonb_build_object('processing_event_id',eid,'lease_until',clock_timestamp()+interval '45 seconds','status','processing');
  ELSIF p_operation='control_revoke' OR p_operation='control_mode' AND p_input->>'mode'='ephemeral' THEN
   IF eid IS NOT NULL THEN INSERT INTO public.assistant_workflow_operations(owner,record_type,id,task_id,data) VALUES(o,'used_event',eid,tid,'{}'); END IF;
   -- Cleanup intents and hash/body removal are committed in the same transaction.
   INSERT INTO public.assistant_workflow_operations(owner,record_type,id,task_id,data)
    SELECT o,'cleanup',id,tid,jsonb_build_object('id',id,'task_id',tid,'object_ref',data->>'object_ref',
      'content_type',data->>'content_type','source_ref',data->'source_ref','state','pending',
      'writer_pending',jsonb_array_length(data->'pending_writer_ids')>0 OR NOT (data->>'object_written')::boolean,
      'pending_writer_ids',data->'pending_writer_ids','multiple_writers',data->'multiple_writers',
      'reason',CASE WHEN NOT (data->>'object_written')::boolean THEN 'upload_inflight' ELSE NULL END)
    FROM public.assistant_workflow_attachments WHERE owner=o AND task_id=tid;
   DELETE FROM public.assistant_workflow_attachments WHERE owner=o AND task_id=tid;
   DELETE FROM public.assistant_workflow_tasks WHERE owner=o AND id=tid;
   DELETE FROM public.assistant_workflow_operations WHERE owner=o AND task_id=tid AND record_type='event';
   c:=c||jsonb_build_object('revision',rev+1,'mode','ephemeral','revoked',true,'processing_event_id',NULL,'lease_until',NULL,
    'status',CASE WHEN c->>'status' IN ('suspended','cancelled','completed') THEN c->>'status' ELSE 'idle' END);
  ELSIF p_operation='control_mode' THEN
   IF p_input->>'mode'<>'allowed' OR terminal OR c->>'status' IN ('processing','interrupted') THEN RETURN jsonb_build_object('error','invalid'); END IF;
   INSERT INTO public.assistant_workflow_operations(owner,record_type,id,task_id,data) VALUES(o,'used_event',eid,tid,'{}');
   c:=c||jsonb_build_object('revision',rev+1,'mode','allowed','revoked',false);
  ELSIF p_operation='control_recover' THEN
   IF c->>'status'<>'interrupted' THEN RETURN jsonb_build_object('error','stale'); END IF;
   INSERT INTO public.assistant_workflow_operations(owner,record_type,id,task_id,data) VALUES(o,'used_event',eid,tid,'{}');
   c:=c||jsonb_build_object('revision',rev+1,'status','idle','processing_event_id',NULL,'lease_until',NULL);
   UPDATE public.assistant_workflow_tasks SET data=data||jsonb_build_object('revision',rev+1,'state','outcome_unknown','updated_at',clock_timestamp()) WHERE owner=o AND id=tid;
  ELSIF p_operation IN ('control_finish','task_cas') THEN
   IF c->>'processing_event_id' IS NOT NULL AND (c->>'processing_event_id' IS DISTINCT FROM eid::text
    OR c->>'status'='interrupted') THEN RETURN jsonb_build_object('error','stale'); END IF;
   IF p_operation='control_finish' AND c->>'processing_event_id' IS NULL THEN RETURN jsonb_build_object('error','stale'); END IF;
   IF p_operation='task_cas' THEN
    IF v IS NULL OR c->>'mode'<>'allowed' OR (c->>'revoked')::boolean OR (v->>'revision')::int<>rev
    THEN RETURN jsonb_build_object('error','stale'); END IF;
    IF NOT public.assistant_wf_keys(p_input->'update',ARRAY['state','save_mode','storage_state','fields','missing_fields','attachment_ids','business_refs'])
    THEN RETURN jsonb_build_object('error','invalid'); END IF;
    v:=v||(p_input->'update')||jsonb_build_object('revision',rev+1,'updated_at',clock_timestamp());
    UPDATE public.assistant_workflow_tasks SET data=v WHERE owner=o AND id=tid;
    INSERT INTO public.assistant_workflow_operations(owner,record_type,id,task_id,data) VALUES(o,'event',eid,tid,
     jsonb_build_object('request_digest',p_input->>'request_digest','result_revision',rev+1));
    INSERT INTO public.assistant_workflow_operations(owner,record_type,id,task_id,data) VALUES(o,'used_event',eid,tid,'{}') ON CONFLICT DO NOTHING;
    desired:=CASE WHEN v->>'state' IN ('suspended','cancelled','completed') THEN v->>'state' ELSE 'idle' END;
   ELSE desired:=p_input->>'status'; END IF;
   c:=c||jsonb_build_object('revision',rev+1,'status',desired,'processing_event_id',NULL,'lease_until',NULL);
  ELSIF p_operation='task_bind' THEN
   IF v IS NULL OR c->>'mode'<>'allowed' OR (c->>'revoked')::boolean OR c->>'processing_event_id' IS NOT NULL
    OR (v->>'revision')::int<>rev OR v->>'conversation_id' IS NOT NULL AND v->>'conversation_id' IS DISTINCT FROM p_input->>'conversation_id'
   THEN RETURN jsonb_build_object('error','stale'); END IF;
   IF v->>'conversation_id'=p_input->>'conversation_id' THEN RETURN jsonb_build_object('result',v||jsonb_build_object('owner',o)); END IF;
   v:=v||jsonb_build_object('conversation_id',p_input->'conversation_id','revision',rev+1,'updated_at',clock_timestamp());
   c:=c||jsonb_build_object('conversation_id',p_input->'conversation_id','revision',rev+1);
   UPDATE public.assistant_workflow_tasks SET data=v WHERE owner=o AND id=tid;
  ELSE RETURN jsonb_build_object('error','invalid'); END IF;
  -- Exactly one foreground task/control per owned conversation, otherwise workspace.
  IF c->>'status' NOT IN ('suspended','cancelled','completed') THEN
   FOR r IN SELECT id,data FROM public.assistant_workflow_operations WHERE owner=o AND record_type='control' AND id<>tid
    AND data->>'status' NOT IN ('suspended','cancelled','completed')
    AND CASE WHEN c->>'conversation_id' IS NOT NULL THEN data->>'conversation_id'=c->>'conversation_id'
      ELSE data->>'conversation_id' IS NULL AND data->>'workspace_id'=c->>'workspace_id' END
   LOOP
    UPDATE public.assistant_workflow_operations SET data=data||jsonb_build_object('status','suspended','revision',(data->>'revision')::int+1,'processing_event_id',NULL,'lease_until',NULL)
     WHERE owner=o AND record_type='control' AND id=r.id;
    UPDATE public.assistant_workflow_tasks SET data=data||jsonb_build_object('state','suspended','revision',(data->>'revision')::int+1,'updated_at',clock_timestamp()) WHERE owner=o AND id=r.id;
   END LOOP;
  END IF;
  UPDATE public.assistant_workflow_operations SET data=c WHERE owner=o AND record_type='control' AND id=tid;
  RETURN jsonb_build_object('result',CASE WHEN p_operation IN ('task_cas','task_bind') THEN v ELSE c END||jsonb_build_object('owner',o));
 END IF;

 IF p_operation LIKE 'action_%' THEN
  aid:=coalesce(p_input->>'action_key',p_input->'receipt'->>'action_key')::uuid;
  SELECT data INTO a FROM public.assistant_workflow_operations WHERE owner=o AND record_type='action' AND id=aid;
  IF p_operation='action_list' THEN
   SELECT coalesce(jsonb_agg(data||jsonb_build_object('owner',o)),'[]') INTO result FROM
    (SELECT data FROM public.assistant_workflow_operations WHERE owner=o AND record_type='action' AND task_id=tid ORDER BY id LIMIT 2001) s;
   RETURN jsonb_build_object('result',result);
  ELSIF p_operation='action_get' THEN
   IF a IS NULL THEN RETURN jsonb_build_object('error','not_found'); END IF;
   RETURN jsonb_build_object('result',a||jsonb_build_object('owner',o));
  END IF;
  IF a IS NOT NULL AND (a->>'task_id' IS DISTINCT FROM ctx->>'task_id' OR a->>'capability_id' IS DISTINCT FROM ctx->>'capability_id'
   OR a->>'binding_revision' IS DISTINCT FROM ctx->>'revision') THEN RETURN jsonb_build_object('error','stale'); END IF;
  IF p_operation='action_reserve' THEN
   IF ctx->>'save_mode'<>'allowed' OR c IS NULL OR c->>'mode'<>'allowed' OR (c->>'revoked')::boolean
    OR c->>'revision' IS DISTINCT FROM ctx->>'revision' OR c->>'capability_id' IS DISTINCT FROM ctx->>'capability_id'
    OR terminal THEN RETURN jsonb_build_object('error','stale'); END IF;
   IF a IS NULL THEN
    a:=jsonb_build_object('action_key',aid,'task_id',tid,'capability_id',ctx->>'capability_id','binding_revision',rev,
      'state','pending','business_ref',NULL,'safe_reason',NULL,'updated_at',clock_timestamp());
    INSERT INTO public.assistant_workflow_operations(owner,record_type,id,task_id,data) VALUES(o,'action',aid,tid,a);
   END IF;
  ELSIF p_operation='action_complete' THEN
   IF a IS NULL THEN RETURN jsonb_build_object('error','not_found'); END IF;
   previous:=p_input->'receipt';
   -- A public JWT call cannot attest that another business service committed.
   -- Terminal publication needs the future coupled/verified business RPC.
   IF previous->>'state' IN ('succeeded','failed') THEN RETURN jsonb_build_object('error','unavailable'); END IF;
   IF previous ? 'owner' OR previous->>'task_id' IS DISTINCT FROM a->>'task_id'
    OR previous->>'capability_id' IS DISTINCT FROM a->>'capability_id'
    OR previous->>'binding_revision' IS DISTINCT FROM a->>'binding_revision'
    OR a->'business_ref'<>'null'::jsonb AND a->'business_ref' IS DISTINCT FROM previous->'business_ref'
    OR a->>'state' IN ('succeeded','failed') AND a->>'state' IS DISTINCT FROM previous->>'state'
    OR a->>'state'='outcome_unknown' AND previous->>'state'='pending'
   THEN RETURN jsonb_build_object('error','duplicate'); END IF;
   a:=previous;
   UPDATE public.assistant_workflow_operations SET data=a WHERE owner=o AND record_type='action' AND id=aid;
  ELSE RETURN jsonb_build_object('error','invalid'); END IF;
  RETURN jsonb_build_object('result',a||jsonb_build_object('owner',o));
 END IF;

 IF p_operation LIKE 'cleanup_%' THEN
  aid:=coalesce(p_input->>'attachment_id',p_input->'receipt'->>'id')::uuid;
  SELECT data INTO a FROM public.assistant_workflow_operations WHERE owner=o AND record_type='cleanup' AND id=aid;
  IF p_operation='cleanup_list' THEN
   SELECT coalesce(jsonb_agg(data||jsonb_build_object('owner',o)),'[]') INTO result FROM
    (SELECT data FROM public.assistant_workflow_operations WHERE owner=o AND record_type='cleanup' AND task_id=tid ORDER BY id LIMIT 2001) s;
   RETURN jsonb_build_object('result',result);
  END IF;
  IF a IS NULL OR tid IS NOT NULL AND a->>'task_id'<>tid::text THEN RETURN jsonb_build_object('error','not_found'); END IF;
  IF p_operation='cleanup_written' THEN
   result:=CASE WHEN p_input->>'writer_id' IS NULL THEN CASE WHEN (a->>'multiple_writers')::boolean THEN a->'pending_writer_ids' ELSE '[]'::jsonb END
    ELSE coalesce((SELECT jsonb_agg(x) FROM jsonb_array_elements(a->'pending_writer_ids') x WHERE x<>to_jsonb((p_input->>'writer_id')::uuid)),'[]'::jsonb) END;
   a:=a||jsonb_build_object('writer_pending',jsonb_array_length(result)>0,'pending_writer_ids',result,'state','pending','reason',NULL);
  ELSIF p_operation='cleanup_update' THEN
   previous:=p_input->'receipt';
   -- Storage metadata absence alone is not physical object deletion evidence.
   IF previous->>'state'='deleted' THEN RETURN jsonb_build_object('error','unavailable'); END IF;
   IF previous->>'task_id' IS DISTINCT FROM a->>'task_id' OR previous->>'object_ref' IS DISTINCT FROM a->>'object_ref'
    OR previous->'source_ref' IS DISTINCT FROM a->'source_ref' THEN RETURN jsonb_build_object('error','invalid'); END IF;
   a:=previous||jsonb_build_object('writer_pending',a->'writer_pending','pending_writer_ids',a->'pending_writer_ids','multiple_writers',a->'multiple_writers');
  ELSIF p_operation<>'cleanup_get' THEN RETURN jsonb_build_object('error','invalid'); END IF;
  UPDATE public.assistant_workflow_operations SET data=a WHERE owner=o AND record_type='cleanup' AND id=aid;
  RETURN jsonb_build_object('result',a||jsonb_build_object('owner',o));
 END IF;

 IF p_operation LIKE 'original_%' THEN
  aid:=coalesce(p_input->>'attachment_id',p_input->'attachment'->>'id')::uuid;
  SELECT data INTO a FROM public.assistant_workflow_attachments WHERE owner=o AND id=aid AND task_id=tid;
  IF p_operation='original_list' THEN
   SELECT coalesce(jsonb_agg(data||jsonb_build_object('owner',o)),'[]') INTO result FROM
    (SELECT data FROM public.assistant_workflow_attachments WHERE owner=o AND (tid IS NULL OR task_id=tid) ORDER BY id LIMIT 2001) s;
   RETURN jsonb_build_object('result',result);
  ELSIF p_operation='original_upload' THEN
   SELECT data INTO a FROM public.assistant_workflow_attachments WHERE owner=o AND task_id=tid AND upload_id=(p_input->>'upload_id')::uuid;
   RETURN jsonb_build_object('result',CASE WHEN a IS NULL THEN NULL ELSE a||jsonb_build_object('owner',o) END);
  ELSIF p_operation='original_written' THEN
   IF a IS NULL THEN RETURN jsonb_build_object('result',false); END IF;
   result:=CASE WHEN p_input->>'writer_id' IS NULL THEN CASE WHEN (a->>'multiple_writers')::boolean THEN a->'pending_writer_ids' ELSE '[]'::jsonb END
    ELSE coalesce((SELECT jsonb_agg(x) FROM jsonb_array_elements(a->'pending_writer_ids') x WHERE x<>to_jsonb((p_input->>'writer_id')::uuid)),'[]'::jsonb) END;
   UPDATE public.assistant_workflow_attachments SET data=data||jsonb_build_object('object_written',true,'pending_writer_ids',result) WHERE owner=o AND id=aid AND task_id=tid;
   RETURN jsonb_build_object('result',true);
  ELSIF p_operation='original_get' THEN
   IF a IS NULL THEN RETURN jsonb_build_object('error','not_found'); END IF;
   RETURN jsonb_build_object('result',a||jsonb_build_object('owner',o));
  END IF;
  IF v IS NULL OR c IS NULL OR c->>'mode'<>'allowed' OR (c->>'revoked')::boolean OR v->>'state' IN ('completed','cancelled')
   OR ctx->>'capability_id' IS DISTINCT FROM v->>'capability_id' THEN RETURN jsonb_build_object('error','stale'); END IF;
  IF p_operation='original_reserve' THEN
   previous:=p_input->'attachment'; eid:=(previous->>'upload_id')::uuid;
   IF a IS NOT NULL OR jsonb_array_length(v->'attachment_ids')>=10 OR previous->>'task_id'<>tid::text
    OR previous->>'binding_revision' IS DISTINCT FROM ctx->>'revision' OR previous ? 'owner' THEN RETURN jsonb_build_object('error','invalid'); END IF;
   child:=public.assistant_workflow_command('control_claim',jsonb_build_object('task_id',tid,'expected_revision',rev,
    'event_id',eid,'capability_id',ctx->>'capability_id','mode','allowed'));
   IF child ? 'error' THEN RETURN child; END IF;
   previous:=previous||jsonb_build_object('operation_event_id',eid,'pending_writer_ids',jsonb_build_array(eid),'multiple_writers',false);
   INSERT INTO public.assistant_workflow_attachments(owner,id,task_id,upload_id,data) VALUES(o,aid,tid,eid,previous);
   RETURN jsonb_build_object('result',previous||jsonb_build_object('owner',o));
  END IF;
  IF a IS NULL THEN RETURN jsonb_build_object('error','not_found'); END IF;
  IF p_operation IN ('original_retry','original_begin') THEN
   IF p_operation='original_retry' AND a->>'state'<>'reserved'
    OR p_operation='original_begin' AND a->>'state'<>'saved' THEN RETURN jsonb_build_object('error','invalid'); END IF;
   child:=public.assistant_workflow_command('control_claim',jsonb_build_object('task_id',tid,'expected_revision',rev,
    'event_id',eid,'capability_id',ctx->>'capability_id','mode','allowed'));
   IF child ? 'error' THEN RETURN child; END IF;
   a:=a||jsonb_build_object('operation_event_id',eid);
   IF p_operation='original_retry' THEN
    IF coalesce((p_input->>'starts_writer')::boolean,true) THEN
     a:=a||jsonb_build_object('multiple_writers',(a->>'multiple_writers')::boolean OR jsonb_array_length(a->'pending_writer_ids')>0,
        'pending_writer_ids',(a->'pending_writer_ids')||jsonb_build_array(eid));
    END IF;
    a:=a||jsonb_build_object('binding_revision',rev);
   ELSE a:=a||jsonb_build_object('extraction_status','pending','reason',NULL); END IF;
   UPDATE public.assistant_workflow_attachments SET data=a WHERE owner=o AND id=aid AND task_id=tid;
   RETURN jsonb_build_object('result',a||jsonb_build_object('owner',o));
  END IF;
  IF p_operation='original_protect' THEN
   IF NOT public.assistant_wf_ref(p_input->'source_ref') OR p_input->'source_ref'->>'kind' IS DISTINCT FROM 'source'
    THEN RETURN jsonb_build_object('error','invalid'); END IF;
   IF a->'source_ref' IS NOT NULL AND a->'source_ref'<>'null'::jsonb AND a->'source_ref' IS DISTINCT FROM p_input->'source_ref'
    THEN RETURN jsonb_build_object('error','duplicate'); END IF;
   IF NOT EXISTS(SELECT 1 FROM public.source_documents WHERE patient_id=o AND id=(p_input->'source_ref'->>'id')::uuid
     AND review_status IN ('user_reviewed','professional_verified') AND reviewed_at IS NOT NULL)
    THEN RETURN jsonb_build_object('error','invalid'); END IF;
   child:=public.assistant_workflow_command('control_claim',jsonb_build_object('task_id',tid,'expected_revision',rev,
    'event_id',eid,'capability_id',ctx->>'capability_id','mode','allowed'));
   IF child ? 'error' THEN RETURN child; END IF;
   previous:=a||jsonb_build_object('source_ref',p_input->'source_ref'); desired:=v->>'state';
  ELSIF p_operation IN ('original_publish','original_extract') THEN
   previous:=p_input->'attachment';
   IF previous->>'id' IS DISTINCT FROM a->>'id' OR previous->>'task_id' IS DISTINCT FROM a->>'task_id'
    OR previous->>'object_ref' IS DISTINCT FROM a->>'object_ref' OR previous->>'upload_id' IS DISTINCT FROM a->>'upload_id'
    OR previous->>'original_checksum' IS DISTINCT FROM a->>'original_checksum' OR previous->>'content_type' IS DISTINCT FROM a->>'content_type'
    OR previous->>'byte_size' IS DISTINCT FROM a->>'byte_size' OR previous->>'source_kind' IS DISTINCT FROM a->>'source_kind'
    OR previous->'source_ref' IS DISTINCT FROM a->'source_ref'
    OR previous->'operation_event_id' IS DISTINCT FROM a->'operation_event_id'
   THEN RETURN jsonb_build_object('error','invalid'); END IF;
   IF p_operation='original_publish' THEN previous:=previous||jsonb_build_object('state','saved','object_written',a->'object_written'); END IF;
   desired:=CASE WHEN previous->>'extraction_status'='failed' THEN 'failed_recoverable' ELSE 'collecting' END;
  ELSE RETURN jsonb_build_object('error','invalid'); END IF;
  previous:=previous||jsonb_build_object('object_written',a->'object_written','pending_writer_ids',a->'pending_writer_ids','multiple_writers',a->'multiple_writers');
  result:=v->'attachment_ids';
  IF NOT result @> jsonb_build_array(aid) THEN result:=result||jsonb_build_array(aid); END IF;
  child:=public.assistant_workflow_command('task_cas',jsonb_build_object('task_id',tid,'expected_revision',rev,
   'event_id',eid,'request_digest',(a->>'original_checksum')||':'||(a->>'source_kind'),
   'update',jsonb_build_object('state',desired,'save_mode','allowed','storage_state','saved','fields',v->'fields',
    'missing_fields',coalesce((SELECT jsonb_agg(x) FROM jsonb_array_elements(v->'missing_fields') x WHERE x<>'"source_image"'::jsonb),'[]'::jsonb),
    'attachment_ids',result,'business_refs',v->'business_refs')));
  IF child ? 'error' THEN RETURN child; END IF;
  UPDATE public.assistant_workflow_attachments SET data=previous WHERE owner=o AND id=aid AND task_id=tid;
  RETURN jsonb_build_object('result',previous||jsonb_build_object('owner',o));
 END IF;
 RETURN jsonb_build_object('error','invalid');
EXCEPTION
 WHEN unique_violation THEN RETURN jsonb_build_object('error','duplicate');
 WHEN check_violation OR not_null_violation OR invalid_text_representation OR foreign_key_violation
 THEN RETURN jsonb_build_object('error','invalid');
END $$;

REVOKE ALL ON FUNCTION public.assistant_wf_keys(jsonb,text[]) FROM PUBLIC,anon,service_role;
GRANT EXECUTE ON FUNCTION public.assistant_wf_keys(jsonb,text[]) TO authenticated;
REVOKE ALL ON FUNCTION public.assistant_wf_ref(jsonb) FROM PUBLIC,anon,service_role;
GRANT EXECUTE ON FUNCTION public.assistant_wf_ref(jsonb) TO authenticated;
REVOKE ALL ON FUNCTION public.assistant_wf_writer_ids(jsonb) FROM PUBLIC,anon,service_role;
GRANT EXECUTE ON FUNCTION public.assistant_wf_writer_ids(jsonb) TO authenticated;
REVOKE ALL ON FUNCTION public.assistant_workflow_command(text,jsonb) FROM PUBLIC,anon,service_role;
GRANT EXECUTE ON FUNCTION public.assistant_workflow_command(text,jsonb) TO authenticated;
COMMIT;
