-- REVIEW ONLY / NOT APPLIED. Requires reviewed035/036 and approved role provisioning.
-- Technical metadata only. No clinical or storage-schema mutations.
BEGIN;

-- Supabase manages auth schema grants: its postgres role lacks GRANT OPTION.
-- These invoker-only readers match auth.uid()/auth.role() JWT claim precedence.
-- They read the verified request context without acquiring managed-schema or
-- clinical privileges. No caller can set claims or choose an identity here.
CREATE FUNCTION public.assistant_patient_uid() RETURNS uuid
LANGUAGE sql STABLE SECURITY INVOKER SET search_path='' AS $$
 SELECT coalesce(nullif(pg_catalog.current_setting('request.jwt.claim.sub',true),''),
  nullif(pg_catalog.current_setting('request.jwt.claims',true),'')::jsonb->>'sub')::uuid
$$;
CREATE FUNCTION public.assistant_patient_role() RETURNS text
LANGUAGE sql STABLE SECURITY INVOKER SET search_path='' AS $$
 SELECT coalesce(nullif(pg_catalog.current_setting('request.jwt.claim.role',true),''),
  nullif(pg_catalog.current_setting('request.jwt.claims',true),'')::jsonb->>'role')
$$;
REVOKE ALL ON FUNCTION public.assistant_patient_uid(),public.assistant_patient_role()
 FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;
GRANT EXECUTE ON FUNCTION public.assistant_patient_uid(),public.assistant_patient_role()
 TO authenticated,assistant_workflow_owner,assistant_message_owner;

SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';
CREATE SCHEMA assistant_evidence AUTHORIZATION assistant_evidence_owner;
REVOKE ALL ON SCHEMA assistant_evidence FROM PUBLIC,anon,authenticated,service_role;
GRANT USAGE ON SCHEMA assistant_evidence TO assistant_evidence_login;
GRANT USAGE ON SCHEMA public TO assistant_evidence_owner,assistant_workflow_owner;
GRANT EXECUTE ON FUNCTION public.assistant_wf_keys(jsonb,text[]) TO assistant_evidence_owner,assistant_workflow_owner;
GRANT EXECUTE ON FUNCTION public.assistant_wf_ref(jsonb),public.assistant_wf_writer_ids(jsonb) TO assistant_workflow_owner;

CREATE TABLE public.assistant_storage_tickets (
 owner uuid NOT NULL REFERENCES public.patient_profiles(user_id), id uuid PRIMARY KEY,
 nonce uuid NOT NULL UNIQUE, task_id uuid NOT NULL, attachment_id uuid NOT NULL,
 writer_id uuid, operation text NOT NULL CHECK(operation IN ('upload','delete')),
 generation integer NOT NULL CHECK(generation>0), object_ref text NOT NULL,
 expected_checksum text NOT NULL CHECK(expected_checksum ~ '^[a-f0-9]{64}$'),
 content_type text NOT NULL CHECK(content_type IN ('image/png','image/jpeg','application/pdf')),
 byte_size integer NOT NULL CHECK(byte_size>0 AND byte_size<=10485760),
 expires_at timestamptz NOT NULL, state text NOT NULL DEFAULT 'issued'
 CHECK(state IN ('issued','inflight','unknown','settled')),
 revoked boolean NOT NULL DEFAULT false, deleting boolean NOT NULL DEFAULT false,
 CHECK((operation='upload')=(writer_id IS NOT NULL)),
 CHECK(content_type='application/pdf' OR byte_size<=8000000),
 CHECK(object_ref=owner::text||'/workflow-originals/'||task_id::text||'/'||attachment_id::text),
 UNIQUE(owner,id), UNIQUE(owner,attachment_id,generation,operation,writer_id)
);
ALTER TABLE public.assistant_storage_tickets OWNER TO assistant_evidence_owner;
ALTER TABLE public.assistant_storage_tickets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assistant_storage_tickets FORCE ROW LEVEL SECURITY;
CREATE POLICY assistant_storage_ticket_internal ON public.assistant_storage_tickets
 TO assistant_evidence_owner USING(true) WITH CHECK(true);
REVOKE ALL ON public.assistant_storage_tickets FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login;

CREATE TABLE public.assistant_verified_operations (
 id uuid PRIMARY KEY, owner uuid NOT NULL, ticket_id uuid NOT NULL, generation integer NOT NULL CHECK(generation>0),
 result text NOT NULL CHECK(result IN ('bytes_verified','absent_after_delete','definitely_not_started','outcome_unknown')),
 checksum text, byte_size integer, observed_at timestamptz NOT NULL, recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(owner,ticket_id) REFERENCES public.assistant_storage_tickets(owner,id),
 UNIQUE(ticket_id,generation,result),
 CHECK(CASE WHEN result='bytes_verified' THEN checksum IS NOT NULL AND checksum ~ '^[a-f0-9]{64}$'
 AND byte_size IS NOT NULL AND byte_size>0 AND byte_size<=10485760
 ELSE checksum IS NULL AND byte_size IS NULL END)
);
CREATE UNIQUE INDEX assistant_verified_terminal ON public.assistant_verified_operations(ticket_id,generation)
 WHERE result<>'outcome_unknown';
ALTER TABLE public.assistant_verified_operations OWNER TO assistant_evidence_owner;
ALTER TABLE public.assistant_verified_operations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assistant_verified_operations FORCE ROW LEVEL SECURITY;
CREATE POLICY assistant_verified_internal ON public.assistant_verified_operations
 TO assistant_evidence_owner USING(true) WITH CHECK(true);
REVOKE ALL ON public.assistant_verified_operations FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login;

CREATE TABLE public.assistant_business_receipts (
 owner uuid NOT NULL REFERENCES public.patient_profiles(user_id), action_key uuid NOT NULL,
 task_id uuid NOT NULL, capability_id text NOT NULL CHECK(capability_id ~ '^[a-z][a-z0-9_.]{1,119}$'),
 binding_revision integer NOT NULL CHECK(binding_revision>0), business_ref jsonb NOT NULL,
 domain_revision bigint NOT NULL CHECK(domain_revision>=0), outcome text NOT NULL CHECK(outcome IN ('prepared','applied')),
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(), PRIMARY KEY(owner,action_key),
 CHECK(public.assistant_wf_keys(business_ref,ARRAY['kind','id','version'])),
 CHECK((business_ref->>'id')::uuid IS NOT NULL AND (business_ref->>'kind') IS NOT NULL),
 CHECK(business_ref->>'kind'=ANY(ARRAY['medication','regimen','enrollment_task','source','dose_event',
 'dose_occurrence','late_report','care_review','media_review','reminder_review','reminder_action',
 'settings_review','settings_action','agent_session','conversation_cleanup','observation','stock','barrier',
 'care_task','contact','file','conversation','feedback','preference'])),
 CHECK(business_ref->>'version' IS NULL OR (business_ref->>'version')::integer>0)
);
ALTER TABLE public.assistant_business_receipts OWNER TO assistant_workflow_owner;
ALTER TABLE public.assistant_business_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assistant_business_receipts FORCE ROW LEVEL SECURITY;
CREATE POLICY assistant_business_receipt_internal ON public.assistant_business_receipts
 TO assistant_workflow_owner USING(true) WITH CHECK(true);
CREATE POLICY assistant_business_receipt_patient ON public.assistant_business_receipts
 FOR SELECT TO authenticated USING(owner=(SELECT public.assistant_patient_uid()));
REVOKE ALL ON public.assistant_business_receipts FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;
GRANT SELECT ON public.assistant_business_receipts TO authenticated;

CREATE TABLE public.assistant_runtime_runs (
 owner uuid NOT NULL REFERENCES public.patient_profiles(user_id), id uuid NOT NULL, task_id uuid,
 epoch integer NOT NULL DEFAULT 0 CHECK(epoch>=0), worker_ticket uuid NOT NULL UNIQUE, worker_nonce uuid NOT NULL,
 status text NOT NULL CHECK(status IN ('running','cancelling','completed','cancelled','failed')),
 started_at timestamptz NOT NULL DEFAULT clock_timestamp(), deadline_at timestamptz NOT NULL,
 reason text CHECK(reason IN ('cancelled','deadline_exceeded','budget_exceeded','execution_failed','worker_interrupted')),
 next_sequence integer NOT NULL DEFAULT 1 CHECK(next_sequence>0),
 metadata jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(metadata)='object' AND octet_length(metadata::text)<=4096
 AND public.assistant_wf_keys(metadata,ARRAY['provider','configured_model','returned_model','instruction_hash','schema_hash',
 'revision','runtime_hash','model_requests','tool_calls','sdk_attempts','sdk_retries','usage','usage_responses','duration_ms'])),
 PRIMARY KEY(owner,id), CHECK(deadline_at>started_at AND deadline_at<=started_at+interval '45 seconds')
);
ALTER TABLE public.assistant_runtime_runs OWNER TO assistant_evidence_owner;
ALTER TABLE public.assistant_runtime_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assistant_runtime_runs FORCE ROW LEVEL SECURITY;
CREATE POLICY assistant_runtime_internal ON public.assistant_runtime_runs
 TO assistant_evidence_owner USING(true) WITH CHECK(true);
REVOKE ALL ON public.assistant_runtime_runs FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login;

CREATE TABLE public.assistant_runtime_events (
 owner uuid NOT NULL, run_id uuid NOT NULL, event_id uuid NOT NULL, sequence integer NOT NULL CHECK(sequence>0),
 epoch integer NOT NULL CHECK(epoch>=0), data jsonb NOT NULL,
 PRIMARY KEY(owner,run_id,event_id), UNIQUE(owner,run_id,sequence),
 FOREIGN KEY(owner,run_id) REFERENCES public.assistant_runtime_runs(owner,id),
 CHECK(jsonb_typeof(data)='object' AND octet_length(data::text)<=2048 AND public.assistant_wf_keys(data,
 ARRAY['sequence','run_id','task_id','action_key','kind','status','reason_key','duration_ms']))
);
ALTER TABLE public.assistant_runtime_events OWNER TO assistant_evidence_owner;
ALTER TABLE public.assistant_runtime_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assistant_runtime_events FORCE ROW LEVEL SECURITY;
CREATE POLICY assistant_runtime_event_internal ON public.assistant_runtime_events
 TO assistant_evidence_owner USING(true) WITH CHECK(true);
REVOKE ALL ON public.assistant_runtime_events FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login;

CREATE FUNCTION assistant_evidence.record_storage_observation(p_observation jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE t public.assistant_storage_tickets%ROWTYPE; v public.assistant_verified_operations%ROWTYPE;
 o uuid; ticket uuid; result_kind text; seen_checksum text; seen_size integer; at_time timestamptz;
BEGIN
 IF session_user<>'assistant_evidence_login' THEN
  RAISE EXCEPTION 'Restricted verification identity required' USING ERRCODE='42501';
 END IF;
 IF p_observation IS NULL OR NOT public.assistant_wf_keys(p_observation,
 ARRAY['ticket_id','nonce','generation','result','checksum','byte_size','observed_at'])
 OR NOT (p_observation ?& ARRAY['ticket_id','nonce','generation','result','observed_at'])
 OR jsonb_typeof(p_observation->'generation') IS DISTINCT FROM 'number'
 OR (p_observation->>'generation') !~ '^[1-9][0-9]*$'
 THEN RAISE EXCEPTION 'Invalid verification observation' USING ERRCODE='22023'; END IF;
 ticket:=(p_observation->>'ticket_id')::uuid;
 SELECT owner INTO o FROM public.assistant_storage_tickets WHERE id=ticket;
 IF o IS NULL THEN RAISE EXCEPTION 'Verification operation unavailable' USING ERRCODE='P0002'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 SELECT * INTO t FROM public.assistant_storage_tickets WHERE id=ticket AND owner=o FOR UPDATE;
 IF t.nonce IS DISTINCT FROM (p_observation->>'nonce')::uuid
 OR t.generation IS DISTINCT FROM (p_observation->>'generation')::integer
 OR t.state='issued' THEN
  RAISE EXCEPTION 'Verification binding changed' USING ERRCODE='40001';
 END IF;
 result_kind:=p_observation->>'result'; seen_checksum:=p_observation->>'checksum';
 seen_size:=(p_observation->>'byte_size')::integer; at_time:=(p_observation->>'observed_at')::timestamptz;
 IF result_kind IS NULL OR result_kind NOT IN ('bytes_verified','absent_after_delete','definitely_not_started','outcome_unknown')
 OR at_time IS NULL OR (p_observation->>'observed_at') !~ '(Z|[+-][0-9]{2}:[0-9]{2})$'
 OR (result_kind='bytes_verified' AND (t.operation<>'upload' OR seen_checksum IS DISTINCT FROM t.expected_checksum
 OR seen_size IS DISTINCT FROM t.byte_size OR jsonb_typeof(p_observation->'byte_size') IS DISTINCT FROM 'number'))
 OR (result_kind<>'bytes_verified' AND (seen_checksum IS NOT NULL OR seen_size IS NOT NULL))
 OR (result_kind='absent_after_delete' AND (t.operation<>'delete' OR NOT t.deleting))
 THEN RAISE EXCEPTION 'Verification result does not match operation' USING ERRCODE='22023'; END IF;
 SELECT * INTO v FROM public.assistant_verified_operations WHERE ticket_id=t.id AND generation=t.generation
 AND result<>'outcome_unknown';
 IF FOUND THEN
  IF result_kind<>v.result AND result_kind<>'outcome_unknown' THEN
   RAISE EXCEPTION 'Conflicting terminal verification' USING ERRCODE='40001';
  END IF;
 ELSE
  INSERT INTO public.assistant_verified_operations(id,owner,ticket_id,generation,result,checksum,byte_size,observed_at)
  VALUES(gen_random_uuid(),o,t.id,t.generation,result_kind,seen_checksum,seen_size,at_time)
  ON CONFLICT(ticket_id,generation,result) DO NOTHING;
  SELECT * INTO v FROM public.assistant_verified_operations WHERE ticket_id=t.id AND generation=t.generation AND result=result_kind;
  UPDATE public.assistant_storage_tickets SET state=CASE WHEN result_kind='outcome_unknown' THEN 'unknown' ELSE 'settled' END
  WHERE id=t.id AND owner=o;
 END IF;
 RETURN jsonb_build_object('ticket_id',t.id,'verification_id',v.id,'generation',v.generation,'result',v.result);
END $$;
ALTER FUNCTION assistant_evidence.record_storage_observation(jsonb) OWNER TO assistant_evidence_owner;
REVOKE ALL ON FUNCTION assistant_evidence.record_storage_observation(jsonb) FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION assistant_evidence.record_storage_observation(jsonb) TO assistant_evidence_login;

-- Align the legacy JSON boundary with the typed preparation/result references.
-- Existing control/event/cleanup branches and owner RLS remain unchanged.
CREATE OR REPLACE FUNCTION public.assistant_wf_ref(v jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SECURITY INVOKER SET search_path='' AS $$
 SELECT v IS NULL OR v='null'::jsonb OR coalesce(public.assistant_wf_keys(v,ARRAY['kind','id','version'])
 AND v->>'kind'=ANY(ARRAY['medication','regimen','source','dose_event','dose_occurrence','late_report','enrollment_task','care_review','media_review',
 'reminder_review','reminder_action','settings_review','settings_action','agent_session','conversation_cleanup','observation','stock','barrier',
 'care_task','contact','file','conversation','feedback','preference']) AND (v->>'id')::uuid IS NOT NULL
 AND (v->>'version' IS NULL OR (v->>'version')::int>0),false)
$$;
ALTER TABLE public.assistant_workflow_operations
 DROP CONSTRAINT assistant_workflow_operations_check,
 ADD CONSTRAINT assistant_workflow_operations_check CHECK(coalesce(CASE record_type
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
 WHEN 'action' THEN (NOT(data ? 'owner') OR data->>'owner'=owner::text)
 AND (NOT(data ? 'clinical_revision') OR data->'clinical_revision'='null'::jsonb
 OR (jsonb_typeof(data->'clinical_revision')='number' AND data->>'clinical_revision' ~ '^[0-9]+$')) AND public.assistant_wf_keys(data,ARRAY['action_key','task_id','capability_id','binding_revision',
 'state','business_ref','safe_reason','updated_at','owner','clinical_revision']) AND data->>'action_key'=id::text
 AND data->>'task_id'=task_id::text AND (data->>'binding_revision')::int>0
 AND data->>'state'=ANY(ARRAY['pending','succeeded','failed','outcome_unknown'])
 AND data->>'capability_id' ~ '^[a-z][a-z0-9_.]{1,119}$' AND public.assistant_wf_ref(data->'business_ref')
 AND (data->>'safe_reason' IS NULL OR data->>'safe_reason' ~ '^[a-z_]{1,80}$'
 OR (data->>'capability_id' IN ('notification.subscribe','notification.unsubscribe')
 AND data->>'safe_reason' ~ '^[a-f0-9]{64}$'))
 WHEN 'cleanup' THEN public.assistant_wf_keys(data,ARRAY['id','task_id','object_ref','content_type','source_ref',
 'state','writer_pending','reason','pending_writer_ids','multiple_writers']) AND data->>'id'=id::text AND data->>'task_id'=task_id::text
 AND data->>'object_ref'=owner::text||'/workflow-originals/'||task_id::text||'/'||id::text
 AND data->>'state'=ANY(ARRAY['pending','deleted','protected','failed'])
 AND data->>'content_type'=ANY(ARRAY['image/png','image/jpeg']) AND jsonb_typeof(data->'writer_pending')='boolean'
 AND public.assistant_wf_ref(data->'source_ref')
 AND public.assistant_wf_writer_ids(data->'pending_writer_ids') AND jsonb_typeof(data->'multiple_writers')='boolean'
 AND (data->>'reason' IS NULL OR data->>'reason'=ANY(ARRAY['upload_inflight','storage_unavailable',
 'protection_unavailable','formal_source','reference_unresolved','shared_reference','operation_unknown','business_record','removed']))
 ELSE false END,false));

GRANT EXECUTE ON FUNCTION public.assistant_patient_uid(),public.assistant_patient_role() TO assistant_workflow_owner;
GRANT EXECUTE ON FUNCTION public.assistant_workflow_command(text,jsonb) TO assistant_workflow_owner;
GRANT SELECT,UPDATE ON public.assistant_workflow_tasks,public.assistant_workflow_operations TO assistant_workflow_owner;
-- Typed native preparation records an action before publishing its receipt.
-- Keep INSERT limited to the workflow owner; its existing owner policy applies.
GRANT INSERT ON public.assistant_workflow_operations TO assistant_workflow_owner;
CREATE POLICY assistant_workflow_task_command ON public.assistant_workflow_tasks TO assistant_workflow_owner
 USING(owner=public.assistant_patient_uid()) WITH CHECK(owner=public.assistant_patient_uid());
CREATE POLICY assistant_workflow_operation_command ON public.assistant_workflow_operations TO assistant_workflow_owner
 USING(owner=public.assistant_patient_uid()) WITH CHECK(owner=public.assistant_patient_uid());

-- Closed structural/control commands only; native domain transactions own completion.
CREATE FUNCTION public.assistant_workflow_mutate(p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=public.assistant_patient_uid(); kind text; tid uuid; target uuid; args jsonb; child jsonb;
 source_data jsonb; target_data jsonb; change jsonb; allowed text[];
BEGIN
 IF o IS NULL OR public.assistant_patient_role() IS DISTINCT FROM 'authenticated' THEN
  RAISE EXCEPTION 'Verified patient identity required' USING ERRCODE='42501';
 END IF;
 kind:=p_command->>'kind';
 allowed:=CASE kind
 WHEN 'start' THEN ARRAY['kind','task','event_id','request_digest','run_binding']
 WHEN 'start_ephemeral' THEN ARRAY['kind','control','run_binding']
 WHEN 'advance' THEN ARRAY['kind','task_id','expected_revision','event_id','update','request_digest','run_binding']
 WHEN 'bind_conversation' THEN ARRAY['kind','task_id','expected_revision','conversation_id','run_binding']
 WHEN 'switch_mode' THEN ARRAY['kind','task_id','expected_revision','event_id','mode','run_binding']
 WHEN 'revoke' THEN ARRAY['kind','task_id','expected_revision','event_id','run_binding']
 WHEN 'resume_handoff' THEN ARRAY['kind','task_id','expected_revision','target_task_id','target_revision','event_id','target_state','run_binding']
 ELSE NULL END;
 IF allowed IS NULL OR NOT public.assistant_wf_keys(p_command,allowed) THEN
  RAISE EXCEPTION 'Invalid mutation command' USING ERRCODE='22023';
 END IF;
 tid:=(CASE WHEN kind='start' THEN p_command->'task'->>'id'
 WHEN kind='start_ephemeral' THEN p_command->'control'->>'task_id' ELSE p_command->>'task_id' END)::uuid;
 IF tid IS NULL THEN RAISE EXCEPTION 'Missing task binding' USING ERRCODE='22023'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 -- Take structural locks before the optional run fence. Legacy035 repeats the
 -- same owner fence; no database transaction spans Storage/provider HTTP.
 target:=(p_command->>'target_task_id')::uuid;
 PERFORM 1 FROM public.assistant_workflow_tasks WHERE owner=o AND id IN (tid,target) ORDER BY id FOR UPDATE;
 PERFORM 1 FROM public.assistant_workflow_operations
 WHERE owner=o AND record_type='control' AND task_id IN (tid,target) ORDER BY task_id,id FOR UPDATE;
 IF p_command->'run_binding' IS NOT NULL AND p_command->'run_binding'<>'null'::jsonb THEN
  -- Installed by the separate run candidate. Until then run-bound commands fail
  -- closed; absence of this function must never trigger a non-atomic fallback.
  PERFORM public.assistant_run_assert_current(o,p_command->'run_binding');
 END IF;
 IF kind='start' THEN
  IF p_command->'task'->>'save_mode' IS DISTINCT FROM 'allowed' THEN
   RAISE EXCEPTION 'Saved task required' USING ERRCODE='22023'; END IF;
  args:=jsonb_build_object('task_id',tid,'task',p_command->'task','suspend_foreground',true,
   'event_id',p_command->'event_id','request_digest',p_command->'request_digest');
  child:=public.assistant_workflow_command('task_create',args);
 ELSIF kind='start_ephemeral' THEN
  IF p_command->'control'->>'mode' IS DISTINCT FROM 'ephemeral' THEN
   RAISE EXCEPTION 'Content-free control required' USING ERRCODE='22023'; END IF;
  child:=public.assistant_workflow_command('control_create',jsonb_build_object(
   'task_id',tid,'receipt',p_command->'control','suspend_foreground',true));
 ELSIF kind='advance' THEN
  IF p_command->'update'->>'save_mode' IS DISTINCT FROM 'allowed'
  OR p_command->'update'->>'state'='completed' THEN
   RAISE EXCEPTION 'A coupled result is required for completion' USING ERRCODE='22023'; END IF;
  child:=public.assistant_workflow_command('task_cas',jsonb_build_object('task_id',tid,
   'expected_revision',p_command->'expected_revision','event_id',p_command->'event_id',
   'request_digest',p_command->'request_digest','update',p_command->'update'));
 ELSIF kind='bind_conversation' THEN
  child:=public.assistant_workflow_command('task_bind',jsonb_build_object('task_id',tid,
   'expected_revision',p_command->'expected_revision','conversation_id',p_command->'conversation_id'));
 ELSIF kind IN ('switch_mode','revoke') THEN
  child:=public.assistant_workflow_command(CASE WHEN kind='revoke' THEN 'control_revoke' ELSE 'control_mode' END,
   jsonb_build_object('task_id',tid,'expected_revision',p_command->'expected_revision',
   'event_id',p_command->'event_id','mode',p_command->'mode'));
 ELSE
  IF target IS NULL OR target=tid OR p_command->>'target_state' IS NULL
  OR p_command->>'target_state' NOT IN ('choose_method','collecting','validating','ready_for_review',
  'awaiting_confirmation','failed_recoverable','outcome_unknown') THEN
   RAISE EXCEPTION 'Invalid recovery target' USING ERRCODE='22023'; END IF;
  SELECT data INTO source_data FROM public.assistant_workflow_tasks WHERE owner=o AND id=tid;
  SELECT data INTO target_data FROM public.assistant_workflow_tasks WHERE owner=o AND id=target;
  IF source_data IS NULL OR target_data IS NULL
  OR (source_data->>'revision')::integer IS DISTINCT FROM (p_command->>'expected_revision')::integer
  OR (target_data->>'revision')::integer IS DISTINCT FROM (p_command->>'target_revision')::integer
  OR source_data->>'state' IN ('completed','cancelled','suspended')
  OR target_data->>'state' IN ('completed','cancelled') THEN
   RAISE EXCEPTION 'Recovery binding changed' USING ERRCODE='40001'; END IF;
  change:=jsonb_build_object('state','suspended','save_mode','allowed','storage_state',source_data->'storage_state',
   'fields',source_data->'fields','missing_fields',source_data->'missing_fields','attachment_ids',source_data->'attachment_ids',
   'business_refs',source_data->'business_refs');
  child:=public.assistant_workflow_command('task_cas',jsonb_build_object('task_id',tid,
   'expected_revision',p_command->'expected_revision','event_id',p_command->'event_id','update',change));
  IF child ? 'error' THEN RAISE EXCEPTION 'Recovery source changed' USING ERRCODE='40001'; END IF;
  change:=jsonb_build_object('state',p_command->>'target_state','save_mode','allowed','storage_state',target_data->'storage_state',
   'fields',target_data->'fields','missing_fields',target_data->'missing_fields','attachment_ids',target_data->'attachment_ids',
   'business_refs',target_data->'business_refs');
  child:=public.assistant_workflow_command('task_cas',jsonb_build_object('task_id',target,
   'expected_revision',p_command->'target_revision','event_id',p_command->'event_id','update',change));
 END IF;
 -- Raising rolls back the complete PL/pgSQL block, including the first half of
 -- a handoff. Returning a child error after the first write would not be atomic.
 IF child ? 'error' THEN RAISE EXCEPTION 'Workflow mutation changed' USING ERRCODE='40001'; END IF;
 RETURN child;
EXCEPTION
 WHEN SQLSTATE '40001' THEN RETURN jsonb_build_object('error','stale');
 WHEN invalid_parameter_value OR invalid_text_representation OR check_violation THEN
  RETURN jsonb_build_object('error','invalid');
END $$;
ALTER FUNCTION public.assistant_workflow_mutate(jsonb) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_workflow_mutate(jsonb) FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;
GRANT EXECUTE ON FUNCTION public.assistant_workflow_mutate(jsonb) TO authenticated;
COMMIT;
