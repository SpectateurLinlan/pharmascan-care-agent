-- REVIEW ONLY / NOT APPLIED. Dependencies: metadata/messages/runs review candidates.
-- Storage policies and bucket configuration are outside this candidate.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';
ALTER TABLE public.assistant_storage_tickets ADD COLUMN run_binding jsonb
 CHECK(run_binding IS NULL OR (public.assistant_wf_keys(run_binding,ARRAY['run_id','epoch'])
 AND (run_binding->>'run_id')::uuid IS NOT NULL AND (run_binding->>'epoch')::int>0));

-- Extend only the original purpose/MIME/size/extraction checks in035. Preserve all
-- other clauses of each check, including the compound cleanup record constraint.
-- Target inspection must compare these definitions before any approved execution.
DO $$ DECLARE c record; definition text; revised text; BEGIN
 FOR c IN SELECT conname,conrelid,pg_get_constraintdef(oid) AS definition FROM pg_constraint
 WHERE contype='c' AND conrelid IN ('public.assistant_workflow_attachments'::regclass,
 'public.assistant_workflow_operations'::regclass) LOOP
  definition:=c.definition;
  revised:=replace(definition,'ARRAY[''image/png''::text, ''image/jpeg''::text]',
   'ARRAY[''image/png''::text, ''image/jpeg''::text, ''application/pdf''::text]');
  IF c.conrelid='public.assistant_workflow_attachments'::regclass THEN
   revised:=replace(revised,'ARRAY[''package''::text, ''pharmacy_label''::text, ''prescription''::text]',
    'ARRAY[''package''::text, ''pharmacy_label''::text, ''prescription''::text, ''reference_photo''::text, ''library_pdf''::text, ''comparison_photo''::text, ''source_preview_photo''::text]');
   revised:=replace(revised,'''interrupted''::text]', '''interrupted''::text, ''not_requested''::text]');
   IF revised LIKE '%byte_size%8000000%' THEN revised:=replace(revised,'8000000','10485760'); END IF;
  END IF;
  IF revised<>definition THEN
   EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I',c.conrelid::regclass,c.conname);
   EXECUTE format('ALTER TABLE %s ADD CONSTRAINT %I %s',c.conrelid::regclass,c.conname,revised);
  END IF;
 END LOOP;
END $$;
CREATE FUNCTION public.assistant_original_metadata_valid(p_data jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SECURITY INVOKER SET search_path='' AS $$
 SELECT coalesce(CASE WHEN p_data->>'source_kind'='library_pdf' THEN
 p_data->>'content_type'='application/pdf' AND (p_data->>'byte_size')::integer BETWEEN 1 AND 10485760
 AND p_data->>'extraction_status'='not_requested'
 ELSE p_data->>'source_kind'=ANY(ARRAY['package','pharmacy_label','prescription','reference_photo','comparison_photo','source_preview_photo'])
 AND p_data->>'content_type'=ANY(ARRAY['image/png','image/jpeg'])
 AND (p_data->>'byte_size')::integer BETWEEN 1 AND 8000000
 AND (p_data->>'extraction_status'<>'not_requested' OR p_data->>'source_kind'=ANY(ARRAY['reference_photo','comparison_photo','source_preview_photo'])) END,false)
$$;
REVOKE ALL ON FUNCTION public.assistant_original_metadata_valid(jsonb) FROM PUBLIC,anon,service_role;
GRANT EXECUTE ON FUNCTION public.assistant_original_metadata_valid(jsonb) TO authenticated,assistant_workflow_owner;
ALTER TABLE public.assistant_workflow_attachments ADD CONSTRAINT assistant_original_native_limits
 CHECK(public.assistant_original_metadata_valid(data));

GRANT SELECT,INSERT,UPDATE ON public.assistant_storage_tickets TO assistant_workflow_owner;
GRANT SELECT ON public.assistant_verified_operations TO assistant_workflow_owner;
CREATE POLICY assistant_storage_patient_command ON public.assistant_storage_tickets TO assistant_workflow_owner
 USING(owner=auth.uid()) WITH CHECK(owner=auth.uid());
CREATE POLICY assistant_verified_patient_command ON public.assistant_verified_operations FOR SELECT TO assistant_workflow_owner
 USING(owner=auth.uid());
CREATE POLICY assistant_workflow_original_command ON public.assistant_workflow_attachments TO assistant_workflow_owner
 USING(owner=auth.uid()) WITH CHECK(owner=auth.uid());
GRANT SELECT,UPDATE ON public.assistant_workflow_attachments TO assistant_workflow_owner;

CREATE TABLE public.assistant_original_deletions (
 owner uuid NOT NULL REFERENCES public.patient_profiles(user_id), attachment_id uuid NOT NULL,
 task_id uuid NOT NULL, ticket_id uuid NOT NULL REFERENCES public.assistant_storage_tickets(id),
 state text NOT NULL CHECK(state IN ('deleting','deleted')), PRIMARY KEY(owner,attachment_id)
);
ALTER TABLE public.assistant_original_deletions OWNER TO assistant_workflow_owner;
ALTER TABLE public.assistant_original_deletions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assistant_original_deletions FORCE ROW LEVEL SECURITY;
CREATE POLICY assistant_original_delete_owner ON public.assistant_original_deletions TO assistant_workflow_owner
 USING(owner=auth.uid()) WITH CHECK(owner=auth.uid());
REVOKE ALL ON public.assistant_original_deletions FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;

CREATE FUNCTION assistant_evidence.storage_ticket_projection(p_ticket uuid) RETURNS jsonb
LANGUAGE sql SECURITY INVOKER SET search_path='' AS $$
 SELECT jsonb_build_object('ticket_id',t.id,'nonce',t.nonce,'task_id',t.task_id,'attachment_id',t.attachment_id,
 'writer_id',t.writer_id,'operation',t.operation,'generation',t.generation,'object_ref',t.object_ref,
 'expected_checksum',t.expected_checksum,'content_type',t.content_type,'byte_size',t.byte_size,'expires_at',t.expires_at)
 FROM public.assistant_storage_tickets t WHERE id=p_ticket AND owner=auth.uid()
$$;
ALTER FUNCTION assistant_evidence.storage_ticket_projection(uuid) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION assistant_evidence.storage_ticket_projection(uuid) FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login;

-- All original reference paths, including old035 calls, take the owner fence and
-- reject a persisted deletion exclusion. Triggers are a secondary fence; domain
-- commands must take the owner fence before their first row lock (I08/I11).
CREATE FUNCTION public.assistant_original_reference_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid; ids jsonb; item jsonb; attachment uuid;
BEGIN
 o:=NEW.owner;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 IF TG_TABLE_NAME='assistant_workflow_tasks' THEN
  ids:=coalesce(NEW.data->'attachment_ids','[]'::jsonb);
  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(NEW.data->'business_refs','[]'::jsonb)) LOOP
   IF item->>'kind'='file' THEN ids:=ids||jsonb_build_array(item->'id'); END IF;
  END LOOP;
 ELSE ids:=jsonb_build_array(NEW.id); END IF;
 FOR attachment IN SELECT value::uuid FROM jsonb_array_elements_text(ids) LOOP
  IF EXISTS(SELECT 1 FROM public.assistant_original_deletions WHERE owner=o AND attachment_id=attachment) THEN
   RAISE EXCEPTION 'Original deletion excludes new references and publication' USING ERRCODE='40001'; END IF;
 END LOOP;
 IF TG_TABLE_NAME='assistant_workflow_attachments' AND TG_OP='UPDATE'
 AND OLD.data->'source_ref' IS NOT NULL AND OLD.data->'source_ref'<>'null'::jsonb
 AND OLD.data->'source_ref' IS DISTINCT FROM NEW.data->'source_ref' THEN
  RAISE EXCEPTION 'Formal source protection cannot be lowered' USING ERRCODE='40001'; END IF;
 RETURN NEW;
END $$;
ALTER FUNCTION public.assistant_original_reference_guard() OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_original_reference_guard() FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login;
CREATE TRIGGER assistant_original_reference_task BEFORE INSERT OR UPDATE ON public.assistant_workflow_tasks
 FOR EACH ROW EXECUTE FUNCTION public.assistant_original_reference_guard();
CREATE TRIGGER assistant_original_reference_attachment BEFORE INSERT OR UPDATE ON public.assistant_workflow_attachments
 FOR EACH ROW EXECUTE FUNCTION public.assistant_original_reference_guard();

-- Keep035 bytes intact. Its implementation becomes private; all public/native
-- routes retain their validation but cannot directly attest Storage completion.
ALTER FUNCTION public.assistant_workflow_command(text,jsonb) RENAME TO assistant_workflow_command_legacy_035;
REVOKE ALL ON FUNCTION public.assistant_workflow_command_legacy_035(text,jsonb) FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login;
GRANT EXECUTE ON FUNCTION public.assistant_workflow_command_legacy_035(text,jsonb) TO assistant_workflow_owner;
CREATE FUNCTION public.assistant_workflow_command(p_operation text,p_input jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=auth.uid(); a jsonb;
BEGIN
 IF o IS NULL OR auth.role() IS DISTINCT FROM 'authenticated' THEN RAISE EXCEPTION 'Verified patient required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 IF p_operation IN ('original_publish','original_written','cleanup_written','cleanup_update') THEN
  RETURN jsonb_build_object('error','unavailable'); END IF;
 IF p_operation='original_extract' THEN
  SELECT data INTO a FROM public.assistant_workflow_attachments WHERE owner=o AND id=(p_input->'attachment'->>'id')::uuid;
  IF a->>'state' IS DISTINCT FROM 'saved' OR p_input->'attachment'->>'state' IS DISTINCT FROM 'saved' THEN
   RETURN jsonb_build_object('error','stale'); END IF;
 END IF;
 RETURN public.assistant_workflow_command_legacy_035(p_operation,p_input);
END $$;
ALTER FUNCTION public.assistant_workflow_command(text,jsonb) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_workflow_command(text,jsonb) FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login;
GRANT EXECUTE ON FUNCTION public.assistant_workflow_command(text,jsonb) TO authenticated;

CREATE FUNCTION public.assistant_original_command(p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=auth.uid(); kind text; allowed text[]; ctx jsonb; tid uuid; aid uuid; a jsonb; c jsonb; args jsonb;
 t public.assistant_storage_tickets%ROWTYPE; proof public.assistant_verified_operations%ROWTYPE;
 ref jsonb; child jsonb; remaining jsonb; ticket_id uuid; writer uuid; generation integer;
BEGIN
 IF o IS NULL OR auth.role() IS DISTINCT FROM 'authenticated' THEN RAISE EXCEPTION 'Verified patient required' USING ERRCODE='42501'; END IF;
 kind:=p_command->>'kind';
 allowed:=CASE kind
 WHEN 'native' THEN ARRAY['kind','operation','input','run_binding']
 WHEN 'reserve_ticket' THEN ARRAY['kind','context','attachment_id','writer_id','run_binding']
 WHEN 'claim_ticket' THEN ARRAY['kind','ticket_id','generation']
 WHEN 'read_verified' THEN ARRAY['kind','reference']
 WHEN 'settle_writer' THEN ARRAY['kind','reference']
 WHEN 'publish_verified' THEN ARRAY['kind','context','attachment_id','reference','run_binding']
 WHEN 'start_deleting' THEN ARRAY['kind','attachment_id']
 WHEN 'settle_cleanup' THEN ARRAY['kind','reference'] ELSE NULL END;
 IF allowed IS NULL OR NOT public.assistant_wf_keys(p_command,allowed) THEN RAISE EXCEPTION 'Invalid original command' USING ERRCODE='22023'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 ctx:=p_command->'context'; ref:=p_command->'reference';
 IF kind IN ('read_verified','settle_writer','publish_verified','settle_cleanup')
 AND (ref IS NULL OR ref='null'::jsonb) THEN RETURN jsonb_build_object('error','invalid'); END IF;
 tid:=(ctx->>'task_id')::uuid; aid:=(p_command->>'attachment_id')::uuid;
 IF tid IS NOT NULL THEN
  PERFORM 1 FROM public.assistant_workflow_tasks WHERE owner=o AND id=tid FOR UPDATE;
  SELECT data INTO c FROM public.assistant_workflow_operations WHERE owner=o AND record_type='control' AND task_id=tid FOR UPDATE;
  IF NOT public.assistant_wf_keys(ctx,ARRAY['task_id','capability_id','revision','save_mode','language','timezone'])
  OR c IS NULL OR c->>'mode'<>'allowed' OR c->>'revoked'<>'false' OR ctx->>'save_mode'<>'allowed'
  OR c->>'revision' IS DISTINCT FROM ctx->>'revision' OR c->>'capability_id' IS DISTINCT FROM ctx->>'capability_id' THEN
   RETURN jsonb_build_object('error','stale'); END IF;
 END IF;
 IF p_command->'run_binding' IS NOT NULL AND p_command->'run_binding'<>'null'::jsonb THEN
  PERFORM public.assistant_run_assert_current(o,p_command->'run_binding'); END IF;
 IF kind='native' THEN
  IF p_command->>'operation' NOT IN ('original_get','original_list','original_upload','original_reserve',
   'original_retry','original_begin','original_extract','original_protect') THEN RETURN jsonb_build_object('error','invalid'); END IF;
  -- The compatibility wrapper keeps source ownership/review and deletion guards.
  RETURN public.assistant_workflow_command(p_command->>'operation',p_command->'input');
 END IF;
 IF ref IS NOT NULL THEN
  IF NOT public.assistant_wf_keys(ref,ARRAY['ticket_id','verification_id','generation','result']) THEN
   RETURN jsonb_build_object('error','invalid'); END IF;
  SELECT * INTO proof FROM public.assistant_verified_operations WHERE owner=o AND id=(ref->>'verification_id')::uuid
   AND ticket_id=(ref->>'ticket_id')::uuid AND generation=(ref->>'generation')::int AND result=ref->>'result';
  IF NOT FOUND THEN RETURN jsonb_build_object('error','unavailable'); END IF;
  SELECT * INTO t FROM public.assistant_storage_tickets WHERE owner=o AND id=proof.ticket_id FOR UPDATE;
  IF aid IS NOT NULL AND (aid<>t.attachment_id OR tid IS DISTINCT FROM t.task_id) THEN RETURN jsonb_build_object('error','stale'); END IF;
  aid:=t.attachment_id; tid:=t.task_id;
 END IF;
 IF kind='read_verified' THEN RETURN jsonb_build_object('result',assistant_evidence.storage_ticket_projection(t.id)); END IF;
 IF kind='claim_ticket' THEN
  SELECT * INTO t FROM public.assistant_storage_tickets WHERE owner=o AND id=(p_command->>'ticket_id')::uuid FOR UPDATE;
  IF NOT FOUND THEN RETURN jsonb_build_object('error','not_found'); END IF;
  IF t.state<>'issued' OR t.generation IS DISTINCT FROM (p_command->>'generation')::int OR clock_timestamp()>=t.expires_at THEN
   RETURN jsonb_build_object('error','stale'); END IF;
  IF t.operation='upload' THEN
   IF t.run_binding IS NOT NULL AND t.run_binding<>'null'::jsonb THEN
    PERFORM public.assistant_run_assert_current(o,t.run_binding); END IF;
   SELECT data INTO c FROM public.assistant_workflow_operations WHERE owner=o AND record_type='control' AND task_id=t.task_id;
   IF c IS NULL OR c->>'mode'<>'allowed' OR c->>'revoked'<>'false' OR EXISTS(SELECT 1 FROM public.assistant_original_deletions
    WHERE owner=o AND attachment_id=t.attachment_id) THEN RETURN jsonb_build_object('error','stale'); END IF;
  END IF;
  UPDATE public.assistant_storage_tickets SET state='inflight' WHERE owner=o AND id=t.id;
  RETURN jsonb_build_object('result',true);
 END IF;
 IF kind IN ('reserve_ticket','publish_verified') THEN
  IF tid IS NULL OR aid IS NULL OR EXISTS(SELECT 1 FROM public.assistant_original_deletions WHERE owner=o AND attachment_id=aid) THEN
   RETURN jsonb_build_object('error','stale'); END IF;
  SELECT data INTO a FROM public.assistant_workflow_attachments WHERE owner=o AND id=aid AND task_id=tid FOR UPDATE;
  IF a IS NULL THEN RETURN jsonb_build_object('error','not_found'); END IF;
  IF kind='reserve_ticket' THEN
   writer:=(p_command->>'writer_id')::uuid;
   IF writer IS NULL OR NOT (a->'pending_writer_ids' @> jsonb_build_array(writer)) THEN RETURN jsonb_build_object('error','stale'); END IF;
   IF EXISTS(SELECT 1 FROM public.assistant_storage_tickets WHERE owner=o AND attachment_id=aid AND writer_id=writer) THEN
    RETURN jsonb_build_object('error','duplicate'); END IF;
   SELECT coalesce(max(s.generation),0)+1 INTO generation FROM public.assistant_storage_tickets s WHERE owner=o AND attachment_id=aid;
   ticket_id:=gen_random_uuid();
   INSERT INTO public.assistant_storage_tickets(owner,id,nonce,task_id,attachment_id,writer_id,operation,generation,
    object_ref,expected_checksum,content_type,byte_size,expires_at,run_binding) VALUES(o,ticket_id,gen_random_uuid(),tid,aid,writer,'upload',generation,
    a->>'object_ref',a->>'original_checksum',a->>'content_type',(a->>'byte_size')::int,clock_timestamp()+interval '45 seconds',nullif(p_command->'run_binding','null'::jsonb));
   RETURN jsonb_build_object('result',assistant_evidence.storage_ticket_projection(ticket_id));
  END IF;
  IF proof.result<>'bytes_verified' OR t.operation<>'upload' OR a->>'operation_event_id' IS DISTINCT FROM t.writer_id::text THEN
   RETURN jsonb_build_object('error','stale'); END IF;
  args:=jsonb_build_object('context',ctx,'task_id',tid,'attachment',a,'event_id',t.writer_id);
  child:=public.assistant_workflow_command_legacy_035('original_publish',args);
  IF child ? 'error' THEN RAISE EXCEPTION 'Publication transaction rejected' USING ERRCODE='40001'; END IF;
  RETURN child;
 END IF;
 IF kind='settle_writer' THEN
  IF t.operation IS DISTINCT FROM 'upload' OR proof.result NOT IN ('bytes_verified','definitely_not_started') THEN RETURN jsonb_build_object('error','stale'); END IF;
  SELECT data INTO a FROM public.assistant_workflow_attachments WHERE owner=o AND id=aid AND task_id=tid FOR UPDATE;
  IF a IS NOT NULL THEN
   SELECT coalesce(jsonb_agg(x),'[]'::jsonb) INTO remaining FROM jsonb_array_elements(a->'pending_writer_ids') x WHERE x<>to_jsonb(t.writer_id);
   UPDATE public.assistant_workflow_attachments SET data=a||jsonb_build_object('pending_writer_ids',remaining,
    'object_written',(a->>'object_written')::boolean OR proof.result='bytes_verified') WHERE owner=o AND id=aid;
  ELSE
   SELECT data INTO a FROM public.assistant_workflow_operations WHERE owner=o AND record_type='cleanup' AND id=aid FOR UPDATE;
   IF a IS NULL THEN RETURN jsonb_build_object('error','not_found'); END IF;
   SELECT coalesce(jsonb_agg(x),'[]'::jsonb) INTO remaining FROM jsonb_array_elements(a->'pending_writer_ids') x WHERE x<>to_jsonb(t.writer_id);
   UPDATE public.assistant_workflow_operations SET data=a||jsonb_build_object('pending_writer_ids',remaining,
    'writer_pending',jsonb_array_length(remaining)>0,'state','pending','reason',CASE WHEN jsonb_array_length(remaining)>0 THEN 'upload_inflight' END)
    WHERE owner=o AND record_type='cleanup' AND id=aid;
  END IF;
  RETURN jsonb_build_object('result',true);
 END IF;
 IF kind IN ('start_deleting','settle_cleanup') THEN
  SELECT data INTO a FROM public.assistant_workflow_operations WHERE owner=o AND record_type='cleanup' AND id=aid FOR UPDATE;
  IF a IS NULL THEN RETURN jsonb_build_object('error','not_found'); END IF;
  IF a->>'state'='deleted' THEN RETURN jsonb_build_object('result',a||jsonb_build_object('owner',o)); END IF;
  IF (a->>'writer_pending')::boolean OR jsonb_array_length(a->'pending_writer_ids')>0 THEN
   RETURN jsonb_build_object('result',a||jsonb_build_object('owner',o,'state','pending','reason','upload_inflight')); END IF;
  IF kind='settle_cleanup' THEN
   IF proof.result IS DISTINCT FROM 'absent_after_delete' OR t.operation IS DISTINCT FROM 'delete'
   OR NOT EXISTS(SELECT 1 FROM public.assistant_original_deletions WHERE owner=o AND attachment_id=aid AND ticket_id=t.id) THEN
    RETURN jsonb_build_object('error','stale'); END IF;
   UPDATE public.assistant_original_deletions SET state='deleted' WHERE owner=o AND attachment_id=aid;
   a:=a||jsonb_build_object('state','deleted','reason','removed');
   UPDATE public.assistant_workflow_operations SET data=a WHERE owner=o AND record_type='cleanup' AND id=aid;
   RETURN jsonb_build_object('result',a||jsonb_build_object('owner',o));
  END IF;
  IF EXISTS(SELECT 1 FROM public.assistant_original_deletions WHERE owner=o AND attachment_id=aid) THEN
   RETURN jsonb_build_object('result',a||jsonb_build_object('owner',o,'state','pending','reason','operation_unknown')); END IF;
  -- Never lower recorded protection. Native references must be classified under
  -- this same fence before extending this check in I08/I11.
  IF a->'source_ref' IS NOT NULL AND a->'source_ref'<>'null'::jsonb OR a->>'state'='protected'
  OR EXISTS(SELECT 1 FROM public.assistant_workflow_tasks WHERE owner=o AND
   (data->'attachment_ids' @> jsonb_build_array(aid) OR data->'business_refs' @> jsonb_build_array(jsonb_build_object('kind','file','id',aid))))
  OR EXISTS(SELECT 1 FROM public.assistant_workflow_operations WHERE owner=o AND record_type='action' AND task_id=(a->>'task_id')::uuid
   AND coalesce(data->>'capability_id','') NOT IN ('gallery.photo.add','library.pdf.add')
   AND (data->>'state' IN ('pending','outcome_unknown') OR data->'business_ref'<>'null'::jsonb)) THEN
   a:=a||jsonb_build_object('state','protected','reason','reference_unresolved');
   UPDATE public.assistant_workflow_operations SET data=a WHERE owner=o AND record_type='cleanup' AND id=aid;
   RETURN jsonb_build_object('result',a||jsonb_build_object('owner',o)); END IF;
  SELECT * INTO t FROM public.assistant_storage_tickets WHERE owner=o AND attachment_id=aid AND operation='upload' ORDER BY generation DESC LIMIT 1;
  IF NOT FOUND THEN RETURN jsonb_build_object('result',a||jsonb_build_object('owner',o,'state','pending','reason','operation_unknown')); END IF;
  tid:=t.task_id; ticket_id:=gen_random_uuid();
  SELECT coalesce(max(s.generation),0)+1 INTO generation FROM public.assistant_storage_tickets s WHERE owner=o AND attachment_id=aid;
  INSERT INTO public.assistant_storage_tickets(owner,id,nonce,task_id,attachment_id,operation,generation,object_ref,
   expected_checksum,content_type,byte_size,expires_at,deleting)
  VALUES(o,ticket_id,gen_random_uuid(),tid,aid,'delete',generation,t.object_ref,t.expected_checksum,t.content_type,t.byte_size,
   clock_timestamp()+interval '45 seconds',true);
  INSERT INTO public.assistant_original_deletions(owner,attachment_id,task_id,ticket_id,state) VALUES(o,aid,tid,ticket_id,'deleting');
  RETURN jsonb_build_object('result',assistant_evidence.storage_ticket_projection(ticket_id));
 END IF;
 RETURN jsonb_build_object('error','invalid');
EXCEPTION WHEN serialization_failure THEN RETURN jsonb_build_object('error','stale');
 WHEN unique_violation THEN RETURN jsonb_build_object('error','duplicate');
 WHEN invalid_parameter_value OR invalid_text_representation OR check_violation OR not_null_violation THEN RETURN jsonb_build_object('error','invalid');
END $$;
ALTER FUNCTION public.assistant_original_command(jsonb) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_original_command(jsonb) FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;
GRANT EXECUTE ON FUNCTION public.assistant_original_command(jsonb) TO authenticated;
-- Operation-scoped storage gate. It observes existing reservations/claims only;
-- it cannot issue a ticket, release a writer or publish a cleanup assertion.
CREATE FUNCTION public.assistant_original_object_access(p_task uuid,p_attachment uuid,p_operation text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=auth.uid(); allowed boolean:=false; key text;
BEGIN
 IF o IS NULL OR auth.role() IS DISTINCT FROM 'authenticated' THEN
  RAISE EXCEPTION 'Verified patient required' USING ERRCODE='42501'; END IF;
 IF p_task IS NULL OR p_attachment IS NULL OR p_operation IS NULL OR p_operation NOT IN ('read','put','delete') THEN
  RAISE EXCEPTION 'Invalid original operation' USING ERRCODE='22023'; END IF;
 key:=o::text||'/workflow-originals/'||p_task::text||'/'||p_attachment::text;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 IF p_operation='read' THEN
  allowed:=EXISTS(SELECT 1 FROM public.assistant_workflow_attachments WHERE owner=o AND task_id=p_task AND id=p_attachment)
   OR EXISTS(SELECT 1 FROM public.assistant_workflow_operations WHERE owner=o AND task_id=p_task
    AND record_type='cleanup' AND id=p_attachment AND data->>'object_ref'=key);
 ELSIF p_operation='put' THEN
  allowed:=EXISTS(SELECT 1 FROM public.assistant_workflow_attachments a
   JOIN public.assistant_workflow_operations c ON c.owner=a.owner AND c.task_id=a.task_id AND c.id=a.task_id AND c.record_type='control'
   JOIN public.assistant_storage_tickets t ON t.owner=a.owner AND t.task_id=a.task_id AND t.attachment_id=a.id
   WHERE a.owner=o AND a.task_id=p_task AND a.id=p_attachment AND a.data->>'state'='reserved'
   AND c.data->>'mode'='allowed' AND c.data->>'revoked'='false' AND c.data->>'status'='idle'
   AND t.operation='upload' AND t.object_ref=key AND t.state='inflight' AND NOT t.revoked
   AND clock_timestamp()<t.expires_at)
   AND NOT EXISTS(SELECT 1 FROM public.assistant_original_deletions WHERE owner=o AND attachment_id=p_attachment);
 ELSE
  allowed:=EXISTS(SELECT 1 FROM public.assistant_original_deletions d
   JOIN public.assistant_storage_tickets t ON t.owner=d.owner AND t.id=d.ticket_id
   WHERE d.owner=o AND d.task_id=p_task AND d.attachment_id=p_attachment AND d.state='deleting'
   AND t.operation='delete' AND t.object_ref=key AND t.state='inflight' AND t.deleting)
   AND NOT EXISTS(SELECT 1 FROM public.assistant_storage_tickets WHERE owner=o AND object_ref=key
    AND operation='upload' AND state<>'settled');
 END IF;
 RETURN jsonb_build_object('allowed',allowed);
END $$;
ALTER FUNCTION public.assistant_original_object_access(uuid,uuid,text) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_original_object_access(uuid,uuid,text) FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;
GRANT EXECUTE ON FUNCTION public.assistant_original_object_access(uuid,uuid,text) TO authenticated;

COMMIT;
