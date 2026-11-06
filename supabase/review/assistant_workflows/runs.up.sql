-- REVIEW ONLY / NOT APPLIED. UTC technical controls, no business or provider execution.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';
ALTER TABLE public.assistant_runtime_runs
 ADD COLUMN operations jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(operations)='object' AND octet_length(operations::text)<=32768),
 ADD COLUMN active_spans jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(active_spans)='object' AND octet_length(active_spans::text)<=8192),
 ADD COLUMN attempts jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(attempts)='object' AND octet_length(attempts::text)<=8192),
 ADD COLUMN responses jsonb NOT NULL DEFAULT '[]' CHECK(jsonb_typeof(responses)='array' AND jsonb_array_length(responses)<=128);
GRANT USAGE ON SCHEMA assistant_evidence TO assistant_workflow_owner;
GRANT SELECT,INSERT,UPDATE ON public.assistant_runtime_runs TO assistant_workflow_owner;
GRANT SELECT,INSERT ON public.assistant_runtime_events TO assistant_workflow_owner;
CREATE POLICY assistant_runtime_patient_command ON public.assistant_runtime_runs TO assistant_workflow_owner
 USING(owner=public.assistant_patient_uid()) WITH CHECK(owner=public.assistant_patient_uid());
CREATE POLICY assistant_runtime_event_patient_command ON public.assistant_runtime_events TO assistant_workflow_owner
 USING(owner=public.assistant_patient_uid()) WITH CHECK(owner=public.assistant_patient_uid());

CREATE FUNCTION assistant_evidence.run_projection(p_owner uuid,p_run uuid,p_acquired boolean DEFAULT false) RETURNS jsonb
LANGUAGE sql SECURITY INVOKER SET search_path='' AS $$
 SELECT jsonb_build_object('owner',r.owner,'run_id',r.id,'task_id',r.task_id,'epoch',r.epoch,
 'worker_ticket',r.worker_ticket,'worker_nonce',r.worker_nonce,'started_at',r.started_at,'deadline_at',r.deadline_at,
 'server_now',clock_timestamp(),'status',r.status,'claim_acquired',p_acquired,'snapshot',jsonb_build_object(
 'status',r.status,'metadata',r.metadata||jsonb_build_object('run_id',r.id),'events',coalesce((
 SELECT jsonb_agg(e.data ORDER BY e.sequence) FROM public.assistant_runtime_events e
 WHERE e.owner=p_owner AND e.run_id=p_run),'[]'::jsonb)))
 FROM public.assistant_runtime_runs r WHERE r.owner=p_owner AND r.id=p_run
$$;
ALTER FUNCTION assistant_evidence.run_projection(uuid,uuid,boolean) OWNER TO assistant_evidence_owner;
REVOKE ALL ON FUNCTION assistant_evidence.run_projection(uuid,uuid,boolean) FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login;
GRANT EXECUTE ON FUNCTION assistant_evidence.run_projection(uuid,uuid,boolean) TO assistant_workflow_owner;

CREATE FUNCTION assistant_evidence.append_run_event(p_owner uuid,p_run uuid,p_event uuid,p_kind text,
 p_step text DEFAULT NULL,p_reason text DEFAULT NULL,p_duration numeric DEFAULT NULL) RETURNS void
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE r public.assistant_runtime_runs%ROWTYPE;
BEGIN
 SELECT * INTO STRICT r FROM public.assistant_runtime_runs WHERE owner=p_owner AND id=p_run FOR UPDATE;
 INSERT INTO public.assistant_runtime_events(owner,run_id,event_id,sequence,epoch,data)
 VALUES(p_owner,p_run,p_event,r.next_sequence,r.epoch,jsonb_build_object('sequence',r.next_sequence,'run_id',r.id,
 'task_id',r.task_id,'action_key',p_step,'kind',p_kind,'status',r.status,'reason_key',p_reason,'duration_ms',p_duration));
 UPDATE public.assistant_runtime_runs SET next_sequence=next_sequence+1 WHERE owner=p_owner AND id=p_run;
END $$;
ALTER FUNCTION assistant_evidence.append_run_event(uuid,uuid,uuid,text,text,text,numeric) OWNER TO assistant_evidence_owner;
REVOKE ALL ON FUNCTION assistant_evidence.append_run_event(uuid,uuid,uuid,text,text,text,numeric) FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login;
GRANT EXECUTE ON FUNCTION assistant_evidence.append_run_event(uuid,uuid,uuid,text,text,text,numeric) TO assistant_workflow_owner;

CREATE FUNCTION public.assistant_run_assert_current(p_owner uuid,p_binding jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE r public.assistant_runtime_runs%ROWTYPE;
BEGIN
 IF public.assistant_patient_uid() IS DISTINCT FROM p_owner OR p_owner IS NULL OR p_binding IS NULL
 OR NOT public.assistant_wf_keys(p_binding,ARRAY['run_id','epoch'])
 OR jsonb_typeof(p_binding->'epoch') IS DISTINCT FROM 'number' THEN
  RAISE EXCEPTION 'Invalid run write binding' USING ERRCODE='40001'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(p_owner::text,35035));
 SELECT * INTO r FROM public.assistant_runtime_runs WHERE owner=p_owner AND id=(p_binding->>'run_id')::uuid FOR UPDATE;
 IF NOT FOUND OR r.status<>'running' OR r.epoch=0 OR r.epoch IS DISTINCT FROM (p_binding->>'epoch')::integer
 OR clock_timestamp()>=r.deadline_at THEN
  RAISE EXCEPTION 'Run stopped, expired or changed' USING ERRCODE='40001'; END IF;
END $$;
ALTER FUNCTION public.assistant_run_assert_current(uuid,jsonb) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_run_assert_current(uuid,jsonb) FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;
GRANT EXECUTE ON FUNCTION public.assistant_run_assert_current(uuid,jsonb) TO assistant_message_owner;

CREATE FUNCTION public.assistant_run_control(p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=public.assistant_patient_uid(); rid uuid; kind text; r public.assistant_runtime_runs%ROWTYPE; at_time timestamptz;
BEGIN
 IF o IS NULL OR public.assistant_patient_role() IS DISTINCT FROM 'authenticated' THEN
  RAISE EXCEPTION 'Verified patient required' USING ERRCODE='42501'; END IF;
 kind:=p_command->>'kind';
 IF kind IS NULL OR kind NOT IN ('start','read','cancel') OR NOT public.assistant_wf_keys(p_command,
 CASE WHEN kind='start' THEN ARRAY['kind','run_id','task_id'] ELSE ARRAY['kind','run_id'] END) THEN
  RAISE EXCEPTION 'Invalid run control command' USING ERRCODE='22023'; END IF;
 rid:=(p_command->>'run_id')::uuid;
 IF rid IS NULL THEN RAISE EXCEPTION 'Run id required' USING ERRCODE='22023'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 SELECT * INTO r FROM public.assistant_runtime_runs WHERE owner=o AND id=rid FOR UPDATE;
 IF kind='start' THEN
  IF FOUND THEN RETURN jsonb_build_object('error','duplicate'); END IF;
  IF p_command->>'task_id' IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.assistant_workflow_operations
   WHERE owner=o AND record_type='control' AND task_id=(p_command->>'task_id')::uuid) THEN
   RETURN jsonb_build_object('error','not_found'); END IF;
  at_time:=clock_timestamp();
  INSERT INTO public.assistant_runtime_runs(owner,id,task_id,worker_ticket,worker_nonce,status,started_at,deadline_at,metadata)
  VALUES(o,rid,(p_command->>'task_id')::uuid,gen_random_uuid(),gen_random_uuid(),'running',at_time,at_time+interval '45 seconds',
   jsonb_build_object('model_requests',0,'tool_calls',0,'usage_responses',0,'duration_ms',0));
  PERFORM assistant_evidence.append_run_event(o,rid,gen_random_uuid(),'run_started');
 ELSE
  IF NOT FOUND THEN RETURN jsonb_build_object('error','not_found'); END IF;
  IF kind='cancel' AND r.status='running' THEN
   UPDATE public.assistant_runtime_runs SET status='cancelling' WHERE owner=o AND id=rid;
   PERFORM assistant_evidence.append_run_event(o,rid,gen_random_uuid(),'run_cancelling',NULL,'cancelled');
  END IF;
 END IF;
 RETURN jsonb_build_object('result',assistant_evidence.run_projection(o,rid));
EXCEPTION WHEN invalid_parameter_value OR invalid_text_representation OR check_violation THEN
 RETURN jsonb_build_object('error','invalid');
END $$;
ALTER FUNCTION public.assistant_run_control(jsonb) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_run_control(jsonb) FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;
GRANT EXECUTE ON FUNCTION public.assistant_run_control(jsonb) TO authenticated;

CREATE FUNCTION assistant_evidence.record_run_observation(p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE r public.assistant_runtime_runs%ROWTYPE; o uuid; rid uuid; kind text; allowed text[];
 event_key text; fingerprint text; previous text; obs jsonb; phase text; span text; attempt text;
 counter text; count_before integer; new_metadata jsonb; retry boolean; usage jsonb; old_usage jsonb;
 combined jsonb; field_name text; step_kind text; next_status text; terminal_reason text; duration numeric; at_time timestamptz;
BEGIN
 IF session_user<>'assistant_evidence_login' THEN
  RAISE EXCEPTION 'Restricted verifier required' USING ERRCODE='42501'; END IF;
 kind:=p_command->>'kind';
 allowed:=CASE kind
 WHEN 'claim' THEN ARRAY['kind','ticket_id','nonce','epoch','event_id','revision','runtime_hash']
 WHEN 'start_step' THEN ARRAY['kind','ticket_id','nonce','epoch','event_id','span_id','step_kind']
 WHEN 'finish_step' THEN ARRAY['kind','ticket_id','nonce','epoch','event_id','span_id','succeeded','duration_ms']
 WHEN 'record_usage' THEN ARRAY['kind','ticket_id','nonce','epoch','event_id','observation']
 WHEN 'finish' THEN ARRAY['kind','ticket_id','nonce','epoch','event_id','status','reason','duration_ms']
 WHEN 'recover_interrupted' THEN ARRAY['kind','ticket_id','nonce','epoch','event_id'] ELSE NULL END;
 IF allowed IS NULL OR NOT public.assistant_wf_keys(p_command,allowed)
 OR NOT (p_command ?& ARRAY['ticket_id','nonce','epoch','event_id'])
 OR jsonb_typeof(p_command->'epoch') IS DISTINCT FROM 'number' THEN
  RAISE EXCEPTION 'Invalid worker observation' USING ERRCODE='22023'; END IF;
 SELECT owner,id INTO o,rid FROM public.assistant_runtime_runs WHERE worker_ticket=(p_command->>'ticket_id')::uuid;
 IF o IS NULL THEN RETURN jsonb_build_object('error','not_found'); END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 SELECT * INTO r FROM public.assistant_runtime_runs WHERE owner=o AND id=rid FOR UPDATE;
 IF r.worker_nonce IS DISTINCT FROM (p_command->>'nonce')::uuid THEN RETURN jsonb_build_object('error','not_found'); END IF;
 event_key:=((p_command->>'event_id')::uuid)::text;
 fingerprint:=encode(sha256(convert_to((p_command-'nonce')::text,'UTF8')),'hex');
 previous:=r.operations->>event_key;
 IF previous IS NOT NULL THEN
  IF previous<>fingerprint THEN RETURN jsonb_build_object('error','duplicate'); END IF;
  RETURN assistant_evidence.run_projection(o,rid);
 END IF;
 at_time:=clock_timestamp();
 IF kind='claim' THEN
  IF r.epoch<>0 THEN RETURN jsonb_build_object('error','duplicate'); END IF;
  IF (p_command->>'epoch')::integer<>0 OR r.status<>'running' THEN RETURN jsonb_build_object('error','stale'); END IF;
  IF at_time>=r.deadline_at THEN RETURN jsonb_build_object('error','deadline'); END IF;
  IF (p_command->>'revision' IS NOT NULL AND (p_command->>'revision') !~ '^[a-f0-9]{40}$')
  OR (p_command->>'runtime_hash' IS NOT NULL AND (p_command->>'runtime_hash') !~ '^[a-f0-9]{64}$') THEN
   RAISE EXCEPTION 'Invalid runtime provenance' USING ERRCODE='22023'; END IF;
  UPDATE public.assistant_runtime_runs SET epoch=1,metadata=metadata||jsonb_build_object(
   'revision',p_command->'revision','runtime_hash',p_command->'runtime_hash'),
   operations=operations||jsonb_build_object(event_key,fingerprint) WHERE owner=o AND id=rid;
  RETURN assistant_evidence.run_projection(o,rid,true);
 END IF;
 IF r.epoch IS DISTINCT FROM (p_command->>'epoch')::integer OR (r.epoch=0 AND kind<>'recover_interrupted') THEN
  RETURN jsonb_build_object('error','stale'); END IF;
 obs:=p_command->'observation'; phase:=obs->>'phase';
 IF kind='start_step' OR (kind='record_usage' AND phase IN ('metadata','attempt')) THEN
  IF r.status IN ('cancelling','cancelled') THEN RETURN jsonb_build_object('error','cancelled'); END IF;
  IF r.status<>'running' THEN RETURN jsonb_build_object('error','stale'); END IF;
  IF at_time>=r.deadline_at THEN RETURN jsonb_build_object('error','deadline'); END IF;
 END IF;
 new_metadata:=r.metadata;
 IF kind='start_step' THEN
  span:=((p_command->>'span_id')::uuid)::text; step_kind:=p_command->>'step_kind';
  IF step_kind IS NULL OR step_kind NOT IN ('application','model','tool') OR r.active_spans ? span THEN
   RAISE EXCEPTION 'Invalid or duplicate step' USING ERRCODE='22023'; END IF;
  IF step_kind IN ('model','tool') THEN
   counter:=CASE WHEN step_kind='model' THEN 'model_requests' ELSE 'tool_calls' END;
   count_before:=coalesce((r.metadata->>counter)::integer,0);
   IF count_before>=4 THEN RETURN jsonb_build_object('error','budget'); END IF;
   new_metadata:=jsonb_set(new_metadata,ARRAY[counter],to_jsonb(count_before+1));
  END IF;
  UPDATE public.assistant_runtime_runs SET metadata=new_metadata,active_spans=active_spans||jsonb_build_object(span,step_kind)
   WHERE owner=o AND id=rid;
  PERFORM assistant_evidence.append_run_event(o,rid,(p_command->>'event_id')::uuid,'step_started',step_kind);
 ELSIF kind='finish_step' THEN
  span:=((p_command->>'span_id')::uuid)::text; step_kind:=r.active_spans->>span;
  duration:=(p_command->>'duration_ms')::numeric;
  IF step_kind IS NULL OR duration IS NULL OR duration<0 OR jsonb_typeof(p_command->'succeeded') IS DISTINCT FROM 'boolean' THEN
   RAISE EXCEPTION 'Owned active step and finite duration required' USING ERRCODE='22023'; END IF;
  UPDATE public.assistant_runtime_runs SET active_spans=active_spans-span WHERE owner=o AND id=rid;
  PERFORM assistant_evidence.append_run_event(o,rid,(p_command->>'event_id')::uuid,
   CASE WHEN (p_command->>'succeeded')::boolean THEN 'step_completed' ELSE 'step_failed' END,step_kind,NULL,duration);
 ELSIF kind='record_usage' THEN
  IF phase='metadata' THEN
   IF NOT public.assistant_wf_keys(obs,ARRAY['phase','configured_model','instruction_hash','schema_hash'])
   OR (obs->>'instruction_hash') IS NULL OR (obs->>'instruction_hash') !~ '^[a-f0-9]{64}$'
   OR (obs->>'schema_hash') IS NULL OR (obs->>'schema_hash') !~ '^[a-f0-9]{64}$'
   OR (obs->>'configured_model' IS NOT NULL AND (length(obs->>'configured_model')>100
   OR (obs->>'configured_model') !~ '^[a-zA-Z0-9._/-]+$')) THEN
    RAISE EXCEPTION 'Invalid provider provenance' USING ERRCODE='22023'; END IF;
   new_metadata:=new_metadata||jsonb_build_object('configured_model',obs->'configured_model',
    'instruction_hash',obs->'instruction_hash','schema_hash',obs->'schema_hash');
  ELSIF phase='attempt' THEN
   IF NOT public.assistant_wf_keys(obs,ARRAY['phase','span_id','attempt_id']) THEN
    RAISE EXCEPTION 'Invalid SDK attempt fields' USING ERRCODE='22023'; END IF;
   span:=((obs->>'span_id')::uuid)::text; attempt:=((obs->>'attempt_id')::uuid)::text;
   IF r.active_spans->>span IS DISTINCT FROM 'model' THEN RETURN jsonb_build_object('error','stale'); END IF;
   IF r.attempts ? attempt THEN RETURN jsonb_build_object('error','duplicate'); END IF;
   SELECT EXISTS(SELECT 1 FROM jsonb_each_text(r.attempts) e WHERE e.value=span) INTO retry;
   new_metadata:=new_metadata||jsonb_build_object('provider','gemini',
    'sdk_attempts',coalesce((new_metadata->>'sdk_attempts')::integer,0)+1,
    'sdk_retries',coalesce((new_metadata->>'sdk_retries')::integer,0)+CASE WHEN retry THEN 1 ELSE 0 END);
   UPDATE public.assistant_runtime_runs SET attempts=attempts||jsonb_build_object(attempt,span) WHERE owner=o AND id=rid;
  ELSIF phase='response' THEN
   IF NOT public.assistant_wf_keys(obs,ARRAY['phase','attempt_id','returned_model','usage']) THEN
    RAISE EXCEPTION 'Invalid SDK response fields' USING ERRCODE='22023'; END IF;
   attempt:=((obs->>'attempt_id')::uuid)::text;
   IF NOT (r.attempts ? attempt) THEN RETURN jsonb_build_object('error','stale'); END IF;
   IF r.responses ? attempt THEN RETURN jsonb_build_object('error','duplicate'); END IF;
   IF obs->>'returned_model' IS NOT NULL AND (length(obs->>'returned_model')>100
   OR (obs->>'returned_model') !~ '^[a-zA-Z0-9._/-]+$') THEN
    RAISE EXCEPTION 'Invalid returned model id' USING ERRCODE='22023'; END IF;
   new_metadata:=new_metadata||jsonb_build_object('returned_model',obs->'returned_model');
   usage:=obs->'usage'; old_usage:=new_metadata->'usage';
   IF usage IS NOT NULL AND usage<>'null'::jsonb THEN
    IF NOT public.assistant_wf_keys(usage,ARRAY['input_tokens','output_tokens','total_tokens','cached_input_tokens']) THEN
     RAISE EXCEPTION 'Invalid usage fields' USING ERRCODE='22023'; END IF;
    combined:='{}'::jsonb;
    FOREACH field_name IN ARRAY ARRAY['input_tokens','output_tokens','total_tokens','cached_input_tokens'] LOOP
     IF usage->>field_name IS NOT NULL AND (jsonb_typeof(usage->field_name) IS DISTINCT FROM 'number'
     OR (usage->>field_name) !~ '^[0-9]+$') THEN
      RAISE EXCEPTION 'Invalid usage count' USING ERRCODE='22023'; END IF;
     IF old_usage IS NULL OR old_usage='null'::jsonb THEN
      combined:=combined||jsonb_build_object(field_name,usage->field_name);
     ELSIF old_usage->>field_name IS NULL OR usage->>field_name IS NULL THEN
      combined:=combined||jsonb_build_object(field_name,NULL);
     ELSE combined:=combined||jsonb_build_object(field_name,(old_usage->>field_name)::bigint+(usage->>field_name)::bigint);
     END IF;
    END LOOP;
    new_metadata:=new_metadata||jsonb_build_object('usage',combined,
     'usage_responses',coalesce((new_metadata->>'usage_responses')::integer,0)+1);
   END IF;
   UPDATE public.assistant_runtime_runs SET responses=responses||to_jsonb(attempt) WHERE owner=o AND id=rid;
  ELSE RAISE EXCEPTION 'Invalid provider observation phase' USING ERRCODE='22023'; END IF;
  UPDATE public.assistant_runtime_runs SET metadata=new_metadata WHERE owner=o AND id=rid;
 ELSIF kind='recover_interrupted' THEN
  IF at_time<r.deadline_at OR r.status NOT IN ('running','cancelling') THEN RETURN jsonb_build_object('error','stale'); END IF;
  UPDATE public.assistant_runtime_runs SET status='failed',reason='worker_interrupted' WHERE owner=o AND id=rid;
  PERFORM assistant_evidence.append_run_event(o,rid,(p_command->>'event_id')::uuid,'run_failed',NULL,'worker_interrupted');
 ELSIF kind='finish' THEN
  next_status:=p_command->>'status'; terminal_reason:=p_command->>'reason'; duration:=(p_command->>'duration_ms')::numeric;
  IF r.status IN ('completed','cancelled','failed') THEN RETURN jsonb_build_object('error','stale'); END IF;
  IF next_status IS NULL OR next_status NOT IN ('completed','cancelled','failed') OR duration IS NULL OR duration<0 THEN
   RAISE EXCEPTION 'Invalid final run status' USING ERRCODE='22023'; END IF;
  IF next_status='completed' THEN
   IF r.status='cancelling' THEN RETURN jsonb_build_object('error','cancelled'); END IF;
   IF at_time>=r.deadline_at THEN RETURN jsonb_build_object('error','deadline'); END IF;
   IF r.active_spans<>'{}'::jsonb THEN RETURN jsonb_build_object('error','stale'); END IF;
  END IF;
  UPDATE public.assistant_runtime_runs SET status=next_status,reason=terminal_reason,
   metadata=metadata||jsonb_build_object('duration_ms',duration) WHERE owner=o AND id=rid;
  PERFORM assistant_evidence.append_run_event(o,rid,(p_command->>'event_id')::uuid,
   CASE next_status WHEN 'completed' THEN 'run_completed' WHEN 'cancelled' THEN 'run_cancelled' ELSE 'run_failed' END,NULL,terminal_reason);
 END IF;
 UPDATE public.assistant_runtime_runs SET operations=operations||jsonb_build_object(event_key,fingerprint) WHERE owner=o AND id=rid;
 RETURN assistant_evidence.run_projection(o,rid);
EXCEPTION WHEN invalid_parameter_value OR invalid_text_representation OR check_violation OR not_null_violation THEN
 RETURN jsonb_build_object('error','invalid');
END $$;
ALTER FUNCTION assistant_evidence.record_run_observation(jsonb) OWNER TO assistant_evidence_owner;
REVOKE ALL ON FUNCTION assistant_evidence.record_run_observation(jsonb) FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION assistant_evidence.record_run_observation(jsonb) TO assistant_evidence_login;
COMMIT;
