-- REVIEW ONLY / NOT APPLIED. Closed patient content transactions; no clinical writes.
-- Requires reviewed metadata candidate and separately provisioned message owner.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';
GRANT USAGE ON SCHEMA public TO assistant_message_owner;
GRANT EXECUTE ON FUNCTION public.assistant_wf_ref(jsonb),public.assistant_wf_writer_ids(jsonb) TO assistant_message_owner;
GRANT EXECUTE ON FUNCTION public.assistant_patient_uid(),public.assistant_patient_role(),public.assistant_wf_keys(jsonb,text[]),
 public.core_trace_summary_is_safe(jsonb),public.create_conversation(uuid,text),
 public.claim_conversation_turn(uuid,uuid,text),public.append_thread_turn(jsonb),
 public.fail_conversation_turn(uuid),public.append_conversation_turn(jsonb),public.clear_conversation_history()
 TO assistant_message_owner;
GRANT SELECT ON public.agent_sessions,public.conversations,public.conversation_turns,
 public.assistant_workflow_tasks,public.assistant_workflow_operations TO assistant_message_owner;
GRANT SELECT(user_id,conversation_history_enabled) ON public.patient_profiles TO assistant_message_owner;
GRANT INSERT,UPDATE ON public.agent_sessions TO assistant_message_owner;
GRANT INSERT ON public.agent_tool_calls TO assistant_message_owner;
GRANT INSERT ON public.assistant_workflow_operations TO assistant_message_owner;
GRANT UPDATE ON public.assistant_workflow_tasks,public.assistant_workflow_operations TO assistant_message_owner;
CREATE POLICY assistant_message_profile ON public.patient_profiles FOR SELECT TO assistant_message_owner USING(user_id=public.assistant_patient_uid());
CREATE POLICY assistant_message_sessions ON public.agent_sessions TO assistant_message_owner
 USING(patient_id=public.assistant_patient_uid()) WITH CHECK(patient_id=public.assistant_patient_uid());
CREATE POLICY assistant_message_threads ON public.conversations FOR SELECT TO assistant_message_owner USING(patient_id=public.assistant_patient_uid());
CREATE POLICY assistant_message_turns ON public.conversation_turns FOR SELECT TO assistant_message_owner USING(patient_id=public.assistant_patient_uid());
CREATE POLICY assistant_message_traces ON public.agent_tool_calls FOR INSERT TO assistant_message_owner WITH CHECK(patient_id=public.assistant_patient_uid());
CREATE POLICY assistant_message_tasks ON public.assistant_workflow_tasks TO assistant_message_owner USING(owner=public.assistant_patient_uid()) WITH CHECK(owner=public.assistant_patient_uid());
CREATE POLICY assistant_message_controls ON public.assistant_workflow_operations TO assistant_message_owner
 USING(owner=public.assistant_patient_uid() AND record_type IN ('control','action')) WITH CHECK(owner=public.assistant_patient_uid() AND record_type IN ('control','action'));

-- Preserve this existing public signature/owner/ACL for older native callers.
-- Its owner and original function definition must match the approved target
-- baseline before applying this candidate. It remains a patient-only operation.
CREATE OR REPLACE FUNCTION public.clear_conversation_history() RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=public.assistant_patient_uid();
BEGIN
 IF o IS NULL OR public.assistant_patient_role() IS DISTINCT FROM 'authenticated' THEN
  RAISE EXCEPTION 'Verified patient required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 UPDATE public.assistant_workflow_tasks SET data=data||jsonb_build_object('conversation_id',NULL,
  'revision',(data->>'revision')::integer+1,'updated_at',clock_timestamp(),
  'state',CASE WHEN data->>'state' IN ('completed','cancelled') THEN data->>'state' ELSE 'suspended' END)
  WHERE owner=o AND conversation_id IS NOT NULL;
 UPDATE public.assistant_workflow_operations SET data=data||jsonb_build_object('conversation_id',NULL,
  'revision',(data->>'revision')::integer+1,'processing_event_id',NULL,'lease_until',NULL,
  'status',CASE WHEN data->>'status' IN ('completed','cancelled') THEN data->>'status' ELSE 'suspended' END)
  WHERE owner=o AND record_type='control' AND conversation_id IS NOT NULL;
 -- The shared owner advisory fence orders consent reads; this role has no profile UPDATE grant.
 DELETE FROM public.conversation_turns WHERE patient_id=o;
 DELETE FROM public.conversations WHERE patient_id=o;
 UPDATE public.agent_sessions SET context=jsonb_set(jsonb_set(context,'{recent_turns}','[]'::jsonb),
  '{conversation_summary}','""'::jsonb) WHERE patient_id=o;
END $$;

CREATE FUNCTION public.assistant_message_command(p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=public.assistant_patient_uid(); kind text; scope jsonb; control jsonb; payload jsonb;
 incoming public.agent_sessions%ROWTYPE; existing public.agent_sessions%ROWTYPE;
 claim_status text; saved public.conversation_turns%ROWTYPE; result jsonb:=jsonb_build_object('kind','ack');
 allowed text[];
BEGIN
 IF o IS NULL OR public.assistant_patient_role() IS DISTINCT FROM 'authenticated' THEN
  RAISE EXCEPTION 'Verified patient required' USING ERRCODE='42501'; END IF;
 kind:=p_command->>'kind'; scope:=p_command->'scope';
 allowed:=CASE kind
 WHEN 'create_conversation' THEN ARRAY['kind','scope','conversation']
 WHEN 'create_session' THEN ARRAY['kind','scope','session']
 WHEN 'update_context' THEN ARRAY['kind','scope','session']
 WHEN 'bind_session' THEN ARRAY['kind','scope','session']
 WHEN 'claim_turn' THEN ARRAY['kind','scope','conversation_id','turn_id','digest']
 WHEN 'append_turn' THEN ARRAY['kind','scope','session_id','message']
 WHEN 'fail_turn' THEN ARRAY['kind','scope','turn_id']
 WHEN 'append_legacy_history' THEN ARRAY['kind','scope','turn']
 WHEN 'clear_history' THEN ARRAY['kind','scope','confirmed']
 WHEN 'append_safe_trace' THEN ARRAY['kind','scope','trace'] ELSE NULL END;
 IF allowed IS NULL OR NOT public.assistant_wf_keys(p_command,allowed)
 OR scope IS NULL OR NOT public.assistant_wf_keys(scope,ARRAY['task_id','revision','run_binding'])
 OR ((scope->>'task_id' IS NULL)<>(scope->>'revision' IS NULL)) THEN
  RAISE EXCEPTION 'Invalid conversation command' USING ERRCODE='22023'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 IF scope->>'task_id' IS NOT NULL THEN
  PERFORM 1 FROM public.assistant_workflow_tasks WHERE owner=o AND id=(scope->>'task_id')::uuid FOR UPDATE;
  SELECT data INTO control FROM public.assistant_workflow_operations WHERE owner=o AND record_type='control'
  AND task_id=(scope->>'task_id')::uuid AND id=(scope->>'task_id')::uuid FOR UPDATE;
  IF control IS NULL OR control->>'mode' IS DISTINCT FROM 'allowed' OR control->>'revoked' IS DISTINCT FROM 'false'
  OR (control->>'revision')::integer IS DISTINCT FROM (scope->>'revision')::integer THEN
   RAISE EXCEPTION 'Conversation task changed' USING ERRCODE='40001'; END IF;
 END IF;
 IF scope->'run_binding' IS NOT NULL AND scope->'run_binding'<>'null'::jsonb THEN
  PERFORM public.assistant_run_assert_current(o,scope->'run_binding');
 END IF;
 IF kind IN ('create_conversation','claim_turn','append_turn','append_legacy_history') AND NOT EXISTS(
 SELECT 1 FROM public.patient_profiles WHERE user_id=o AND conversation_history_enabled) THEN
  RAISE EXCEPTION 'Conversation history consent changed' USING ERRCODE='40001'; END IF;

 IF kind='create_conversation' THEN
  payload:=p_command->'conversation';
  IF NOT public.assistant_wf_keys(payload,ARRAY['id','title','created_at','updated_at']) THEN
   RAISE EXCEPTION 'Invalid conversation fields' USING ERRCODE='22023'; END IF;
  IF NOT EXISTS(SELECT 1 FROM public.conversations WHERE patient_id=o AND id=(payload->>'id')::uuid) THEN
   PERFORM public.create_conversation((payload->>'id')::uuid,payload->>'title'); END IF;
 ELSIF kind IN ('create_session','update_context','bind_session') THEN
  payload:=p_command->'session';
  IF NOT public.assistant_wf_keys(payload,ARRAY['id','conversation_id','context','intent','state','pending_field_names',
  'state_version','updated_at','expires_at','demo_only']) THEN
   RAISE EXCEPTION 'Invalid session fields' USING ERRCODE='22023'; END IF;
  SELECT * INTO incoming FROM jsonb_populate_record(NULL::public.agent_sessions,
   payload||jsonb_build_object('patient_id',o,'prompt_version','deterministic_router_v1','demo_only',true));
  SELECT * INTO existing FROM public.agent_sessions WHERE patient_id=o AND id=incoming.id FOR UPDATE;
  IF kind='create_session' THEN
   IF FOUND THEN
    IF existing.state_version IS DISTINCT FROM incoming.state_version OR existing.context IS DISTINCT FROM incoming.context
    OR existing.conversation_id IS DISTINCT FROM incoming.conversation_id THEN
     RAISE EXCEPTION 'Existing session changed' USING ERRCODE='40001'; END IF;
   ELSE
    INSERT INTO public.agent_sessions(id,patient_id,conversation_id,context,intent,state,pending_field_names,
     state_version,updated_at,expires_at,prompt_version,demo_only)
    VALUES(incoming.id,o,incoming.conversation_id,incoming.context,incoming.intent,incoming.state,incoming.pending_field_names,
     incoming.state_version,incoming.updated_at,incoming.expires_at,'deterministic_router_v1',true);
   END IF;
  ELSE
   IF NOT FOUND THEN RAISE EXCEPTION 'Owned session unavailable' USING ERRCODE='P0002'; END IF;
   IF existing.conversation_id IS NOT NULL AND existing.conversation_id IS DISTINCT FROM incoming.conversation_id
   OR incoming.state_version<existing.state_version THEN
    RAISE EXCEPTION 'Session binding changed' USING ERRCODE='40001'; END IF;
   IF kind='bind_session' AND (existing.state<>'collecting' OR existing.context->'recent_turns'<>'[]'::jsonb) THEN
    RAISE EXCEPTION 'Fresh session required' USING ERRCODE='40001'; END IF;
   UPDATE public.agent_sessions SET conversation_id=incoming.conversation_id,context=incoming.context,intent=incoming.intent,
    state=incoming.state,pending_field_names=incoming.pending_field_names,state_version=incoming.state_version,
    updated_at=incoming.updated_at,expires_at=incoming.expires_at WHERE patient_id=o AND id=incoming.id;
  END IF;
 ELSIF kind='claim_turn' THEN
  claim_status:=public.claim_conversation_turn((p_command->>'conversation_id')::uuid,
   (p_command->>'turn_id')::uuid,p_command->>'digest');
  result:=jsonb_build_object('kind','claim','status',claim_status);
 ELSIF kind='append_turn' THEN
  payload:=p_command->'message';
  IF NOT public.assistant_wf_keys(payload,ARRAY['id','conversation_id','user_text','assistant_text','photo_attached','created_at']) THEN
   RAISE EXCEPTION 'Invalid message fields' USING ERRCODE='22023'; END IF;
  PERFORM public.append_thread_turn(payload||jsonb_build_object('session_id',p_command->>'session_id'));
  SELECT * INTO saved FROM public.conversation_turns WHERE patient_id=o AND id=(payload->>'id')::uuid;
  IF NOT FOUND OR saved.conversation_id IS DISTINCT FROM (payload->>'conversation_id')::uuid THEN
   RAISE EXCEPTION 'Owned message unavailable' USING ERRCODE='P0002'; END IF;
  result:=jsonb_build_object('kind','message','message',jsonb_build_object('id',saved.id,
   'conversation_id',saved.conversation_id,'user_text',saved.user_text,'assistant_text',saved.full_assistant_text,
   'photo_attached',saved.photo_attached,'created_at',saved.created_at));
 ELSIF kind='fail_turn' THEN
  PERFORM public.fail_conversation_turn((p_command->>'turn_id')::uuid);
 ELSIF kind='append_legacy_history' THEN
  payload:=p_command->'turn';
  IF NOT public.assistant_wf_keys(payload,ARRAY['id','session_id','user_text','assistant_text','created_at']) THEN
   RAISE EXCEPTION 'Invalid history fields' USING ERRCODE='22023'; END IF;
  PERFORM public.append_conversation_turn(payload||jsonb_build_object('patient_id',o));
 ELSIF kind='clear_history' THEN
  IF p_command->'confirmed' IS DISTINCT FROM 'true'::jsonb THEN
   RAISE EXCEPTION 'Independent clear confirmation required' USING ERRCODE='22023'; END IF;
  -- The compatible native RPC also detaches035 links for older native callers.
  PERFORM public.clear_conversation_history();
 ELSIF kind='append_safe_trace' THEN
  payload:=p_command->'trace';
  IF NOT public.assistant_wf_keys(payload,ARRAY['id','session_id','correlation_id','tool_name','tool_status',
   'request_summary','response_summary','called_at','duration_ms','demo_only'])
   OR NOT public.core_trace_summary_is_safe(payload->'request_summary')
   OR NOT public.core_trace_summary_is_safe(payload->'response_summary') THEN
   RAISE EXCEPTION 'Invalid safe trace fields' USING ERRCODE='22023'; END IF;
  IF NOT EXISTS(SELECT 1 FROM public.agent_sessions WHERE patient_id=o AND id=(payload->>'session_id')::uuid) THEN
   RAISE EXCEPTION 'Owned trace session unavailable' USING ERRCODE='P0002'; END IF;
  INSERT INTO public.agent_tool_calls(id,patient_id,session_id,correlation_id,tool_name,tool_status,
   request_summary,response_summary,called_at,duration_ms,demo_only)
  VALUES((payload->>'id')::uuid,o,(payload->>'session_id')::uuid,(payload->>'correlation_id')::uuid,
   payload->>'tool_name',payload->>'tool_status',payload->'request_summary',payload->'response_summary',
   (payload->>'called_at')::timestamptz,(payload->>'duration_ms')::integer,true);
 END IF;
 RETURN jsonb_build_object('result',result);
EXCEPTION
 WHEN SQLSTATE '40001' THEN RETURN jsonb_build_object('error','stale');
 WHEN SQLSTATE 'P0002' THEN RETURN jsonb_build_object('error','not_found');
 WHEN invalid_parameter_value OR invalid_text_representation OR check_violation OR unique_violation THEN
  RETURN jsonb_build_object('error','invalid');
END $$;
ALTER FUNCTION public.assistant_message_command(jsonb) OWNER TO assistant_message_owner;
REVOKE ALL ON FUNCTION public.assistant_message_command(jsonb) FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;
GRANT EXECUTE ON FUNCTION public.assistant_message_command(jsonb) TO authenticated;
-- Explicit native conversation transition: own task + native session + minimal
-- receipt share one owner fence. No callback, history body cache or clinical write.
CREATE FUNCTION public.assistant_conversation_transition(p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=public.assistant_patient_uid(); t jsonb; c jsonb; a jsonb; tid uuid; aid uuid; sid uuid;
 cap text; target uuid; rev integer; native public.agent_sessions%ROWTYPE;
 context_data jsonb:='{"version":1,"recent_turns":[],"conversation_summary":""}'::jsonb; conversation uuid; result jsonb; stamp timestamptz:=clock_timestamp();
BEGIN
 IF o IS NULL OR public.assistant_patient_role() IS DISTINCT FROM 'authenticated' THEN
  RAISE EXCEPTION 'Verified patient required' USING ERRCODE='42501'; END IF;
 IF NOT public.assistant_wf_keys(p_command,ARRAY['task_id','revision','capability_id','target','action_key','session_id','confirmed'])
 OR p_command->'confirmed' IS DISTINCT FROM 'true'::jsonb THEN
  RAISE EXCEPTION 'Independent conversation confirmation required' USING ERRCODE='22023'; END IF;
 tid:=(p_command->>'task_id')::uuid; aid:=(p_command->>'action_key')::uuid;
 sid:=(p_command->>'session_id')::uuid; cap:=p_command->>'capability_id';
 target:=(p_command->>'target')::uuid; rev:=(p_command->>'revision')::integer;
 IF tid IS NULL OR aid IS NULL OR sid IS NULL OR rev IS NULL OR cap IS NULL OR rev<1 OR cap NOT IN ('conversation.new','conversation.resume','conversation.clear')
 OR ((cap='conversation.resume')<>(target IS NOT NULL)) THEN
  RAISE EXCEPTION 'Invalid conversation transition' USING ERRCODE='22023'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 SELECT data INTO t FROM public.assistant_workflow_tasks WHERE owner=o AND id=tid FOR UPDATE;
 SELECT data INTO c FROM public.assistant_workflow_operations WHERE owner=o AND record_type='control' AND id=tid FOR UPDATE;
 SELECT data INTO a FROM public.assistant_workflow_operations WHERE owner=o AND record_type='action' AND id=aid;
 IF t IS NULL OR c IS NULL OR c->>'mode' IS DISTINCT FROM 'allowed' OR c->>'revoked' IS DISTINCT FROM 'false'
 OR t->>'capability_id' IS DISTINCT FROM cap OR t->>'save_mode' IS DISTINCT FROM 'allowed'
 OR t->'fields'->>'conversation_id' IS DISTINCT FROM target::text THEN
  RAISE EXCEPTION 'Owned conversation task changed' USING ERRCODE='40001'; END IF;
 IF a IS NOT NULL THEN
  IF a->>'task_id' IS DISTINCT FROM tid::text OR a->>'capability_id' IS DISTINCT FROM cap
  OR (a->>'binding_revision')::integer IS DISTINCT FROM rev OR a->>'state'<>'succeeded'
  OR (cap<>'conversation.clear' AND a->'business_ref'->>'id' IS DISTINCT FROM sid::text) THEN
   RAISE EXCEPTION 'Conversation receipt binding changed' USING ERRCODE='40001'; END IF;
 ELSE
  IF (t->>'revision')::integer IS DISTINCT FROM rev OR (c->>'revision')::integer IS DISTINCT FROM rev
  OR c->>'status' IS DISTINCT FROM 'idle' OR t->>'state' IN ('cancelled','completed','suspended') THEN
   RAISE EXCEPTION 'Current saved conversation action required' USING ERRCODE='40001'; END IF;
  -- The shared owner advisory fence orders consent reads; this role has no profile UPDATE grant.
  IF cap='conversation.clear' THEN
   PERFORM public.clear_conversation_history();
  ELSE
   IF cap='conversation.resume' THEN
    IF NOT EXISTS(SELECT 1 FROM public.patient_profiles WHERE user_id=o AND conversation_history_enabled)
    OR NOT EXISTS(SELECT 1 FROM public.conversations WHERE patient_id=o AND id=target) THEN
     RAISE EXCEPTION 'Owned retained conversation required' USING ERRCODE='P0002'; END IF;
    conversation:=target;
    SELECT context_data||jsonb_build_object('recent_turns',COALESCE(jsonb_agg(jsonb_build_object(
     'user',left(q.user_text,500),'assistant',left(coalesce(q.full_assistant_text,q.assistant_text,''),700)) ORDER BY q.created_at,q.id),'[]'::jsonb))
     INTO context_data FROM (SELECT id,created_at,user_text,assistant_text,full_assistant_text FROM public.conversation_turns
      WHERE patient_id=o AND conversation_id=target ORDER BY created_at DESC,id DESC LIMIT 6) q;
   END IF;
   INSERT INTO public.agent_sessions(id,patient_id,conversation_id,context,intent,state,pending_field_names,
    state_version,updated_at,expires_at,prompt_version,demo_only)
   VALUES(sid,o,conversation,context_data,NULL,'collecting','{}'::text[],1,stamp,stamp+interval '2 hours','deterministic_router_v1',true);
  END IF;
  INSERT INTO public.assistant_workflow_operations(owner,record_type,id,task_id,data)
   VALUES(o,'action',aid,tid,jsonb_build_object('owner',o,'action_key',aid,'task_id',tid,'capability_id',cap,
    'binding_revision',rev,'state','succeeded','business_ref',jsonb_build_object(
     'kind',CASE WHEN cap='conversation.clear' THEN 'conversation_cleanup' ELSE 'agent_session' END,
     'id',CASE WHEN cap='conversation.clear' THEN aid ELSE sid END),'updated_at',stamp));
 END IF;
 IF cap='conversation.clear' THEN RETURN jsonb_build_object('session',NULL); END IF;
 SELECT * INTO native FROM public.agent_sessions WHERE patient_id=o AND id=sid;
 IF NOT FOUND OR native.conversation_id IS DISTINCT FROM target THEN
  RAISE EXCEPTION 'Actual native session unavailable' USING ERRCODE='P0002'; END IF;
 result:=jsonb_build_object('id',native.id,'patient_id',o,'conversation_id',native.conversation_id,'context',native.context,
  'intent',native.intent,'state',native.state,'pending_field_names',native.pending_field_names,'state_version',native.state_version,
  'updated_at',native.updated_at,'expires_at',native.expires_at,'demo_only',native.demo_only);
 RETURN jsonb_build_object('session',result);
END $$;
ALTER FUNCTION public.assistant_conversation_transition(jsonb) OWNER TO assistant_message_owner;
REVOKE ALL ON FUNCTION public.assistant_conversation_transition(jsonb) FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;
GRANT EXECUTE ON FUNCTION public.assistant_conversation_transition(jsonb) TO authenticated;

-- Browser-only subscription metadata. This function cannot send notifications.
GRANT SELECT,INSERT,UPDATE ON public.push_subscriptions TO assistant_message_owner;
CREATE POLICY assistant_message_subscriptions ON public.push_subscriptions TO assistant_message_owner
 USING(patient_id=public.assistant_patient_uid()) WITH CHECK(patient_id=public.assistant_patient_uid());
CREATE FUNCTION public.assistant_notification_transition(p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=public.assistant_patient_uid(); tid uuid; rev integer; aid uuid; cap text; t jsonb; c jsonb; a jsonb;
 input jsonb; digest text; target uuid; selected_endpoint text; sub public.push_subscriptions%ROWTYPE;
BEGIN
 IF o IS NULL OR public.assistant_patient_role() IS DISTINCT FROM 'authenticated' THEN
  RAISE EXCEPTION 'Verified patient required' USING ERRCODE='42501'; END IF;
 IF NOT public.assistant_wf_keys(p_command,ARRAY['task_id','revision','capability_id','action_key','confirmed','subscription','subscription_id','endpoint'])
 OR p_command->'confirmed' IS DISTINCT FROM 'true'::jsonb THEN
  RAISE EXCEPTION 'Independent browser confirmation required' USING ERRCODE='22023'; END IF;
 tid:=(p_command->>'task_id')::uuid; rev:=(p_command->>'revision')::integer;
 aid:=(p_command->>'action_key')::uuid; cap:=p_command->>'capability_id';
 target:=(p_command->>'subscription_id')::uuid; selected_endpoint:=p_command->>'endpoint';
 digest:=encode(sha256(convert_to(p_command::text,'UTF8')),'hex');
 IF tid IS NULL OR aid IS NULL OR rev IS NULL OR rev<1 OR cap IS NULL
 OR cap NOT IN ('notification.subscribe','notification.unsubscribe') THEN
  RAISE EXCEPTION 'Invalid subscription action' USING ERRCODE='22023'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 SELECT data INTO t FROM public.assistant_workflow_tasks WHERE owner=o AND id=tid FOR UPDATE;
 SELECT data INTO c FROM public.assistant_workflow_operations WHERE owner=o AND record_type='control' AND id=tid FOR UPDATE;
 IF t IS NULL OR c IS NULL OR t->>'capability_id' IS DISTINCT FROM cap
 OR t->>'save_mode' IS DISTINCT FROM 'allowed' OR c->>'mode' IS DISTINCT FROM 'allowed'
 OR c->>'revoked' IS DISTINCT FROM 'false' OR c->>'status' IS DISTINCT FROM 'idle'
 OR (t->>'revision')::int IS DISTINCT FROM rev OR (c->>'revision')::int IS DISTINCT FROM rev
 OR t->>'state' IN ('cancelled','suspended','completed') THEN
  RAISE EXCEPTION 'Current owned subscription task required' USING ERRCODE='40001'; END IF;
 SELECT data INTO a FROM public.assistant_workflow_operations WHERE owner=o AND record_type='action' AND id=aid;
 IF a IS NOT NULL THEN
  IF a->>'task_id' IS DISTINCT FROM tid::text OR a->>'capability_id' IS DISTINCT FROM cap
  OR (a->>'binding_revision')::int IS DISTINCT FROM rev OR a->>'safe_reason' IS DISTINCT FROM digest THEN
   RAISE EXCEPTION 'Subscription receipt binding changed' USING ERRCODE='40001'; END IF;
  IF cap='notification.unsubscribe' THEN RETURN jsonb_build_object('subscription',NULL); END IF;
  SELECT * INTO sub FROM public.push_subscriptions WHERE patient_id=o AND id=(a->'business_ref'->>'id')::uuid;
  IF NOT FOUND OR NOT sub.enabled THEN RAISE EXCEPTION 'Current subscription changed' USING ERRCODE='40001'; END IF;
  RETURN jsonb_build_object('subscription',jsonb_build_object('id',sub.id,'enabled',sub.enabled));
 END IF;
 IF cap='notification.subscribe' THEN
  input:=p_command->'subscription';
  IF input IS NULL OR input='null'::jsonb OR target IS NOT NULL OR selected_endpoint IS NOT NULL
  OR NOT public.assistant_wf_keys(input,ARRAY['endpoint','keys'])
  OR NOT public.assistant_wf_keys(input->'keys',ARRAY['p256dh','auth'])
  OR input->>'endpoint' IS NULL OR input->'keys'->>'p256dh' IS NULL OR input->'keys'->>'auth' IS NULL THEN
   RAISE EXCEPTION 'Invalid subscription input' USING ERRCODE='22023'; END IF;
  IF length(input->>'endpoint') NOT BETWEEN 12 AND 2048
  OR input->>'endpoint' !~* '^https://(fcm[.]googleapis[.]com|updates[.]push[.]services[.]mozilla[.]com|([a-z0-9-]+[.])+push[.]apple[.]com|([a-z0-9-]+[.])+notify[.]windows[.]com)(:443)?([/?][^#[:space:]]*)?$'
  OR length(input->'keys'->>'p256dh') NOT BETWEEN 86 AND 100
  OR length(input->'keys'->>'auth') NOT BETWEEN 22 AND 30
  OR input->'keys'->>'p256dh' !~ '^[A-Za-z0-9_-]+={0,2}$'
  OR input->'keys'->>'auth' !~ '^[A-Za-z0-9_-]+={0,2}$' THEN
   RAISE EXCEPTION 'Invalid browser subscription' USING ERRCODE='22023'; END IF;
  IF octet_length(decode(translate(input->'keys'->>'p256dh','-_','+/')||repeat('=',(4-length(input->'keys'->>'p256dh')%4)%4),'base64'))<>65
  OR get_byte(decode(translate(input->'keys'->>'p256dh','-_','+/')||repeat('=',(4-length(input->'keys'->>'p256dh')%4)%4),'base64'),0)<>4
  OR octet_length(decode(translate(input->'keys'->>'auth','-_','+/')||repeat('=',(4-length(input->'keys'->>'auth')%4)%4),'base64'))<>16 THEN
   RAISE EXCEPTION 'Invalid browser subscription keys' USING ERRCODE='22023'; END IF;
  INSERT INTO public.push_subscriptions(patient_id,endpoint,keys,enabled)
   VALUES(o,input->>'endpoint',input->'keys',true)
   ON CONFLICT(patient_id,endpoint) DO UPDATE SET keys=EXCLUDED.keys,enabled=true
   RETURNING * INTO sub;
 ELSE
  IF p_command->'subscription' IS DISTINCT FROM 'null'::jsonb
  OR ((target IS NULL)=(selected_endpoint IS NULL)) THEN
   RAISE EXCEPTION 'Choose one owned subscription selector' USING ERRCODE='22023'; END IF;
  UPDATE public.push_subscriptions SET enabled=false WHERE patient_id=o AND
   (CASE WHEN target IS NOT NULL THEN id=target ELSE push_subscriptions.endpoint=selected_endpoint END);
 END IF;
 INSERT INTO public.assistant_workflow_operations(owner,record_type,id,task_id,data)
 VALUES(o,'action',aid,tid,jsonb_build_object('owner',o,'action_key',aid,'task_id',tid,'capability_id',cap,
  'binding_revision',rev,'state','succeeded','safe_reason',digest,'business_ref',
  CASE WHEN cap='notification.subscribe' THEN jsonb_build_object('kind','settings_action','id',sub.id) ELSE NULL END,
  'updated_at',clock_timestamp()));
 RETURN jsonb_build_object('subscription',CASE WHEN cap='notification.subscribe'
  THEN jsonb_build_object('id',sub.id,'enabled',sub.enabled) ELSE NULL END);
END $$;
ALTER FUNCTION public.assistant_notification_transition(jsonb) OWNER TO assistant_message_owner;
REVOKE ALL ON FUNCTION public.assistant_notification_transition(jsonb) FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;
GRANT EXECUTE ON FUNCTION public.assistant_notification_transition(jsonb) TO authenticated;

COMMIT;
