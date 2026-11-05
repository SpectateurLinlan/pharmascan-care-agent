-- REVIEW ONLY / NOT APPLIED. I11 owner-copy/source bridge, after media-verification.
-- Owner-copy/source and native metadata transactions. Target gates block enablement.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';

CREATE TABLE public.assistant_media_generations(owner uuid PRIMARY KEY,revision bigint NOT NULL DEFAULT 0 CHECK(revision>=0));
CREATE TABLE public.assistant_media_commands (
 owner uuid NOT NULL,action_key uuid NOT NULL,task_id uuid NOT NULL,capability_id text NOT NULL,
 kind text NOT NULL,command_digest text NOT NULL CHECK(command_digest ~ '^[a-f0-9]{64}$'),
 prepared_ref jsonb NOT NULL,binding_revision integer NOT NULL CHECK(binding_revision>0),
 domain_revision bigint NOT NULL CHECK(domain_revision>=0),snapshot_hash text,native_hash text,duplicate boolean,
 PRIMARY KEY(owner,action_key),FOREIGN KEY(owner,action_key) REFERENCES public.assistant_business_receipts(owner,action_key) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE public.assistant_media_original_links (
 owner uuid NOT NULL,task_id uuid NOT NULL,attachment_id uuid NOT NULL,media_kind text NOT NULL CHECK(media_kind IN ('photo','pdf')),
 native_id uuid NOT NULL,action_key uuid NOT NULL,PRIMARY KEY(owner,attachment_id,media_kind,native_id),
 FOREIGN KEY(owner,action_key) REFERENCES public.assistant_business_receipts(owner,action_key) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE public.assistant_media_cleanup_settlements (
 owner uuid NOT NULL,action_key uuid NOT NULL,native_ref jsonb NOT NULL,reference jsonb NOT NULL,recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(owner,action_key),FOREIGN KEY(owner,action_key) REFERENCES public.assistant_business_receipts(owner,action_key)
);
DO $$ DECLARE relation_name text; BEGIN
 FOREACH relation_name IN ARRAY ARRAY['assistant_media_generations','assistant_media_commands','assistant_media_original_links','assistant_media_cleanup_settlements'] LOOP
  EXECUTE format('ALTER TABLE public.%I OWNER TO assistant_workflow_owner',relation_name);
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',relation_name);
  EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',relation_name);
  EXECUTE format('CREATE POLICY assistant_media_domain_owner ON public.%I TO assistant_workflow_owner USING(owner=public.assistant_patient_uid()) WITH CHECK(owner=public.assistant_patient_uid())',relation_name);
  EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner',relation_name);
 END LOOP;
END $$;
GRANT SELECT,INSERT,UPDATE ON public.medication_library_files TO assistant_workflow_owner;
CREATE POLICY assistant_media_library_owner ON public.medication_library_files TO assistant_workflow_owner
 USING(patient_id=public.assistant_patient_uid()) WITH CHECK(patient_id=public.assistant_patient_uid());
GRANT SELECT,INSERT ON public.medication_image_audit TO assistant_workflow_owner;
CREATE POLICY assistant_media_audit_owner ON public.medication_image_audit TO assistant_workflow_owner
 USING(patient_id=public.assistant_patient_uid()) WITH CHECK(patient_id=public.assistant_patient_uid());

CREATE FUNCTION public.assistant_original_verification_ref(p_task_id uuid,p_attachment_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=public.assistant_patient_uid();a jsonb;result jsonb;
BEGIN
 IF o IS NULL OR public.assistant_patient_role() IS DISTINCT FROM 'authenticated' THEN RAISE EXCEPTION 'Verified owner required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 SELECT data INTO a FROM public.assistant_workflow_attachments WHERE owner=o AND task_id=p_task_id AND id=p_attachment_id;
 IF a IS NULL OR a->>'state' IS DISTINCT FROM 'saved' OR a->'object_written' IS DISTINCT FROM 'true'::jsonb
 OR coalesce(a->'cleanup_pending','false')<>'false'::jsonb OR EXISTS(SELECT 1 FROM public.assistant_original_deletions
  WHERE owner=o AND attachment_id=p_attachment_id) THEN RETURN jsonb_build_object('error','stale'); END IF;
 SELECT jsonb_build_object('ticket_id',t.id,'verification_id',v.id,'generation',v.generation,'result',v.result) INTO result
 FROM public.assistant_storage_tickets t JOIN public.assistant_verified_operations v
 ON v.owner=t.owner AND v.ticket_id=t.id AND v.generation=t.generation
 WHERE t.owner=o AND t.task_id=p_task_id AND t.attachment_id=p_attachment_id AND t.operation='upload'
 AND NOT t.deleting AND NOT t.revoked AND v.result='bytes_verified' AND t.object_ref=a->>'object_ref'
 AND t.expected_checksum=a->>'original_checksum' AND v.checksum=t.expected_checksum
 AND v.byte_size=t.byte_size AND t.byte_size=(a->>'byte_size')::int ORDER BY t.generation DESC LIMIT 1;
 IF result IS NULL THEN RETURN jsonb_build_object('error','unavailable'); END IF;
 RETURN jsonb_build_object('result',result);
END $$;

CREATE FUNCTION public.assistant_media_copy_projection(p_id uuid) RETURNS jsonb
LANGUAGE sql SECURITY INVOKER SET search_path='' AS $$
 SELECT jsonb_build_object('ticket_id',id,'nonce',nonce,'task_id',task_id,'task_revision',task_revision,
 'capability_id',capability_id,'attachment_id',attachment_id,'writer_id',writer_id,'generation',generation,
 'source_checksum',source_checksum,'source_byte_size',source_byte_size,'target',target,'expires_at',expires_at)
 FROM public.assistant_media_copy_tickets WHERE owner=public.assistant_patient_uid() AND id=p_id
$$;

CREATE FUNCTION public.assistant_media_copy_current(p_owner uuid,p_ticket public.assistant_media_copy_tickets) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE t jsonb;ctl jsonb;a jsonb;proof jsonb;target jsonb:=p_ticket.target;
BEGIN
 IF p_owner IS DISTINCT FROM public.assistant_patient_uid() OR p_ticket.owner IS DISTINCT FROM p_owner THEN
  RAISE EXCEPTION 'Verified owned copy required' USING ERRCODE='42501'; END IF;
 SELECT data INTO t FROM public.assistant_workflow_tasks WHERE owner=p_owner AND id=p_ticket.task_id FOR UPDATE;
 SELECT data INTO ctl FROM public.assistant_workflow_operations WHERE owner=p_owner AND task_id=p_ticket.task_id
  AND id=p_ticket.task_id AND record_type='control' FOR UPDATE;
 IF t IS NULL OR ctl IS NULL OR (t->>'revision')::int IS DISTINCT FROM p_ticket.task_revision
 OR (ctl->>'revision')::int IS DISTINCT FROM p_ticket.task_revision OR t->>'capability_id' IS DISTINCT FROM p_ticket.capability_id
 OR ctl->>'capability_id' IS DISTINCT FROM p_ticket.capability_id OR t->>'save_mode' IS DISTINCT FROM 'allowed'
 OR ctl->>'mode' IS DISTINCT FROM 'allowed' OR ctl->'revoked' IS DISTINCT FROM 'false'::jsonb OR ctl->>'status' IS DISTINCT FROM 'idle'
 OR t->>'state' NOT IN ('collecting','ready_for_review','awaiting_confirmation')
 OR NOT(t->'attachment_ids' @> jsonb_build_array(p_ticket.attachment_id)) THEN
  RAISE EXCEPTION 'Current copy saving scope changed' USING ERRCODE='40001'; END IF;
 IF EXISTS(SELECT 1 FROM public.assistant_native_media_deletions d WHERE d.owner=p_owner
  AND d.bucket_id=p_ticket.bucket_id AND d.object_ref=p_ticket.object_ref) THEN
  RAISE EXCEPTION 'Native key is permanently deleting; no reuse' USING ERRCODE='40001'; END IF;
 proof:=public.assistant_original_verification_ref(p_ticket.task_id,p_ticket.attachment_id);
 IF proof ? 'error' THEN RAISE EXCEPTION 'Owned verified original unavailable' USING ERRCODE='40001'; END IF;
 SELECT data INTO a FROM public.assistant_workflow_attachments WHERE owner=p_owner AND task_id=p_ticket.task_id AND id=p_ticket.attachment_id;
 IF a->>'original_checksum' IS DISTINCT FROM p_ticket.source_checksum OR (a->>'byte_size')::int IS DISTINCT FROM p_ticket.source_byte_size THEN
  RAISE EXCEPTION 'Raw original changed' USING ERRCODE='40001'; END IF;
 IF target->>'media_kind'='source_image' THEN
  IF p_ticket.capability_id IS DISTINCT FROM 'medication.source.add' OR a->>'source_kind' IS DISTINCT FROM target->>'source_kind'
  OR a->>'extraction_status' IS DISTINCT FROM 'succeeded' THEN RAISE EXCEPTION 'Actual source normalization scope required' USING ERRCODE='40001'; END IF;
 ELSIF target->>'media_kind'='photo' THEN
  IF p_ticket.capability_id IS DISTINCT FROM 'gallery.photo.add' OR a->>'source_kind' IS DISTINCT FROM 'reference_photo' THEN
   RAISE EXCEPTION 'Actual reference photo scope required' USING ERRCODE='40001'; END IF;
 ELSE
  IF p_ticket.capability_id IS DISTINCT FROM 'library.pdf.add' OR a->>'source_kind' IS DISTINCT FROM 'library_pdf'
  OR a->>'content_type' IS DISTINCT FROM 'application/pdf' THEN RAISE EXCEPTION 'Actual store-only PDF scope required' USING ERRCODE='40001'; END IF;
 END IF;
 IF target->>'media_kind'<>'source_image' OR t->'fields'->>'medication_id' IS NOT NULL THEN
  IF t->'fields'->>'medication_id' IS DISTINCT FROM target->>'medication_id' OR NOT EXISTS(SELECT 1 FROM public.patient_medications
   WHERE patient_id=p_owner AND id=(target->>'medication_id')::uuid AND archived_at IS NULL) THEN
   RAISE EXCEPTION 'Actual current owned medication required' USING ERRCODE='40001'; END IF;
 END IF;
 RETURN a;
END $$;

CREATE FUNCTION public.assistant_media_copy_verified(p_owner uuid,p_reference jsonb) RETURNS public.assistant_media_copy_tickets
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE t public.assistant_media_copy_tickets%ROWTYPE;
BEGIN
 IF p_owner IS DISTINCT FROM public.assistant_patient_uid() OR NOT coalesce(public.assistant_wf_keys(p_reference,
 ARRAY['family','ticket_id','verification_id','generation','result']),false)
 OR p_reference->>'family' IS DISTINCT FROM 'native_media' THEN
  RAISE EXCEPTION 'Owned distinct native media proof required' USING ERRCODE='42501'; END IF;
 SELECT c.* INTO t FROM public.assistant_media_copy_tickets c JOIN public.assistant_media_copy_verifications v
 ON v.owner=c.owner AND v.ticket_id=c.id AND v.generation=c.generation WHERE c.owner=p_owner
 AND c.id=(p_reference->>'ticket_id')::uuid AND v.id=(p_reference->>'verification_id')::uuid
 AND v.generation=(p_reference->>'generation')::int AND v.result=p_reference->>'result';
 IF NOT FOUND THEN RAISE EXCEPTION 'Actual independently recorded native proof unavailable' USING ERRCODE='55000'; END IF;
 RETURN t;
END $$;

CREATE FUNCTION public.assistant_media_copy_command(p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=public.assistant_patient_uid();kind text:=p_command->>'kind';ctx jsonb:=p_command->'context';target jsonb:=p_command->'target';
 t public.assistant_media_copy_tickets%ROWTYPE;a jsonb;allowed text[];n integer;id uuid;run jsonb;recovered jsonb;
BEGIN
 IF o IS NULL OR public.assistant_patient_role() IS DISTINCT FROM 'authenticated' THEN RAISE EXCEPTION 'Verified patient required' USING ERRCODE='42501'; END IF;
 allowed:=CASE kind WHEN 'reserve' THEN ARRAY['kind','context','attachment_id','writer_id','target','run_binding']
 WHEN 'claim' THEN ARRAY['kind','ticket_id','nonce','generation'] WHEN 'read_verified' THEN ARRAY['kind','reference']
 WHEN 'assert_current' THEN ARRAY['kind','context','reference']
 WHEN 'recover' THEN ARRAY['kind','context','attachment_id','target'] END;
 IF allowed IS NULL OR NOT coalesce(public.assistant_wf_keys(p_command,allowed),false) OR octet_length(p_command::text)>6144 THEN
  RAISE EXCEPTION 'Closed native copy command required' USING ERRCODE='22023'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 IF kind='recover' THEN
  -- Read historical technical evidence only: no claim, native write or task CAS.
  IF NOT coalesce(public.assistant_wf_keys(ctx,ARRAY['owner','task_id','capability_id','revision','language','timezone','save_mode']),false)
  OR ctx->>'owner' IS DISTINCT FROM o::text OR ctx->>'save_mode' IS DISTINCT FROM 'allowed'
  OR jsonb_typeof(ctx->'revision') IS DISTINCT FROM 'number' OR ctx->>'revision' !~ '^[1-9][0-9]*$'
  OR NOT EXISTS(SELECT 1 FROM public.assistant_workflow_attachments a WHERE a.owner=o
   AND a.task_id=(ctx->>'task_id')::uuid AND a.id=(p_command->>'attachment_id')::uuid) THEN
   RAISE EXCEPTION 'Owned saved copy-recovery scope required' USING ERRCODE='40001'; END IF;
  SELECT jsonb_build_object('family','native_media','ticket_id',c.id,'verification_id',v.id,
    'generation',v.generation,'result',v.result) INTO recovered
  FROM public.assistant_media_copy_tickets c JOIN public.assistant_media_copy_verifications v
   ON v.owner=c.owner AND v.ticket_id=c.id AND v.generation=c.generation AND v.result='bytes_verified'
  WHERE c.owner=o AND c.task_id=(ctx->>'task_id')::uuid AND c.task_revision=(ctx->>'revision')::int
   AND c.capability_id=ctx->>'capability_id' AND c.attachment_id=(p_command->>'attachment_id')::uuid
   AND c.target=target ORDER BY c.generation LIMIT 1;
  IF recovered IS NOT NULL THEN RETURN jsonb_build_object('result',recovered); END IF;
  IF EXISTS(SELECT 1 FROM public.assistant_media_copy_tickets c WHERE c.owner=o
   AND c.task_id=(ctx->>'task_id')::uuid AND c.task_revision=(ctx->>'revision')::int
   AND c.capability_id=ctx->>'capability_id' AND c.attachment_id=(p_command->>'attachment_id')::uuid AND c.target=target) THEN
   RAISE EXCEPTION 'Unresolved native-copy writer cannot be repeated' USING ERRCODE='40001'; END IF;
  RETURN jsonb_build_object('result',null);
 END IF;
 IF kind IN ('read_verified','assert_current') THEN
  t:=public.assistant_media_copy_verified(o,p_command->'reference');
  IF kind='assert_current' THEN
   IF ctx->>'owner' IS DISTINCT FROM o::text OR ctx->>'task_id' IS DISTINCT FROM t.task_id::text
   OR (ctx->>'revision')::int IS DISTINCT FROM t.task_revision OR ctx->>'capability_id' IS DISTINCT FROM t.capability_id
   OR ctx->>'save_mode' IS DISTINCT FROM 'allowed' OR p_command->'reference'->>'result' IS DISTINCT FROM 'bytes_verified' THEN
    RAISE EXCEPTION 'Copy proof belongs to another current review' USING ERRCODE='40001'; END IF;
   PERFORM public.assistant_media_copy_current(o,t);
  END IF;
  RETURN jsonb_build_object('result',public.assistant_media_copy_projection(t.id));
 ELSIF kind='claim' THEN
  SELECT * INTO t FROM public.assistant_media_copy_tickets WHERE owner=o AND id=(p_command->>'ticket_id')::uuid FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Owned copy ticket unavailable' USING ERRCODE='P0002'; END IF;
  IF t.state<>'issued' OR clock_timestamp()>=t.expires_at OR t.nonce IS DISTINCT FROM (p_command->>'nonce')::uuid
  OR t.generation IS DISTINCT FROM (p_command->>'generation')::int THEN RAISE EXCEPTION 'Copy claim cannot be replayed' USING ERRCODE='40001'; END IF;
  IF t.run_binding IS NOT NULL THEN PERFORM public.assistant_run_assert_current(o,t.run_binding); END IF;
  PERFORM public.assistant_media_copy_current(o,t);
  UPDATE public.assistant_media_copy_tickets SET state='inflight' WHERE owner=o AND id=t.id;
  RETURN jsonb_build_object('result',true);
 END IF;
 IF NOT coalesce(public.assistant_wf_keys(ctx,ARRAY['owner','task_id','capability_id','revision','language','timezone','save_mode']),false)
 OR ctx->>'owner' IS DISTINCT FROM o::text OR ctx->>'save_mode' IS DISTINCT FROM 'allowed' THEN
  RAISE EXCEPTION 'Current owned context required' USING ERRCODE='40001'; END IF;
 SELECT data INTO a FROM public.assistant_workflow_attachments WHERE owner=o AND task_id=(ctx->>'task_id')::uuid
 AND id=(p_command->>'attachment_id')::uuid;
 IF a IS NULL THEN RAISE EXCEPTION 'Owned original unavailable' USING ERRCODE='P0002'; END IF;
 t.owner:=o;t.id:=gen_random_uuid();t.nonce:=gen_random_uuid();t.task_id:=(ctx->>'task_id')::uuid;
 t.task_revision:=(ctx->>'revision')::int;t.capability_id:=ctx->>'capability_id';t.attachment_id:=(p_command->>'attachment_id')::uuid;
 t.writer_id:=(p_command->>'writer_id')::uuid;t.source_checksum:=a->>'original_checksum';t.source_byte_size:=(a->>'byte_size')::int;
 t.target:=target;t.bucket_id:=CASE WHEN target->>'media_kind'='pdf' THEN 'medication-sources' ELSE 'visual-references' END;
 t.object_ref:=CASE WHEN target->>'media_kind'='pdf' THEN o::text||'/library/'||(target->>'medication_id')||'/'||(target->>'checksum')||'.pdf'
  ELSE o::text||'/'||(target->>'medication_id')||'/'||(target->>'checksum')||'.png' END;
 IF target->>'owner' IS DISTINCT FROM o::text OR (target->>'native_id')::uuid IS DISTINCT FROM (CASE WHEN target->>'media_kind'='pdf'
 THEN extensions.uuid_generate_v5(o,'medication-library-pdf:'||(target->>'medication_id')||':'||(target->>'checksum'))
 ELSE extensions.uuid_generate_v5((target->>'medication_id')::uuid,(target->>'checksum')||CASE WHEN target->>'media_kind'='source_image'
  THEN target->>'source_kind' ELSE '' END) END) THEN RAISE EXCEPTION 'Native copy identity differs from native policy' USING ERRCODE='22023'; END IF;
 PERFORM public.assistant_media_copy_current(o,t);
 run:=nullif(p_command->'run_binding','null'::jsonb);
 IF run IS NOT NULL THEN PERFORM public.assistant_run_assert_current(o,run); END IF;
 SELECT count(*) FILTER(WHERE state<>'settled'),coalesce(max(generation),0)+1 INTO n,t.generation
 FROM public.assistant_media_copy_tickets WHERE owner=o AND bucket_id=t.bucket_id AND object_ref=t.object_ref;
 IF n>=64 THEN RAISE EXCEPTION 'Unresolved copy writers need recovery' USING ERRCODE='40001'; END IF;
 t.expires_at:=clock_timestamp()+interval '45 seconds';t.state:='issued';t.run_binding:=run;
 INSERT INTO public.assistant_media_copy_tickets SELECT t.*;
 RETURN jsonb_build_object('result',public.assistant_media_copy_projection(t.id));
EXCEPTION WHEN SQLSTATE '40001' THEN RETURN jsonb_build_object('error','stale');
 WHEN unique_violation THEN RETURN jsonb_build_object('error','duplicate');
 WHEN SQLSTATE 'P0002' THEN RETURN jsonb_build_object('error','not_found');
 WHEN SQLSTATE '55000' THEN RETURN jsonb_build_object('error','unavailable');
 WHEN invalid_parameter_value OR invalid_text_representation OR check_violation OR not_null_violation THEN RETURN jsonb_build_object('error','invalid');
END $$;

CREATE FUNCTION public.assistant_native_image_assert_verified(p_owner uuid,p_image jsonb,p_reference jsonb,p_task uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE t public.assistant_media_copy_tickets%ROWTYPE;
BEGIN
 t:=public.assistant_media_copy_verified(p_owner,p_reference);
 IF p_reference->>'result' IS DISTINCT FROM 'bytes_verified' OR t.task_id IS DISTINCT FROM p_task
 OR t.capability_id IS DISTINCT FROM 'medication.source.add' OR t.target->>'media_kind' IS DISTINCT FROM 'source_image'
 OR t.target->>'owner' IS DISTINCT FROM p_owner::text OR t.target->>'native_id' IS DISTINCT FROM p_image->>'id'
 OR t.target->>'medication_id' IS DISTINCT FROM p_image->>'medication_id'
 OR t.target->>'source_kind' IS DISTINCT FROM p_image->>'source_description'
 OR t.target->>'checksum' IS DISTINCT FROM p_image->>'checksum' OR t.object_ref IS DISTINCT FROM p_image->>'storage_path'
 OR t.bucket_id<>'visual-references' OR p_image->>'patient_id' IS DISTINCT FROM p_owner::text THEN
  RAISE EXCEPTION 'Source image proof differs from the current native proposal' USING ERRCODE='40001'; END IF;
 PERFORM public.assistant_media_copy_current(p_owner,t);
 RETURN true;
END $$;

CREATE FUNCTION public.assistant_media_epoch_changed() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=CASE WHEN TG_OP='DELETE' THEN OLD.patient_id ELSE NEW.patient_id END;
BEGIN
 IF o IS DISTINCT FROM public.assistant_patient_uid() THEN RAISE EXCEPTION 'Owned media epoch required' USING ERRCODE='42501'; END IF;
 INSERT INTO public.assistant_media_generations(owner,revision) VALUES(o,1)
 ON CONFLICT(owner) DO UPDATE SET revision=public.assistant_media_generations.revision+1;
 RETURN NULL;
END $$;
CREATE TRIGGER assistant_media_epoch AFTER INSERT OR UPDATE OR DELETE ON public.medication_images
 FOR EACH ROW EXECUTE FUNCTION public.assistant_media_epoch_changed();
CREATE TRIGGER assistant_media_epoch AFTER INSERT OR UPDATE OR DELETE ON public.medication_library_files
 FOR EACH ROW EXECUTE FUNCTION public.assistant_media_epoch_changed();
CREATE TRIGGER assistant_media_owner_first BEFORE INSERT OR UPDATE OR DELETE ON public.medication_library_files
 FOR EACH STATEMENT EXECUTE FUNCTION public.assistant_medication_owner_fence();

CREATE FUNCTION public.assistant_media_revision() RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=public.assistant_patient_uid();n bigint;
BEGIN
 IF o IS NULL OR public.assistant_patient_role() IS DISTINCT FROM 'authenticated' THEN RAISE EXCEPTION 'Verified patient required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 SELECT coalesce((SELECT g.revision FROM public.assistant_media_generations g WHERE g.owner=o),0)
 +coalesce((SELECT g.revision FROM public.assistant_enrollment_generations g WHERE g.owner=o),0) INTO n;
 RETURN jsonb_build_object('revision',n);
END $$;

CREATE FUNCTION public.assistant_media_native(p_owner uuid,p_photo boolean,p_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE result jsonb;
BEGIN
 IF p_owner IS DISTINCT FROM public.assistant_patient_uid() THEN RAISE EXCEPTION 'Owned media required' USING ERRCODE='42501'; END IF;
 IF p_photo THEN
  SELECT jsonb_build_object('metadata_version',1,'gallery_removed',false,'deleted_at',NULL,'cleanup_pending',false,'source_id',NULL)
  ||i.data||jsonb_build_object('id',i.id,'patient_id',i.patient_id,'medication_id',i.medication_id,'source_id',i.source_id) INTO result
  FROM public.medication_images i WHERE i.patient_id=p_owner AND i.id=p_id;
 ELSE SELECT to_jsonb(f) INTO result FROM public.medication_library_files f WHERE f.patient_id=p_owner AND f.id=p_id; END IF;
 IF result IS NULL THEN RAISE EXCEPTION 'Owned native media unavailable' USING ERRCODE='P0002'; END IF;
 RETURN result;
END $$;

CREATE FUNCTION public.assistant_media_expected(p_cap text,p_fields jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE SECURITY INVOKER SET search_path='' AS $$
DECLARE defaults jsonb;allowed text[];
BEGIN
 defaults:=jsonb_build_object('medication_id',NULL,'page',0);
 IF p_cap='gallery.photo.add' THEN
  defaults:=defaults||jsonb_build_object('source_attachment_id',NULL,'image_kind',NULL,'source_description',NULL);
 ELSIF p_cap='library.pdf.add' THEN
  defaults:=defaults||jsonb_build_object('source_attachment_id',NULL,'filename',NULL,'category',NULL,'description','');
 ELSIF p_cap IN ('gallery.photo.edit','gallery.photo.remove','gallery.photo.delete','gallery.photo.retire') THEN
  defaults:=defaults||jsonb_build_object('expected_version',NULL,'image_id',NULL,'image_kind',NULL,'source_description',NULL);
 ELSIF p_cap IN ('library.pdf.edit','library.pdf.delete') THEN
  defaults:=defaults||jsonb_build_object('expected_version',NULL,'file_id',NULL,'title',NULL,'category',NULL,'description',NULL);
 ELSE RAISE EXCEPTION 'Closed media capability required' USING ERRCODE='22023'; END IF;
 SELECT array_agg(key) INTO allowed FROM jsonb_object_keys(defaults) key;
 IF NOT coalesce(public.assistant_wf_keys(p_fields,allowed),false) THEN RAISE EXCEPTION 'Unknown media fields' USING ERRCODE='22023'; END IF;
 RETURN defaults||p_fields;
END $$;

CREATE FUNCTION public.assistant_media_selection(p_owner uuid,p_task jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE cap text:=p_task->>'capability_id';f jsonb:=public.assistant_media_expected(cap,p_task->'fields');row_json jsonb;a jsonb;
BEGIN
 IF f->>'medication_id' IS NULL OR NOT EXISTS(SELECT 1 FROM public.patient_medications WHERE patient_id=p_owner AND id=(f->>'medication_id')::uuid) THEN
  RAISE EXCEPTION 'Owned selected medication required' USING ERRCODE='40001'; END IF;
 IF cap IN ('gallery.photo.add','library.pdf.add') THEN
  IF f->>'source_attachment_id' IS NULL OR NOT(p_task->'attachment_ids' @> jsonb_build_array(f->'source_attachment_id')) THEN
   RAISE EXCEPTION 'Select the saved original in this task' USING ERRCODE='40001'; END IF;
  row_json:=public.assistant_original_verification_ref((p_task->>'id')::uuid,(f->>'source_attachment_id')::uuid);
  IF row_json ? 'error' THEN RAISE EXCEPTION 'Verified original unavailable' USING ERRCODE='40001'; END IF;
  SELECT data INTO a FROM public.assistant_workflow_attachments WHERE owner=p_owner AND task_id=(p_task->>'id')::uuid AND id=(f->>'source_attachment_id')::uuid;
  IF (cap='gallery.photo.add' AND (a->>'source_kind' IS DISTINCT FROM 'reference_photo' OR f->>'image_kind' IS NULL OR f->>'image_kind' NOT IN ('loose_pill','package','blister','source')
    OR nullif(btrim(f->>'source_description'),'') IS NULL OR length(f->>'source_description')>200))
  OR (cap='library.pdf.add' AND (a->>'source_kind' IS DISTINCT FROM 'library_pdf' OR nullif(f->>'filename','') IS NULL
    OR length(f->>'filename')>240 OR f->>'filename' !~* '\.pdf$' OR f->>'filename' ~ '[/\\<>:"|?*[:cntrl:]]'
    OR f->>'category' IS NULL OR f->>'category' NOT IN ('prescription','pharmacy_document','medication_instructions','other'))) THEN
   RAISE EXCEPTION 'Complete the current typed upload draft' USING ERRCODE='22023'; END IF;
  RETURN jsonb_build_object('attachment_id',f->'source_attachment_id','checksum',a->'original_checksum');
 END IF;
 IF jsonb_array_length(p_task->'attachment_ids')<>0 THEN RAISE EXCEPTION 'Lifecycle selection does not accept upload assets' USING ERRCODE='22023'; END IF;
 row_json:=public.assistant_media_native(p_owner,cap LIKE 'gallery.%',coalesce((f->>'image_id')::uuid,(f->>'file_id')::uuid));
 IF row_json->>'medication_id' IS DISTINCT FROM f->>'medication_id' OR row_json->>'deleted_at' IS NOT NULL
 OR coalesce((row_json->>'metadata_version')::int,(row_json->>'version')::int) IS DISTINCT FROM (f->>'expected_version')::int
 OR (cap LIKE 'gallery.%' AND row_json->'gallery_removed'='true'::jsonb)
 OR (cap IN ('gallery.photo.remove','gallery.photo.delete') AND row_json->>'source_id' IS NOT NULL)
 OR (cap='library.pdf.delete' AND (row_json->>'source_document_id' IS NOT NULL OR row_json->>'regimen_version_id' IS NOT NULL)) THEN
  RAISE EXCEPTION 'Current owned media version/protection changed' USING ERRCODE='40001'; END IF;
 IF (cap='gallery.photo.edit' AND (f->>'image_kind' IS NULL OR f->>'image_kind' NOT IN ('loose_pill','package','blister','source') OR nullif(btrim(f->>'source_description'),'') IS NULL OR length(f->>'source_description')>200))
 OR (cap='library.pdf.edit' AND (nullif(btrim(f->>'title'),'') IS NULL OR length(f->>'title')>160 OR f->>'category' IS NULL OR f->>'category' NOT IN ('prescription','pharmacy_document','medication_instructions','other') OR f->>'description' IS NULL OR length(f->>'description')>500)) THEN
  RAISE EXCEPTION 'Complete the typed metadata edit' USING ERRCODE='22023'; END IF;
 RETURN row_json;
END $$;

CREATE FUNCTION public.assistant_media_filename(p_name text) RETURNS text
LANGUAGE plpgsql IMMUTABLE SECURITY INVOKER SET search_path='' AS $$
DECLARE name text;
BEGIN
 IF p_name IS NULL OR length(p_name)>240 OR p_name !~* '\.pdf$' OR p_name ~ '[/\\<>:"|?*[:cntrl:]]' THEN
  RAISE EXCEPTION 'Owned PDF leaf filename required' USING ERRCODE='22023'; END IF;
 name:=btrim(regexp_replace(p_name,'^[[:space:]]+|[[:space:]]+$','','g'),'.');
 IF length(name)<5 OR name !~* '\.pdf$' THEN RAISE EXCEPTION 'PDF filename required' USING ERRCODE='22023'; END IF;
 RETURN left(name,length(name)-4)||'.pdf';
END $$;

CREATE FUNCTION public.assistant_media_result(p_owner uuid,p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE c public.assistant_media_commands%ROWTYPE;r jsonb;row_json jsonb;hashed jsonb;ref jsonb;
BEGIN
 SELECT * INTO STRICT c FROM public.assistant_media_commands WHERE owner=p_owner AND action_key=(p_command->'binding'->>'action_key')::uuid;
 SELECT to_jsonb(x) INTO STRICT r FROM public.assistant_business_receipts x WHERE owner=p_owner AND action_key=c.action_key;
 IF c.kind='prepare_media' THEN RETURN jsonb_build_object('receipt',r,'result',NULL); END IF;
 ref:=r->'business_ref';row_json:=public.assistant_media_native(p_owner,c.capability_id LIKE 'gallery.%',(ref->>'id')::uuid);
 hashed:=CASE WHEN c.kind IN ('delete_photo','tombstone_pdf') THEN row_json-'cleanup_pending' ELSE row_json END;
 IF c.native_hash IS DISTINCT FROM encode(sha256(convert_to(hashed::text,'UTF8')),'hex') THEN
  RAISE EXCEPTION 'Actual media changed; retain historical receipt' USING ERRCODE='40001'; END IF;
 IF c.kind IN ('register_photo','register_pdf') THEN
  row_json:=jsonb_build_object(CASE c.kind WHEN 'register_photo' THEN 'photo' ELSE 'file' END,row_json,'duplicate',c.duplicate); END IF;
 RETURN jsonb_build_object('receipt',r,'result',row_json);
END $$;

CREATE FUNCTION public.assistant_media_apply(p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE o uuid:=public.assistant_patient_uid();b jsonb:=p_command->'binding';kind text:=p_command->>'kind';cap text:=b->>'capability_id';
 preparing boolean:=kind='prepare_media';registering boolean:=kind IN ('register_photo','register_pdf');
 tid uuid:=(b->>'task_id')::uuid;aid uuid:=(b->>'action_key')::uuid;rev int:=(b->>'task_revision')::int;ref jsonb:=b->'prepared_ref';
 t jsonb;ctl jsonb;f jsonb;native jsonb;selection jsonb;snapshot text;digest text;generation bigint;child jsonb;outref jsonb;allowed text[];
 prior public.assistant_media_commands%ROWTYPE;prep public.assistant_media_commands%ROWTYPE;copy_ticket public.assistant_media_copy_tickets%ROWTYPE;
 duplicate boolean:=false;version int;target uuid;fields jsonb;a jsonb;path text;
BEGIN
 IF o IS NULL OR public.assistant_patient_role() IS DISTINCT FROM 'authenticated' THEN RAISE EXCEPTION 'Verified owner required' USING ERRCODE='42501'; END IF;
 allowed:=CASE WHEN preparing THEN ARRAY['kind','binding'] WHEN registering THEN ARRAY['kind','binding','values','confirmed','copy_proof']
 ELSE ARRAY['kind','binding','values','confirmed'] END;
 IF kind='register_photo' THEN allowed:=allowed||ARRAY['reviewed','processing_consent']; END IF;
 IF NOT coalesce(public.assistant_wf_keys(p_command,allowed),false) OR octet_length(p_command::text)>8192
 OR NOT coalesce(public.assistant_wf_keys(b,ARRAY['task_id','task_revision','capability_id','action_key','prepared_ref','expected_domain_revision','run_binding']),false)
 OR NOT coalesce(public.assistant_wf_keys(ref,ARRAY['kind','id','version']),false)
 OR tid IS NULL OR aid IS NULL OR rev IS NULL OR rev<1 OR (NOT preparing AND p_command->'confirmed' IS DISTINCT FROM 'true'::jsonb)
 OR (kind='register_photo' AND (p_command->'reviewed' IS DISTINCT FROM 'true'::jsonb OR p_command->'processing_consent' IS DISTINCT FROM 'true'::jsonb)) THEN
  RAISE EXCEPTION 'Closed independently confirmed media command required' USING ERRCODE='22023'; END IF;
 digest:=encode(sha256(convert_to(p_command::text,'UTF8')),'hex');
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 SELECT data INTO t FROM public.assistant_workflow_tasks WHERE owner=o AND id=tid FOR UPDATE;
 SELECT data INTO ctl FROM public.assistant_workflow_operations WHERE owner=o AND task_id=tid AND id=tid AND record_type='control' FOR UPDATE;
 SELECT * INTO prior FROM public.assistant_media_commands WHERE owner=o AND action_key=aid;
 IF FOUND THEN
  IF prior.command_digest IS DISTINCT FROM digest THEN RAISE EXCEPTION 'Media action reused' USING ERRCODE='23505'; END IF;
  RETURN jsonb_build_object('result',public.assistant_media_result(o,p_command),'replayed',true); END IF;
 IF EXISTS(SELECT 1 FROM public.assistant_business_receipts WHERE owner=o AND action_key=aid) THEN RAISE EXCEPTION 'Action belongs to another boundary' USING ERRCODE='23505'; END IF;
 generation:=(public.assistant_media_revision()->>'revision')::bigint;
 IF t IS NULL OR ctl IS NULL OR t->>'capability_id' IS DISTINCT FROM cap OR ctl->>'capability_id' IS DISTINCT FROM cap
 OR (t->>'revision')::int IS DISTINCT FROM rev OR (ctl->>'revision')::int IS DISTINCT FROM rev
 OR t->>'save_mode' IS DISTINCT FROM 'allowed' OR ctl->>'mode' IS DISTINCT FROM 'allowed'
 OR ctl->'revoked' IS DISTINCT FROM 'false'::jsonb OR ctl->>'status' IS DISTINCT FROM 'idle'
 OR generation IS DISTINCT FROM (b->>'expected_domain_revision')::bigint OR ref->>'kind' IS DISTINCT FROM 'media_review' OR ref->'version' IS DISTINCT FROM '1'::jsonb THEN
  RAISE EXCEPTION 'Current saved media review changed' USING ERRCODE='40001'; END IF;
 IF nullif(b->'run_binding','null'::jsonb) IS NOT NULL THEN PERFORM public.assistant_run_assert_current(o,b->'run_binding'); END IF;
 fields:=t->'fields';
 IF preparing AND cap IN ('gallery.photo.add','library.pdf.add') AND fields->>'source_attachment_id' IS NULL AND jsonb_array_length(t->'attachment_ids')=1 THEN
  fields:=fields||jsonb_build_object('source_attachment_id',t->'attachment_ids'->0);t:=jsonb_set(t,'{fields}',fields); END IF;
 f:=public.assistant_media_expected(cap,fields);selection:=public.assistant_media_selection(o,t);
 snapshot:=encode(sha256(convert_to(selection::text,'UTF8')),'hex');
 IF preparing THEN
  IF ref->>'id' IS DISTINCT FROM aid::text THEN RAISE EXCEPTION 'Owned technical marker required' USING ERRCODE='22023'; END IF;
  SELECT * INTO prep FROM public.assistant_media_commands c WHERE c.owner=o AND c.task_id=tid AND c.kind='prepare_media' AND c.prepared_ref=t->'business_refs'->0;
  IF NOT(t->>'state'='ready_for_review' OR (cap IN ('gallery.photo.add','library.pdf.add') AND t->>'state'='collecting')
   OR (t->>'state'='awaiting_confirmation' AND jsonb_array_length(t->'business_refs')=1 AND prep.owner IS NOT NULL
    AND (prep.binding_revision<rev OR prep.domain_revision<>generation OR prep.snapshot_hash IS DISTINCT FROM snapshot))) THEN
   RAISE EXCEPTION 'Prepare a fresh owned selection' USING ERRCODE='40001'; END IF;
  INSERT INTO public.assistant_workflow_operations(owner,record_type,id,task_id,data) VALUES(o,'action',aid,tid,jsonb_build_object(
   'action_key',aid,'task_id',tid,'capability_id',cap,'binding_revision',rev,'state','pending','business_ref',ref,'safe_reason','media_prepared','updated_at',clock_timestamp()));
  outref:=ref;native:='null';
 ELSE
  IF t->>'state' IS DISTINCT FROM 'awaiting_confirmation' OR NOT(t->'business_refs' @> jsonb_build_array(ref)) OR p_command->'values' IS DISTINCT FROM f
  OR kind IS DISTINCT FROM (CASE cap WHEN 'gallery.photo.add' THEN 'register_photo' WHEN 'library.pdf.add' THEN 'register_pdf'
   WHEN 'gallery.photo.edit' THEN 'edit_photo' WHEN 'gallery.photo.remove' THEN 'remove_photo' WHEN 'gallery.photo.delete' THEN 'delete_photo'
   WHEN 'gallery.photo.retire' THEN 'retire_photo' WHEN 'library.pdf.edit' THEN 'edit_pdf' WHEN 'library.pdf.delete' THEN 'tombstone_pdf' END) THEN
   RAISE EXCEPTION 'Native action differs from the independent patient review' USING ERRCODE='40001'; END IF;
  SELECT * INTO prep FROM public.assistant_media_commands c WHERE c.owner=o AND c.task_id=tid AND c.kind='prepare_media' AND c.prepared_ref=ref;
  IF prep.owner IS NULL OR prep.binding_revision<>rev OR prep.capability_id<>cap OR prep.domain_revision<>generation OR prep.snapshot_hash IS DISTINCT FROM snapshot THEN
   RAISE EXCEPTION 'Media preparation is stale' USING ERRCODE='40001'; END IF;
  IF registering THEN
   copy_ticket:=public.assistant_media_copy_verified(o,p_command->'copy_proof');PERFORM public.assistant_media_copy_current(o,copy_ticket);
   IF p_command->'copy_proof'->>'result' IS DISTINCT FROM 'bytes_verified' OR copy_ticket.task_id<>tid OR copy_ticket.task_revision<>rev
   OR copy_ticket.capability_id<>cap OR copy_ticket.attachment_id IS DISTINCT FROM (f->>'source_attachment_id')::uuid
   OR copy_ticket.target->>'medication_id' IS DISTINCT FROM f->>'medication_id'
   OR copy_ticket.target->>'media_kind' IS DISTINCT FROM (CASE kind WHEN 'register_photo' THEN 'photo' ELSE 'pdf' END) THEN
    RAISE EXCEPTION 'Actual independent copy differs from this original/medication' USING ERRCODE='40001'; END IF;
   IF kind='register_photo' THEN
    SELECT public.assistant_media_native(o,true,i.id) INTO native FROM public.medication_images i WHERE i.patient_id=o
     AND i.medication_id=(f->>'medication_id')::uuid AND i.data->>'checksum'=copy_ticket.target->>'checksum' ORDER BY i.id LIMIT 1;
    duplicate:=native IS NOT NULL;
    IF NOT duplicate THEN
     native:=jsonb_build_object('id',copy_ticket.target->'native_id','patient_id',o,'medication_id',f->'medication_id','image_kind',f->'image_kind',
      'storage_path',copy_ticket.object_ref,'checksum',copy_ticket.target->'checksum','source_description',f->'source_description','source_id',NULL,
      'reviewed',true,'eligibility','associated','eligibility_reason',CASE WHEN f->>'image_kind'='loose_pill'
       THEN 'image_content_not_independently_validated_comparison_disabled' ELSE 'automatic_loose_pill_matching_not_available_for_this_image_type' END,
      'created_at',clock_timestamp(),'metadata_version',1,'gallery_removed',false,'deleted_at',NULL,'cleanup_pending',false);
     INSERT INTO public.medication_images(id,patient_id,medication_id,data,version) VALUES((native->>'id')::uuid,o,(f->>'medication_id')::uuid,native,1);
    END IF;
   ELSE
    SELECT to_jsonb(x) INTO native FROM public.medication_library_files x WHERE patient_id=o AND medication_id=(f->>'medication_id')::uuid AND checksum=copy_ticket.target->>'checksum';
    duplicate:=native IS NOT NULL;
    IF NOT duplicate THEN
     child:=public.register_medication_library_pdf(jsonb_build_object('id',copy_ticket.target->'native_id','patient_id',o,'medication_id',f->'medication_id',
      'storage_path',copy_ticket.object_ref,'checksum',copy_ticket.target->'checksum','original_filename',public.assistant_media_filename(f->>'filename'),
      'display_title',left(left(public.assistant_media_filename(f->>'filename'),length(public.assistant_media_filename(f->>'filename'))-4),160),
      'category',f->'category','description',btrim(coalesce(f->>'description','')),'content_type','application/pdf','byte_size',copy_ticket.target->'byte_size'));
     native:=child->'file';duplicate:=(child->>'duplicate')::boolean;
    END IF;
   END IF;
   IF native->>'deleted_at' IS NOT NULL OR native->'gallery_removed'='true'::jsonb OR native->>'storage_path' IS DISTINCT FROM copy_ticket.object_ref THEN
    RAISE EXCEPTION 'This native file was removed or differs from the verified key' USING ERRCODE='40001'; END IF;
  ELSE
   target:=(selection->>'id')::uuid;version:=(f->>'expected_version')::int;
   IF kind='retire_photo' THEN
    native:=selection;
    IF native->>'eligibility' IS DISTINCT FROM 'ineligible' OR native->>'eligibility_reason' IS DISTINCT FROM 'patient_retired_reference' THEN
     native:=native||jsonb_build_object('eligibility','ineligible','eligibility_reason','patient_retired_reference','metadata_version',version+1);
     UPDATE public.medication_images SET data=native,version=version+1 WHERE patient_id=o AND id=target;
     INSERT INTO public.medication_image_audit(patient_id,image_id,action,before_values,after_values,actor_id)
      VALUES(o,target,'stopped_comparison',jsonb_build_object('eligibility',selection->'eligibility','eligibility_reason',selection->'eligibility_reason'),
       jsonb_build_object('eligibility','ineligible','eligibility_reason','patient_retired_reference'),o);
    END IF;
   ELSIF kind IN ('edit_photo','remove_photo','delete_photo') THEN
    child:=public.manage_personal_gallery_image(target,CASE kind WHEN 'edit_photo' THEN 'edit' WHEN 'remove_photo' THEN 'remove' ELSE 'delete' END,
      version,f->>'image_kind',f->>'source_description',true);native:=child->'image';
   ELSIF kind='edit_pdf' THEN native:=to_jsonb(public.update_medication_library_pdf(target,version,f->>'title',f->>'category',btrim(f->>'description')));
   ELSE child:=public.tombstone_medication_library_pdf(target,true);native:=public.assistant_media_native(o,false,target); END IF;
  END IF;
  native:=public.assistant_media_native(o,cap LIKE 'gallery.%',(native->>'id')::uuid);
  outref:=jsonb_build_object('kind','file','id',native->'id','version',coalesce(native->'metadata_version',native->'version'));
 END IF;
 IF nullif(b->'run_binding','null'::jsonb) IS NOT NULL THEN PERFORM public.assistant_run_assert_current(o,b->'run_binding'); END IF;
 child:=public.assistant_workflow_command_legacy_035('task_cas',jsonb_build_object('task_id',tid,'expected_revision',rev,'event_id',aid,'request_digest',digest,
  'update',jsonb_build_object('state',CASE WHEN preparing THEN 'awaiting_confirmation' WHEN native->'cleanup_pending'='true'::jsonb THEN 'outcome_unknown' ELSE 'completed' END,
   'save_mode','allowed','storage_state',CASE WHEN native->'cleanup_pending'='true'::jsonb THEN 'cleanup_pending' ELSE 'saved' END,
   'fields',fields,'missing_fields','[]'::jsonb,'attachment_ids',t->'attachment_ids','business_refs',jsonb_build_array(outref))));
 IF child ? 'error' THEN RAISE EXCEPTION 'Task changed after native media publication' USING ERRCODE='40001'; END IF;
 generation:=(public.assistant_media_revision()->>'revision')::bigint;
 INSERT INTO public.assistant_business_receipts(owner,action_key,task_id,capability_id,binding_revision,business_ref,domain_revision,outcome)
 VALUES(o,aid,tid,cap,rev+1,outref,generation,CASE WHEN preparing THEN 'prepared' ELSE 'applied' END);
 INSERT INTO public.assistant_media_commands(owner,action_key,task_id,capability_id,kind,command_digest,prepared_ref,binding_revision,domain_revision,snapshot_hash,native_hash,duplicate)
 VALUES(o,aid,tid,cap,kind,digest,ref,rev+1,generation,CASE WHEN preparing THEN snapshot END,
  CASE WHEN NOT preparing THEN encode(sha256(convert_to((CASE WHEN kind IN ('delete_photo','tombstone_pdf') THEN native-'cleanup_pending' ELSE native END)::text,'UTF8')),'hex') END,duplicate);
 IF registering THEN
  INSERT INTO public.assistant_media_original_links(owner,task_id,attachment_id,media_kind,native_id,action_key)
  VALUES(o,tid,(f->>'source_attachment_id')::uuid,copy_ticket.target->>'media_kind',(native->>'id')::uuid,aid) ON CONFLICT DO NOTHING;
  UPDATE public.assistant_workflow_attachments SET data=data||jsonb_build_object('source_ref',outref) WHERE owner=o AND task_id=tid AND id=(f->>'source_attachment_id')::uuid
   AND (data->'source_ref' IS NULL OR data->'source_ref'='null'::jsonb);
 END IF;
 RETURN jsonb_build_object('result',public.assistant_media_result(o,p_command),'replayed',false);
END $$;

CREATE FUNCTION public.assistant_media_prepare(p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF p_command->>'kind' IS DISTINCT FROM 'prepare_media' THEN RETURN jsonb_build_object('error','invalid'); END IF;
 RETURN public.assistant_media_apply(p_command);
EXCEPTION WHEN SQLSTATE '40001' THEN RETURN jsonb_build_object('error','stale'); WHEN unique_violation THEN RETURN jsonb_build_object('error','duplicate');
 WHEN SQLSTATE 'P0002' THEN RETURN jsonb_build_object('error','not_found'); WHEN invalid_parameter_value OR invalid_text_representation OR check_violation OR not_null_violation THEN RETURN jsonb_build_object('error','invalid'); END $$;
CREATE FUNCTION public.assistant_media_write(p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF p_command->>'kind' IS NOT DISTINCT FROM 'prepare_media' THEN RETURN jsonb_build_object('error','invalid'); END IF;
 RETURN public.assistant_media_apply(p_command);
EXCEPTION WHEN SQLSTATE '40001' THEN RETURN jsonb_build_object('error','stale'); WHEN unique_violation THEN RETURN jsonb_build_object('error','duplicate');
 WHEN SQLSTATE 'P0002' THEN RETURN jsonb_build_object('error','not_found'); WHEN invalid_parameter_value OR invalid_text_representation OR check_violation OR not_null_violation THEN RETURN jsonb_build_object('error','invalid'); END $$;
CREATE FUNCTION public.assistant_media_read(p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=public.assistant_patient_uid();c public.assistant_media_commands%ROWTYPE;
BEGIN
 IF o IS NULL OR public.assistant_patient_role() IS DISTINCT FROM 'authenticated' THEN RAISE EXCEPTION 'Verified owner required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 SELECT * INTO c FROM public.assistant_media_commands WHERE owner=o AND action_key=(p_command->'binding'->>'action_key')::uuid;
 IF NOT FOUND THEN RETURN jsonb_build_object('error','not_found'); END IF;
 IF c.command_digest IS DISTINCT FROM encode(sha256(convert_to(p_command::text,'UTF8')),'hex') THEN RETURN jsonb_build_object('error','duplicate'); END IF;
 RETURN jsonb_build_object('result',public.assistant_media_result(o,p_command),'replayed',true);
EXCEPTION WHEN SQLSTATE '40001' THEN RETURN jsonb_build_object('error','stale'); WHEN SQLSTATE 'P0002' THEN RETURN jsonb_build_object('error','stale'); END $$;

-- Owner fence precedes the original RPC's first native row lock. Retain native
-- argument/default/return contracts, policy, audits and unbound retirement no-op.
ALTER FUNCTION public.register_medication_library_pdf(jsonb) RENAME TO assistant_media_pdf_register_legacy_031;
ALTER FUNCTION public.update_medication_library_pdf(uuid,integer,text,text,text) RENAME TO assistant_media_pdf_update_legacy_031;
ALTER FUNCTION public.tombstone_medication_library_pdf(uuid,boolean) RENAME TO assistant_media_pdf_delete_legacy_031;
ALTER FUNCTION public.manage_personal_gallery_image(uuid,text,integer,text,text,boolean) RENAME TO assistant_media_photo_manage_legacy_031;
ALTER FUNCTION public.retire_personal_reference(uuid) RENAME TO assistant_media_photo_retire_legacy_031;
DO $$ DECLARE signature text; BEGIN
 FOREACH signature IN ARRAY ARRAY['assistant_media_pdf_register_legacy_031(jsonb)','assistant_media_pdf_update_legacy_031(uuid,integer,text,text,text)',
 'assistant_media_pdf_delete_legacy_031(uuid,boolean)','assistant_media_photo_manage_legacy_031(uuid,text,integer,text,text,boolean)','assistant_media_photo_retire_legacy_031(uuid)'] LOOP
  EXECUTE 'REVOKE ALL ON FUNCTION public.'||signature||' FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner';
  EXECUTE 'GRANT EXECUTE ON FUNCTION public.'||signature||' TO assistant_workflow_owner';
 END LOOP;
END $$;
CREATE FUNCTION public.assistant_media_owner_fence() RETURNS void
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
BEGIN
 IF public.assistant_patient_uid() IS NULL OR public.assistant_patient_role() IS DISTINCT FROM 'authenticated' THEN RAISE EXCEPTION 'Verified owner required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(public.assistant_patient_uid()::text,35035));
END $$;
CREATE FUNCTION public.register_medication_library_pdf(p_file jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN PERFORM public.assistant_media_owner_fence();RETURN public.assistant_media_pdf_register_legacy_031(p_file); END $$;
CREATE FUNCTION public.update_medication_library_pdf(p_id uuid,p_expected_version integer,p_title text,p_category text,p_description text) RETURNS public.medication_library_files
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN PERFORM public.assistant_media_owner_fence();RETURN public.assistant_media_pdf_update_legacy_031(p_id,p_expected_version,p_title,p_category,p_description); END $$;
CREATE FUNCTION public.tombstone_medication_library_pdf(p_id uuid,p_confirmed boolean) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN PERFORM public.assistant_media_owner_fence();RETURN public.assistant_media_pdf_delete_legacy_031(p_id,p_confirmed); END $$;
CREATE FUNCTION public.manage_personal_gallery_image(p_image_id uuid,p_action text,p_expected_version integer,
 p_image_kind text DEFAULT NULL,p_source_description text DEFAULT NULL,p_confirmed boolean DEFAULT false) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN PERFORM public.assistant_media_owner_fence();RETURN public.assistant_media_photo_manage_legacy_031(p_image_id,p_action,p_expected_version,p_image_kind,p_source_description,p_confirmed); END $$;
CREATE FUNCTION public.retire_personal_reference(p_image_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN PERFORM public.assistant_media_owner_fence();RETURN public.assistant_media_photo_retire_legacy_031(p_image_id); END $$;

-- Metadata acknowledgements below are private implementation details. A normal
-- caller cannot turn its own DELETE response (or a 404) into physical evidence.
ALTER FUNCTION public.ack_personal_gallery_image_cleanup(uuid) RENAME TO assistant_media_photo_ack_legacy_031;
ALTER FUNCTION public.ack_medication_library_pdf_cleanup(uuid) RENAME TO assistant_media_pdf_ack_legacy_031;
REVOKE ALL ON FUNCTION public.assistant_media_photo_ack_legacy_031(uuid),public.assistant_media_pdf_ack_legacy_031(uuid)
 FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;
GRANT EXECUTE ON FUNCTION public.assistant_media_photo_ack_legacy_031(uuid),public.assistant_media_pdf_ack_legacy_031(uuid) TO assistant_workflow_owner;

CREATE FUNCTION public.assistant_media_delete_projection(p_id uuid) RETURNS jsonb
LANGUAGE sql SECURITY INVOKER SET search_path='' AS $$
 SELECT jsonb_build_object('ticket_id',id,'nonce',nonce,'generation',generation,'owner',owner,
 'task_id',task_id,'task_revision',task_revision,'action_key',action_key,'media_kind',media_kind,
 'medication_id',medication_id,'native_ref',native_ref,'object_ref',object_ref,'checksum',checksum,'expires_at',expires_at)
 FROM public.assistant_media_delete_tickets WHERE owner=public.assistant_patient_uid() AND id=p_id
$$;

CREATE FUNCTION public.assistant_media_delete_current(p_owner uuid,p_action uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE r public.assistant_business_receipts%ROWTYPE;c public.assistant_media_commands%ROWTYPE;n jsonb;photo boolean;path text;bucket text;
BEGIN
 IF p_owner IS DISTINCT FROM public.assistant_patient_uid() THEN RAISE EXCEPTION 'Owned deletion required' USING ERRCODE='42501'; END IF;
 SELECT * INTO r FROM public.assistant_business_receipts WHERE owner=p_owner AND action_key=p_action;
 SELECT * INTO c FROM public.assistant_media_commands WHERE owner=p_owner AND action_key=p_action;
 IF r.owner IS NULL OR c.owner IS NULL OR r.outcome IS DISTINCT FROM 'applied'
 OR r.capability_id NOT IN ('gallery.photo.delete','library.pdf.delete') OR r.business_ref->>'kind' IS DISTINCT FROM 'file'
 OR c.kind IS DISTINCT FROM (CASE r.capability_id WHEN 'gallery.photo.delete' THEN 'delete_photo' ELSE 'tombstone_pdf' END) THEN
  RAISE EXCEPTION 'Actual confirmed native deletion receipt required' USING ERRCODE='P0002'; END IF;
 photo:=r.capability_id='gallery.photo.delete';n:=public.assistant_media_native(p_owner,photo,(r.business_ref->>'id')::uuid);
 IF n->>'deleted_at' IS NULL OR coalesce(n->'metadata_version',n->'version') IS DISTINCT FROM r.business_ref->'version'
 OR c.native_hash IS DISTINCT FROM encode(sha256(convert_to((n-'cleanup_pending')::text,'UTF8')),'hex')
 OR (photo AND n->>'source_id' IS NOT NULL) OR (NOT photo AND (n->>'source_document_id' IS NOT NULL OR n->>'regimen_version_id' IS NOT NULL)) THEN
  RAISE EXCEPTION 'Actual native tombstone changed or is protected' USING ERRCODE='40001'; END IF;
 path:=CASE WHEN photo THEN p_owner::text||'/'||(n->>'medication_id')||'/'||(n->>'checksum')||'.png'
 ELSE p_owner::text||'/library/'||(n->>'medication_id')||'/'||(n->>'checksum')||'.pdf' END;
 bucket:=CASE WHEN photo THEN 'visual-references' ELSE 'medication-sources' END;
 IF path IS NULL OR n->>'checksum' !~ '^[a-f0-9]{64}$' OR n->>'storage_path' IS DISTINCT FROM path
 OR (photo AND EXISTS(SELECT 1 FROM public.medication_images i WHERE i.patient_id=p_owner AND i.id<>(n->>'id')::uuid AND i.data->>'storage_path'=path))
 OR (NOT photo AND EXISTS(SELECT 1 FROM public.medication_library_files f WHERE f.patient_id=p_owner AND f.id<>(n->>'id')::uuid AND f.storage_path=path))
 OR EXISTS(SELECT 1 FROM public.assistant_media_copy_tickets t WHERE t.owner=p_owner AND t.bucket_id=bucket AND t.object_ref=path AND t.state<>'settled') THEN
  RAISE EXCEPTION 'Shared native reference or unresolved copy writer' USING ERRCODE='40001'; END IF;
 RETURN n;
END $$;

CREATE FUNCTION public.assistant_media_cleanup_command(p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=public.assistant_patient_uid();kind text:=p_command->>'kind';aid uuid;reference jsonb:=p_command->'reference';allowed text[];
 r public.assistant_business_receipts%ROWTYPE;t public.assistant_media_delete_tickets%ROWTYPE;v public.assistant_media_delete_verifications%ROWTYPE;
 s public.assistant_media_cleanup_settlements%ROWTYPE;n jsonb;task jsonb;ctl jsonb;child jsonb;proof jsonb;bucket text;photo boolean;
BEGIN
 IF o IS NULL OR public.assistant_patient_role() IS DISTINCT FROM 'authenticated' THEN RAISE EXCEPTION 'Verified owner required' USING ERRCODE='42501'; END IF;
 allowed:=CASE kind WHEN 'start' THEN ARRAY['kind','action_key'] WHEN 'claim' THEN ARRAY['kind','ticket_id','nonce','generation']
 WHEN 'settle' THEN ARRAY['kind','reference'] END;
 IF allowed IS NULL OR NOT coalesce(public.assistant_wf_keys(p_command,allowed) AND p_command ?& allowed,false)
 OR octet_length(p_command::text)>2048 THEN RAISE EXCEPTION 'Closed native cleanup command required' USING ERRCODE='22023'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 IF kind='start' THEN aid:=(p_command->>'action_key')::uuid;
 ELSE
  SELECT * INTO t FROM public.assistant_media_delete_tickets WHERE owner=o AND id=coalesce((p_command->>'ticket_id')::uuid,(reference->>'ticket_id')::uuid) FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Owned native delete ticket unavailable' USING ERRCODE='P0002'; END IF;
  aid:=t.action_key;
 END IF;
 n:=public.assistant_media_delete_current(o,aid);
 SELECT * INTO STRICT r FROM public.assistant_business_receipts WHERE owner=o AND action_key=aid;
 photo:=r.capability_id='gallery.photo.delete';bucket:=CASE WHEN photo THEN 'visual-references' ELSE 'medication-sources' END;
 SELECT * INTO s FROM public.assistant_media_cleanup_settlements WHERE owner=o AND action_key=aid;
 IF kind='start' THEN
  IF s.owner IS NOT NULL THEN
   IF n->'cleanup_pending' IS DISTINCT FROM 'false'::jsonb OR s.native_ref IS DISTINCT FROM r.business_ref THEN
    RAISE EXCEPTION 'Historical cleanup settlement differs from native metadata' USING ERRCODE='40001'; END IF;
   RETURN jsonb_build_object('result',jsonb_build_object('kind','settled','result',jsonb_build_object('receipt',to_jsonb(r),'result',n)));
  END IF;
  IF n->'cleanup_pending' IS DISTINCT FROM 'true'::jsonb THEN RAISE EXCEPTION 'Independent native deletion proof is missing' USING ERRCODE='40001'; END IF;
  SELECT * INTO t FROM public.assistant_media_delete_tickets WHERE owner=o AND bucket_id=bucket AND object_ref=n->>'storage_path' FOR UPDATE;
  IF FOUND THEN
   IF t.action_key IS DISTINCT FROM aid OR t.native_ref IS DISTINCT FROM r.business_ref THEN RAISE EXCEPTION 'Native key belongs to another deletion' USING ERRCODE='40001'; END IF;
   SELECT * INTO v FROM public.assistant_media_delete_verifications WHERE owner=o AND ticket_id=t.id AND generation=t.generation AND result='absent_after_delete';
   IF FOUND THEN
    proof:=jsonb_build_object('family','native_media_delete','ticket_id',t.id,'verification_id',v.id,'generation',v.generation,'result',v.result);
    RETURN jsonb_build_object('result',jsonb_build_object('kind','verified','ticket',public.assistant_media_delete_projection(t.id),'proof',proof));
   END IF;
   IF t.state<>'issued' THEN RAISE EXCEPTION 'Unresolved deletion cannot be replayed or expired away' USING ERRCODE='40001'; END IF;
  ELSE
   INSERT INTO public.assistant_media_delete_tickets(owner,id,nonce,generation,task_id,task_revision,action_key,media_kind,medication_id,native_ref,bucket_id,object_ref,checksum,expires_at)
   VALUES(o,gen_random_uuid(),gen_random_uuid(),1,r.task_id,r.binding_revision,aid,CASE WHEN photo THEN 'photo' ELSE 'pdf' END,
    (n->>'medication_id')::uuid,r.business_ref,bucket,n->>'storage_path',n->>'checksum',clock_timestamp()+interval '45 seconds') RETURNING * INTO t;
   INSERT INTO public.assistant_native_media_deletions(owner,bucket_id,object_ref,ticket_id) VALUES(o,bucket,t.object_ref,t.id);
  END IF;
  IF NOT EXISTS(SELECT 1 FROM public.assistant_native_media_deletions d WHERE d.owner=o AND d.bucket_id=t.bucket_id AND d.object_ref=t.object_ref AND d.ticket_id=t.id) THEN
   RAISE EXCEPTION 'Persistent native deleting exclusion missing' USING ERRCODE='40001'; END IF;
  RETURN jsonb_build_object('result',jsonb_build_object('kind','ticket','ticket',public.assistant_media_delete_projection(t.id)));
 END IF;
 IF t.native_ref IS DISTINCT FROM r.business_ref OR t.task_id IS DISTINCT FROM r.task_id OR t.task_revision IS DISTINCT FROM r.binding_revision
 OR t.object_ref IS DISTINCT FROM n->>'storage_path' OR t.checksum IS DISTINCT FROM n->>'checksum' OR t.bucket_id IS DISTINCT FROM bucket
 OR NOT EXISTS(SELECT 1 FROM public.assistant_native_media_deletions d WHERE d.owner=o AND d.bucket_id=t.bucket_id AND d.object_ref=t.object_ref AND d.ticket_id=t.id) THEN
  RAISE EXCEPTION 'Native deletion target/exclusion changed' USING ERRCODE='40001'; END IF;
 IF kind='claim' THEN
  IF t.state<>'issued' OR t.nonce IS DISTINCT FROM (p_command->>'nonce')::uuid OR t.generation IS DISTINCT FROM (p_command->>'generation')::int
  OR clock_timestamp()>=t.expires_at OR n->'cleanup_pending' IS DISTINCT FROM 'true'::jsonb THEN
   RAISE EXCEPTION 'Native deletion cannot be claimed again' USING ERRCODE='40001'; END IF;
  UPDATE public.assistant_media_delete_tickets SET state='inflight' WHERE owner=o AND id=t.id;
  RETURN jsonb_build_object('result',true);
 END IF;
 IF NOT coalesce(public.assistant_wf_keys(reference,ARRAY['family','ticket_id','verification_id','generation','result'])
 AND reference ?& ARRAY['family','ticket_id','verification_id','generation','result'],false)
 OR reference->>'family' IS DISTINCT FROM 'native_media_delete' OR reference->>'result' IS DISTINCT FROM 'absent_after_delete'
 OR (reference->>'generation')::int IS DISTINCT FROM t.generation THEN RAISE EXCEPTION 'Correlated native delete proof required' USING ERRCODE='22023'; END IF;
 SELECT * INTO v FROM public.assistant_media_delete_verifications WHERE owner=o AND id=(reference->>'verification_id')::uuid
 AND ticket_id=t.id AND generation=t.generation AND result='absent_after_delete' AND bucket_id=t.bucket_id;
 IF NOT FOUND OR t.state<>'settled' THEN RAISE EXCEPTION 'Actual independent absence proof unavailable' USING ERRCODE='40001'; END IF;
 IF s.owner IS NOT NULL THEN
  IF n->'cleanup_pending' IS DISTINCT FROM 'false'::jsonb OR s.reference IS DISTINCT FROM reference THEN RAISE EXCEPTION 'Native cleanup already has another settlement' USING ERRCODE='40001'; END IF;
 ELSE
  IF n->'cleanup_pending' IS DISTINCT FROM 'true'::jsonb THEN RAISE EXCEPTION 'Unsettled native cleanup differs' USING ERRCODE='40001'; END IF;
  IF photo THEN PERFORM public.assistant_media_photo_ack_legacy_031((r.business_ref->>'id')::uuid);
  ELSE PERFORM public.assistant_media_pdf_ack_legacy_031((r.business_ref->>'id')::uuid); END IF;
  -- A revoked/changed task stays revoked/changed. Technical settlement cannot
  -- reconstruct content or require the original chat run to remain alive.
  SELECT data INTO task FROM public.assistant_workflow_tasks WHERE owner=o AND id=r.task_id FOR UPDATE;
  SELECT data INTO ctl FROM public.assistant_workflow_operations WHERE owner=o AND task_id=r.task_id AND id=r.task_id AND record_type='control' FOR UPDATE;
  IF (task->>'revision')::int=r.binding_revision AND (ctl->>'revision')::int=r.binding_revision
  AND task->>'capability_id'=r.capability_id AND task->>'state'='outcome_unknown' AND task->>'save_mode'='allowed'
  AND ctl->>'mode'='allowed' AND ctl->'revoked'='false'::jsonb AND ctl->>'status'='idle'
  AND task->'business_refs' @> jsonb_build_array(r.business_ref) THEN
   child:=public.assistant_workflow_command_legacy_035('task_cas',jsonb_build_object('task_id',r.task_id,'expected_revision',r.binding_revision,
    'event_id',extensions.uuid_generate_v5(t.id,'cleanup-settlement'),'request_digest',encode(sha256(convert_to(reference::text,'UTF8')),'hex'),
    'update',jsonb_build_object('state','completed','save_mode','allowed','storage_state','saved','fields',task->'fields','missing_fields','[]'::jsonb,
    'attachment_ids',task->'attachment_ids','business_refs',task->'business_refs')));
   IF child ? 'error' THEN RAISE EXCEPTION 'Native cleanup task publication changed' USING ERRCODE='40001'; END IF;
  END IF;
  INSERT INTO public.assistant_media_cleanup_settlements(owner,action_key,native_ref,reference) VALUES(o,aid,r.business_ref,reference);
 END IF;
 n:=public.assistant_media_native(o,photo,(r.business_ref->>'id')::uuid);
 IF n->'cleanup_pending' IS DISTINCT FROM 'false'::jsonb THEN RAISE EXCEPTION 'Actual native cleanup acknowledgement unavailable' USING ERRCODE='40001'; END IF;
 RETURN jsonb_build_object('result',jsonb_build_object('receipt',to_jsonb(r),'result',n));
EXCEPTION WHEN SQLSTATE '40001' THEN RETURN jsonb_build_object('error','stale'); WHEN SQLSTATE 'P0002' THEN RETURN jsonb_build_object('error','not_found');
 WHEN unique_violation THEN RETURN jsonb_build_object('error','duplicate');
 WHEN invalid_parameter_value OR invalid_text_representation OR check_violation OR not_null_violation THEN RETURN jsonb_build_object('error','invalid');
END $$;

-- Preserve native ACK signatures, but require their actual typed deletion
-- receipt and independently recorded absence. I14 must adapt legacy callers
-- before any candidate can be enabled; a caller's own DELETE/404 is insufficient.
CREATE FUNCTION public.assistant_media_ack(p_id uuid,p_photo boolean) RETURNS void
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE o uuid:=public.assistant_patient_uid();t public.assistant_media_delete_tickets%ROWTYPE;v public.assistant_media_delete_verifications%ROWTYPE;result jsonb;
BEGIN
 IF o IS NULL OR public.assistant_patient_role() IS DISTINCT FROM 'authenticated' THEN RAISE EXCEPTION 'Verified owner required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 SELECT * INTO t FROM public.assistant_media_delete_tickets WHERE owner=o AND native_ref->>'id'=p_id::text AND media_kind=CASE WHEN p_photo THEN 'photo' ELSE 'pdf' END;
 SELECT * INTO v FROM public.assistant_media_delete_verifications WHERE owner=o AND ticket_id=t.id AND generation=t.generation AND result='absent_after_delete' AND bucket_id=t.bucket_id;
 IF t.owner IS NULL OR v.owner IS NULL THEN RAISE EXCEPTION 'Independent native deletion proof required' USING ERRCODE='40001'; END IF;
 result:=public.assistant_media_cleanup_command(jsonb_build_object('kind','settle','reference',jsonb_build_object('family','native_media_delete',
  'ticket_id',t.id,'verification_id',v.id,'generation',v.generation,'result',v.result)));
 IF result ? 'error' THEN RAISE EXCEPTION 'Native cleanup settlement unavailable' USING ERRCODE='40001'; END IF;
END $$;
CREATE FUNCTION public.ack_personal_gallery_image_cleanup(p_image_id uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$ BEGIN PERFORM public.assistant_media_ack(p_image_id,true); END $$;
CREATE FUNCTION public.ack_medication_library_pdf_cleanup(p_id uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$ BEGIN PERFORM public.assistant_media_ack(p_id,false); END $$;

-- Fence reference creation against permanent deleting keys. Existing metadata
-- updates/cleanup acknowledgements do not acquire new object references.
CREATE FUNCTION public.assistant_media_reference_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=public.assistant_patient_uid();path text;bucket text;image jsonb;native_id uuid;med uuid;checksum text;
BEGIN
 IF o IS NULL OR NEW.patient_id IS DISTINCT FROM o THEN RAISE EXCEPTION 'Verified owned reference required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 IF TG_TABLE_NAME='medication_images' THEN
  IF TG_OP='UPDATE' THEN
   IF NEW.data->>'storage_path' IS NOT DISTINCT FROM OLD.data->>'storage_path' AND NEW.source_id IS NOT DISTINCT FROM OLD.source_id THEN RETURN NEW; END IF;
  END IF;
  path:=NEW.data->>'storage_path';bucket:='visual-references';native_id:=NEW.id;med:=NEW.medication_id;checksum:=NEW.data->>'checksum';
 ELSIF TG_TABLE_NAME='medication_library_files' THEN
  IF TG_OP='UPDATE' THEN
   IF NEW.storage_path IS NOT DISTINCT FROM OLD.storage_path AND NEW.source_document_id IS NOT DISTINCT FROM OLD.source_document_id
   AND NEW.regimen_version_id IS NOT DISTINCT FROM OLD.regimen_version_id THEN RETURN NEW; END IF;
  END IF;
  path:=NEW.storage_path;bucket:='medication-sources';native_id:=NEW.id;med:=NEW.medication_id;checksum:=NEW.checksum;
 ELSE
  -- Source association may reference several images; reject any deleting key.
  IF EXISTS(SELECT 1 FROM public.medication_images i JOIN public.assistant_native_media_deletions d
   ON d.owner=i.patient_id AND d.bucket_id='visual-references' AND d.object_ref=i.data->>'storage_path'
   WHERE i.patient_id=o AND i.source_id=NEW.source_id) THEN RAISE EXCEPTION 'Deleting source cannot acquire new associations' USING ERRCODE='40001'; END IF;
  RETURN NEW;
 END IF;
 IF path IS NULL OR EXISTS(SELECT 1 FROM public.assistant_native_media_deletions d WHERE d.owner=o AND d.bucket_id=bucket AND d.object_ref=path) THEN
  RAISE EXCEPTION 'Deleting native object cannot acquire references' USING ERRCODE='40001'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.assistant_media_copy_tickets t JOIN public.assistant_media_copy_verifications v ON v.owner=t.owner AND v.ticket_id=t.id AND v.generation=t.generation
  WHERE t.owner=o AND t.bucket_id=bucket AND t.object_ref=path AND t.target->>'native_id'=native_id::text AND t.target->>'medication_id'=med::text
  AND t.target->>'checksum'=checksum AND v.result='bytes_verified' AND v.checksum=checksum AND v.bucket_id=bucket
  AND v.byte_size=(t.target->>'byte_size')::int AND v.source_checksum=t.source_checksum) THEN
  RAISE EXCEPTION 'Actual independently verified native bytes required' USING ERRCODE='40001'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER assistant_media_reference BEFORE INSERT OR UPDATE ON public.medication_images
 FOR EACH ROW EXECUTE FUNCTION public.assistant_media_reference_guard();
CREATE TRIGGER assistant_media_reference BEFORE INSERT OR UPDATE ON public.medication_library_files
 FOR EACH ROW EXECUTE FUNCTION public.assistant_media_reference_guard();
CREATE TRIGGER assistant_media_reference BEFORE INSERT OR UPDATE ON public.medication_source_links
 FOR EACH ROW EXECUTE FUNCTION public.assistant_media_reference_guard();

DO $$ DECLARE signature text; BEGIN
 FOREACH signature IN ARRAY ARRAY['assistant_original_verification_ref(uuid,uuid)','assistant_media_copy_projection(uuid)',
 'assistant_media_copy_current(uuid,public.assistant_media_copy_tickets)','assistant_media_copy_verified(uuid,jsonb)',
 'assistant_media_copy_command(jsonb)','assistant_native_image_assert_verified(uuid,jsonb,jsonb,uuid)',
 'assistant_media_epoch_changed()','assistant_media_revision()','assistant_media_native(uuid,boolean,uuid)',
 'assistant_media_expected(text,jsonb)','assistant_media_selection(uuid,jsonb)','assistant_media_result(uuid,jsonb)',
 'assistant_media_apply(jsonb)','assistant_media_prepare(jsonb)','assistant_media_write(jsonb)','assistant_media_read(jsonb)','assistant_media_filename(text)',
 'assistant_media_delete_projection(uuid)','assistant_media_delete_current(uuid,uuid)','assistant_media_cleanup_command(jsonb)',
 'assistant_media_ack(uuid,boolean)','ack_personal_gallery_image_cleanup(uuid)','ack_medication_library_pdf_cleanup(uuid)','assistant_media_reference_guard()',
 'assistant_media_owner_fence()','register_medication_library_pdf(jsonb)','update_medication_library_pdf(uuid,integer,text,text,text)',
 'tombstone_medication_library_pdf(uuid,boolean)','manage_personal_gallery_image(uuid,text,integer,text,text,boolean)','retire_personal_reference(uuid)'] LOOP
  EXECUTE 'ALTER FUNCTION public.'||signature||' OWNER TO assistant_workflow_owner';
  EXECUTE 'REVOKE ALL ON FUNCTION public.'||signature||' FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner';
 END LOOP;
END $$;
GRANT EXECUTE ON FUNCTION public.assistant_original_verification_ref(uuid,uuid),public.assistant_media_copy_command(jsonb),
 public.assistant_media_revision(),public.assistant_media_prepare(jsonb),public.assistant_media_write(jsonb),public.assistant_media_read(jsonb),
 public.assistant_media_cleanup_command(jsonb),public.ack_personal_gallery_image_cleanup(uuid),public.ack_medication_library_pdf_cleanup(uuid),
 public.register_medication_library_pdf(jsonb),public.update_medication_library_pdf(uuid,integer,text,text,text),public.tombstone_medication_library_pdf(uuid,boolean),
 public.manage_personal_gallery_image(uuid,text,integer,text,text,boolean),public.retire_personal_reference(uuid) TO authenticated;
COMMIT;
