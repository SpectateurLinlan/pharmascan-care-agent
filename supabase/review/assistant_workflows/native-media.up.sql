-- REVIEW ONLY / NOT APPLIED. Task-independent native file compatibility, after all existing candidates.
-- No roles, clinical grants, Storage policy changes, provider calls or activation.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';
CREATE TABLE public.assistant_native_file_intents (
 owner uuid NOT NULL,id uuid PRIMARY KEY,nonce uuid NOT NULL UNIQUE,generation integer NOT NULL DEFAULT 1 CHECK(generation>0),
 operation text NOT NULL CHECK(operation IN ('upload','delete')),target jsonb NOT NULL,
 bucket_id text NOT NULL CHECK(bucket_id IN ('visual-references','medication-sources')),object_ref text NOT NULL CHECK(length(object_ref)<=400),
 native_ref jsonb,native_hash text,command_digest text NOT NULL CHECK(command_digest~'^[a-f0-9]{64}$'),
 expires_at timestamptz NOT NULL,state text NOT NULL DEFAULT 'issued' CHECK(state IN ('issued','inflight','unknown','settled')),
 published boolean NOT NULL DEFAULT false,UNIQUE(owner,id),UNIQUE(owner,operation,bucket_id,object_ref),
 CHECK(target->>'owner'=owner::text AND target->>'bucket_id'=bucket_id AND target->>'object_ref'=object_ref)
);
CREATE TABLE public.assistant_native_file_observations (
 id uuid PRIMARY KEY,owner uuid NOT NULL,ticket_id uuid NOT NULL,generation integer NOT NULL CHECK(generation>0),
 result text NOT NULL CHECK(result IN ('bytes_verified','absent_after_delete','outcome_unknown')),
 checksum text,byte_size integer,bucket_id text,observed_at timestamptz NOT NULL,
 FOREIGN KEY(owner,ticket_id) REFERENCES public.assistant_native_file_intents(owner,id),UNIQUE(ticket_id,generation,result)
);
CREATE UNIQUE INDEX assistant_native_file_terminal ON public.assistant_native_file_observations(ticket_id,generation)
 WHERE result<>'outcome_unknown';
DO $$ DECLARE relation_name text; BEGIN
 FOREACH relation_name IN ARRAY ARRAY['assistant_native_file_intents','assistant_native_file_observations'] LOOP
  EXECUTE format('ALTER TABLE public.%I OWNER TO assistant_evidence_owner',relation_name);
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',relation_name);
  EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',relation_name);
  EXECUTE format('CREATE POLICY assistant_native_file_technical ON public.%I TO assistant_evidence_owner USING(true) WITH CHECK(true)',relation_name);
  EXECUTE format('CREATE POLICY assistant_native_file_patient_command ON public.%I TO assistant_workflow_owner USING(owner=public.assistant_patient_uid()) WITH CHECK(owner=public.assistant_patient_uid())',relation_name);
  EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login',relation_name);
 END LOOP;
END $$;
GRANT SELECT,INSERT,UPDATE ON public.assistant_native_file_intents TO assistant_workflow_owner;
GRANT SELECT ON public.assistant_native_file_observations TO assistant_workflow_owner;
ALTER TABLE public.assistant_native_media_deletions ADD CONSTRAINT assistant_native_file_exclusion_fk
 FOREIGN KEY(owner,native_ticket_id) REFERENCES public.assistant_native_file_intents(owner,id);

CREATE FUNCTION assistant_evidence.native_file_immutable() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF TG_TABLE_NAME='assistant_native_file_observations' OR TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Retain native file facts and exclusions' USING ERRCODE='42501'; END IF;
 IF (NEW.owner,NEW.id,NEW.operation,NEW.target,NEW.bucket_id,NEW.object_ref,NEW.native_ref,NEW.native_hash,NEW.command_digest)
 IS DISTINCT FROM (OLD.owner,OLD.id,OLD.operation,OLD.target,OLD.bucket_id,OLD.object_ref,OLD.native_ref,OLD.native_hash,OLD.command_digest)
 OR (OLD.published AND NOT NEW.published) THEN RAISE EXCEPTION 'Immutable native intent binding' USING ERRCODE='40001'; END IF;
 IF (NEW.nonce,NEW.generation,NEW.expires_at) IS DISTINCT FROM (OLD.nonce,OLD.generation,OLD.expires_at) THEN
  IF OLD.state<>'issued' OR OLD.expires_at>clock_timestamp() OR NEW.state<>'issued' OR NEW.generation<>OLD.generation+1
  OR EXISTS(SELECT 1 FROM public.assistant_native_file_observations WHERE ticket_id=OLD.id) THEN
   RAISE EXCEPTION 'A claimed or observed native operation cannot be reissued' USING ERRCODE='40001'; END IF;
 END IF;
 IF NOT((OLD.state='issued' AND NEW.state IN ('issued','inflight')) OR (OLD.state IN ('inflight','unknown') AND NEW.state IN ('unknown','settled'))
 OR (OLD.state='settled' AND NEW.state='settled')) THEN RAISE EXCEPTION 'Native operation cannot restart' USING ERRCODE='40001'; END IF;
 RETURN NEW;
END $$;
ALTER FUNCTION assistant_evidence.native_file_immutable() OWNER TO assistant_evidence_owner;
REVOKE ALL ON FUNCTION assistant_evidence.native_file_immutable() FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login;
CREATE TRIGGER assistant_native_intent_immutable BEFORE UPDATE OR DELETE ON public.assistant_native_file_intents
 FOR EACH ROW EXECUTE FUNCTION assistant_evidence.native_file_immutable();
CREATE TRIGGER assistant_native_observation_immutable BEFORE UPDATE OR DELETE ON public.assistant_native_file_observations
 FOR EACH ROW EXECUTE FUNCTION assistant_evidence.native_file_immutable();

CREATE FUNCTION public.assistant_native_file_target(p_owner uuid,p_target jsonb,p_upload boolean) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE SECURITY INVOKER SET search_path='' AS $$
DECLARE parts text[];pdf boolean;med uuid;checksum text;path text;size integer;
BEGIN
 IF NOT coalesce(public.assistant_wf_keys(p_target,ARRAY['owner','bucket_id','object_ref','checksum','content_type','byte_size'])
 AND p_target ?& ARRAY['owner','bucket_id','object_ref','checksum','content_type','byte_size'],false)
 OR p_target->>'owner' IS DISTINCT FROM p_owner::text OR p_target->>'bucket_id' NOT IN ('visual-references','medication-sources') THEN
  RAISE EXCEPTION 'Owned bounded native file target required' USING ERRCODE='22023'; END IF;
 pdf:=p_target->>'bucket_id'='medication-sources';parts:=string_to_array(p_target->>'object_ref','/');
 IF cardinality(parts)<>(CASE WHEN pdf THEN 4 ELSE 3 END) OR parts[1]<>p_owner::text OR (pdf AND parts[2]<>'library') THEN
  RAISE EXCEPTION 'Canonical owned native path required' USING ERRCODE='22023'; END IF;
 med:=parts[cardinality(parts)-1]::uuid;checksum:=p_target->>'checksum';
 path:=p_owner::text||CASE WHEN pdf THEN '/library/' ELSE '/' END||med::text||'/'||checksum||CASE WHEN pdf THEN '.pdf' ELSE '.png' END;
 IF checksum IS NULL OR checksum!~'^[a-f0-9]{64}$' OR p_target->>'object_ref' IS DISTINCT FROM path
 OR p_target->>'content_type' IS DISTINCT FROM (CASE WHEN pdf THEN 'application/pdf' ELSE 'image/png' END)
 OR (p_upload AND (jsonb_typeof(p_target->'byte_size') IS DISTINCT FROM 'number' OR p_target->>'byte_size' !~ '^[1-9][0-9]*$')) THEN
  RAISE EXCEPTION 'Canonical native checksum/MIME/size required' USING ERRCODE='22023'; END IF;
 IF p_target->>'byte_size' IS NOT NULL THEN
  size:=(p_target->>'byte_size')::int;
  IF size<1 OR size>(CASE WHEN pdf THEN 10485760 ELSE 8000000 END) THEN RAISE EXCEPTION 'Native file exceeds purpose limit' USING ERRCODE='22023'; END IF;
 END IF;
 RETURN p_target;
END $$;

CREATE FUNCTION public.assistant_native_file_delete_current(p_owner uuid,p_bucket text,p_path text) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE n jsonb;ref jsonb;kind text;receipt public.draft_deletion_receipts%ROWTYPE;count_rows integer;
BEGIN
 IF p_owner IS DISTINCT FROM public.assistant_patient_uid() THEN RAISE EXCEPTION 'Owned native deletion required' USING ERRCODE='42501'; END IF;
 IF p_bucket='visual-references' THEN
  SELECT count(*) INTO count_rows FROM public.medication_images WHERE patient_id=p_owner AND data->>'storage_path'=p_path;
  IF count_rows>1 THEN RAISE EXCEPTION 'Shared native image protected' USING ERRCODE='40001'; END IF;
  SELECT data||jsonb_build_object('id',id,'medication_id',medication_id,'source_id',source_id) INTO n FROM public.medication_images WHERE patient_id=p_owner AND data->>'storage_path'=p_path;
  IF FOUND THEN
   IF n->>'deleted_at' IS NULL OR n->>'source_id' IS NOT NULL THEN RAISE EXCEPTION 'Formal or current native image protected' USING ERRCODE='40001'; END IF;
   ref:=jsonb_build_object('kind','file','id',n->'id','version',coalesce(n->'metadata_version','1'::jsonb));
  ELSE
   SELECT count(*) INTO count_rows FROM public.draft_deletion_receipts WHERE patient_id=p_owner AND p_path=ANY(storage_paths);
   IF count_rows<>1 THEN RAISE EXCEPTION 'Exclusive owned deletion receipt required' USING ERRCODE='40001'; END IF;
   SELECT * INTO receipt FROM public.draft_deletion_receipts WHERE patient_id=p_owner AND p_path=ANY(storage_paths);
   ref:=jsonb_build_object('kind',CASE WHEN receipt.kind='draft' THEN 'regimen' ELSE 'enrollment_task' END,'id',receipt.target_id);
   n:=jsonb_build_object('ref',ref,'storage_path',p_path,'cleanup_pending',true);
  END IF;
 ELSE
  SELECT count(*) INTO count_rows FROM public.medication_library_files WHERE patient_id=p_owner AND storage_path=p_path;
  IF count_rows<>1 THEN RAISE EXCEPTION 'Exclusive owned PDF required' USING ERRCODE='40001'; END IF;
  SELECT to_jsonb(f) INTO n FROM public.medication_library_files f WHERE patient_id=p_owner AND storage_path=p_path;
  IF n->>'deleted_at' IS NULL OR n->>'source_document_id' IS NOT NULL OR n->>'regimen_version_id' IS NOT NULL THEN
   RAISE EXCEPTION 'Current or formal PDF protected' USING ERRCODE='40001'; END IF;
  ref:=jsonb_build_object('kind','file','id',n->'id','version',n->'version');
 END IF;
 IF EXISTS(SELECT 1 FROM public.assistant_native_file_intents WHERE owner=p_owner AND bucket_id=p_bucket AND object_ref=p_path AND operation='upload' AND state<>'settled')
 OR EXISTS(SELECT 1 FROM public.assistant_media_copy_tickets WHERE owner=p_owner AND bucket_id=p_bucket AND object_ref=p_path AND state<>'settled') THEN
  RAISE EXCEPTION 'Unresolved native writer protected' USING ERRCODE='40001'; END IF;
 RETURN jsonb_build_object('ref',ref,'hash',encode(sha256(convert_to((n-'cleanup_pending')::text,'UTF8')),'hex'),
  'cleanup_pending',n->'cleanup_pending');
END $$;

CREATE FUNCTION public.assistant_native_file_projection(p_id uuid) RETURNS jsonb
LANGUAGE sql SECURITY INVOKER SET search_path='' AS $$
 SELECT jsonb_build_object('ticket_id',id,'nonce',nonce,'generation',generation,'operation',operation,'target',target,
 'expires_at',expires_at,'native_ref',native_ref) FROM public.assistant_native_file_intents WHERE owner=public.assistant_patient_uid() AND id=p_id
$$;
CREATE FUNCTION public.assistant_native_file_proof(p_id uuid) RETURNS jsonb
LANGUAGE sql SECURITY INVOKER SET search_path='' AS $$
 SELECT jsonb_build_object('family','native_object','ticket_id',ticket_id,'verification_id',id,'generation',generation,'result',result)
 FROM public.assistant_native_file_observations WHERE owner=public.assistant_patient_uid() AND ticket_id=p_id AND result<>'outcome_unknown'
 ORDER BY generation DESC LIMIT 1
$$;

CREATE FUNCTION public.assistant_native_media_command(p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=public.assistant_patient_uid();kind text:=p_command->>'kind';intent jsonb:=p_command->'intent';target jsonb;
 t public.assistant_native_file_intents%ROWTYPE;v public.assistant_native_file_observations%ROWTYPE;
 intent_id uuid;bucket text;path text;parts text[];pdf boolean;digest text;current_native jsonb;reference jsonb;allowed text[];
BEGIN
 IF o IS NULL OR public.assistant_patient_role() IS DISTINCT FROM 'authenticated' THEN RAISE EXCEPTION 'Verified patient required' USING ERRCODE='42501'; END IF;
 allowed:=CASE kind WHEN 'prepare_upload' THEN ARRAY['kind','intent'] WHEN 'prepare_delete' THEN ARRAY['kind','intent']
 WHEN 'claim' THEN ARRAY['kind','ticket_id','nonce','generation'] WHEN 'settle_delete' THEN ARRAY['kind','proof'] ELSE NULL END;
 IF allowed IS NULL OR NOT public.assistant_wf_keys(p_command,allowed) THEN RAISE EXCEPTION 'Closed native command required' USING ERRCODE='22023'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 IF kind IN ('prepare_upload','prepare_delete') THEN
  IF kind='prepare_upload' THEN
   IF NOT coalesce(public.assistant_wf_keys(intent,ARRAY['operation_id','target']) AND intent ?& ARRAY['operation_id','target'],false) THEN RAISE EXCEPTION 'Closed upload intent required' USING ERRCODE='22023'; END IF;
   target:=public.assistant_native_file_target(o,intent->'target',true);
  ELSE
   IF NOT coalesce(public.assistant_wf_keys(intent,ARRAY['operation_id','owner','bucket_id','object_ref']) AND intent ?& ARRAY['operation_id','owner','bucket_id','object_ref'],false)
   OR intent->>'owner' IS DISTINCT FROM o::text THEN RAISE EXCEPTION 'Closed owned delete intent required' USING ERRCODE='22023'; END IF;
   bucket:=intent->>'bucket_id';path:=intent->>'object_ref';parts:=string_to_array(path,'/');pdf:=bucket='medication-sources';
   target:=public.assistant_native_file_target(o,jsonb_build_object('owner',o,'bucket_id',bucket,'object_ref',path,
    'checksum',regexp_replace(parts[cardinality(parts)],CASE WHEN pdf THEN '[.]pdf$' ELSE '[.]png$' END,''),
    'content_type',CASE WHEN pdf THEN 'application/pdf' ELSE 'image/png' END,'byte_size',NULL),false);
  END IF;
  intent_id:=(intent->>'operation_id')::uuid;bucket:=target->>'bucket_id';path:=target->>'object_ref';
  digest:=encode(sha256(convert_to(intent::text,'UTF8')),'hex');
  SELECT * INTO t FROM public.assistant_native_file_intents WHERE owner=o AND operation=CASE WHEN kind='prepare_upload' THEN 'upload' ELSE 'delete' END AND bucket_id=bucket AND object_ref=path FOR UPDATE;
  IF FOUND THEN
   IF t.id IS DISTINCT FROM intent_id OR t.command_digest IS DISTINCT FROM digest THEN RAISE EXCEPTION 'Native key/action reused with different input' USING ERRCODE='23505'; END IF;
   reference:=public.assistant_native_file_proof(t.id);
   IF reference IS NOT NULL THEN RETURN jsonb_build_object('result',jsonb_build_object('ticket',public.assistant_native_file_projection(t.id),'proof',reference)); END IF;
   IF t.state<>'issued' THEN RAISE EXCEPTION 'Unknown native operation cannot be replayed' USING ERRCODE='40001'; END IF;
   IF t.expires_at<=clock_timestamp() THEN
    UPDATE public.assistant_native_file_intents SET nonce=gen_random_uuid(),generation=generation+1,expires_at=clock_timestamp()+interval '45 seconds' WHERE owner=o AND assistant_native_file_intents.id=t.id;
   END IF;
  ELSE
   IF intent_id IS NULL THEN RAISE EXCEPTION 'Native operation id required' USING ERRCODE='22023'; END IF;
   IF kind='prepare_upload' THEN
    IF EXISTS(SELECT 1 FROM public.assistant_native_media_deletions WHERE owner=o AND bucket_id=bucket AND object_ref=path) THEN RAISE EXCEPTION 'Deleting native key cannot be written' USING ERRCODE='40001'; END IF;
   ELSE
    current_native:=public.assistant_native_file_delete_current(o,bucket,path);
    IF current_native->'cleanup_pending' IS DISTINCT FROM 'true'::jsonb THEN RAISE EXCEPTION 'Current confirmed tombstone required' USING ERRCODE='40001'; END IF;
    IF NOT EXISTS(SELECT 1 FROM public.assistant_native_file_intents i JOIN public.assistant_native_file_observations p ON p.owner=i.owner AND p.ticket_id=i.id AND p.generation=i.generation
     WHERE i.owner=o AND i.operation='upload' AND i.bucket_id=bucket AND i.object_ref=path AND i.state='settled' AND p.result='bytes_verified')
    AND NOT EXISTS(SELECT 1 FROM public.assistant_media_copy_tickets i JOIN public.assistant_media_copy_verifications p ON p.owner=i.owner AND p.ticket_id=i.id AND p.generation=i.generation
     WHERE i.owner=o AND i.bucket_id=bucket AND i.object_ref=path AND i.state='settled' AND p.result='bytes_verified') THEN
     RAISE EXCEPTION 'Untracked legacy writers require separate reconciliation' USING ERRCODE='40001'; END IF;
    IF EXISTS(SELECT 1 FROM public.assistant_native_media_deletions WHERE owner=o AND bucket_id=bucket AND object_ref=path) THEN RAISE EXCEPTION 'Native key already has a deleting operation' USING ERRCODE='40001'; END IF;
   END IF;
   INSERT INTO public.assistant_native_file_intents(owner,id,nonce,generation,operation,target,bucket_id,object_ref,native_ref,native_hash,command_digest,expires_at)
    VALUES(o,intent_id,gen_random_uuid(),1,CASE WHEN kind='prepare_upload' THEN 'upload' ELSE 'delete' END,target,bucket,path,current_native->'ref',current_native->>'hash',digest,clock_timestamp()+interval '45 seconds');
   IF kind='prepare_delete' THEN INSERT INTO public.assistant_native_media_deletions(owner,bucket_id,object_ref,native_ticket_id) VALUES(o,bucket,path,intent_id); END IF;
  END IF;
  RETURN jsonb_build_object('result',jsonb_build_object('ticket',public.assistant_native_file_projection(intent_id),'proof',NULL));
 END IF;
 intent_id:=CASE WHEN kind='claim' THEN (p_command->>'ticket_id')::uuid ELSE (p_command->'proof'->>'ticket_id')::uuid END;
 SELECT * INTO t FROM public.assistant_native_file_intents WHERE owner=o AND assistant_native_file_intents.id=intent_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Owned native intent required' USING ERRCODE='P0002'; END IF;
 IF t.operation='delete' THEN
  current_native:=public.assistant_native_file_delete_current(o,t.bucket_id,t.object_ref);
  IF current_native->'ref' IS DISTINCT FROM t.native_ref OR current_native->>'hash' IS DISTINCT FROM t.native_hash
  OR NOT EXISTS(SELECT 1 FROM public.assistant_native_media_deletions WHERE owner=o AND native_ticket_id=t.id AND bucket_id=t.bucket_id AND object_ref=t.object_ref) THEN
   RAISE EXCEPTION 'Actual tombstone or permanent deleting exclusion changed' USING ERRCODE='40001'; END IF;
 END IF;
 IF kind='claim' THEN
  IF jsonb_typeof(p_command->'generation') IS DISTINCT FROM 'number' OR t.nonce IS DISTINCT FROM (p_command->>'nonce')::uuid OR t.generation IS DISTINCT FROM (p_command->>'generation')::int
  OR t.state<>'issued' OR clock_timestamp()>=t.expires_at OR (t.operation='upload' AND EXISTS(
   SELECT 1 FROM public.assistant_native_media_deletions WHERE owner=o AND bucket_id=t.bucket_id AND object_ref=t.object_ref)) THEN
   RAISE EXCEPTION 'Native operation cannot be started or replayed' USING ERRCODE='40001'; END IF;
  UPDATE public.assistant_native_file_intents SET state='inflight' WHERE owner=o AND assistant_native_file_intents.id=t.id;
 ELSE
  reference:=p_command->'proof';
  IF t.operation<>'delete' OR t.state<>'settled' OR NOT coalesce(public.assistant_wf_keys(reference,ARRAY['family','ticket_id','verification_id','generation','result']),false)
  OR reference->>'family' IS DISTINCT FROM 'native_object' OR reference->>'result' IS DISTINCT FROM 'absent_after_delete'
  OR (reference->>'generation')::int IS DISTINCT FROM t.generation THEN RAISE EXCEPTION 'Correlated native absence proof required' USING ERRCODE='40001'; END IF;
  SELECT * INTO v FROM public.assistant_native_file_observations WHERE owner=o AND assistant_native_file_observations.id=(reference->>'verification_id')::uuid
   AND ticket_id=t.id AND generation=t.generation AND result='absent_after_delete' AND bucket_id=t.bucket_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'Actual absence proof unavailable' USING ERRCODE='40001'; END IF;
 END IF;
 RETURN jsonb_build_object('result',true);
EXCEPTION WHEN SQLSTATE '40001' THEN RETURN jsonb_build_object('error','stale');
 WHEN SQLSTATE 'P0002' THEN RETURN jsonb_build_object('error','not_found'); WHEN unique_violation THEN RETURN jsonb_build_object('error','duplicate');
 WHEN invalid_parameter_value OR invalid_text_representation OR check_violation OR not_null_violation THEN RETURN jsonb_build_object('error','invalid');
END $$;
ALTER FUNCTION public.assistant_native_media_command(jsonb) OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_native_media_command(jsonb) FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;
GRANT EXECUTE ON FUNCTION public.assistant_native_media_command(jsonb) TO authenticated;

CREATE FUNCTION assistant_evidence.record_native_media_observation(p_observation jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid;t public.assistant_native_file_intents%ROWTYPE;v public.assistant_native_file_observations%ROWTYPE;kind text;observed timestamptz;
BEGIN
 IF session_user<>'assistant_evidence_login' THEN RAISE EXCEPTION 'Restricted observer required' USING ERRCODE='42501'; END IF;
 IF NOT coalesce(public.assistant_wf_keys(p_observation,ARRAY['ticket_id','nonce','generation','result','observed_at','checksum','byte_size','bucket_id'])
 AND p_observation ?& ARRAY['ticket_id','nonce','generation','result','observed_at'],false) OR octet_length(p_observation::text)>4096 OR jsonb_typeof(p_observation->'generation') IS DISTINCT FROM 'number'
 OR p_observation->>'generation' !~ '^[1-9][0-9]*$' THEN
  RAISE EXCEPTION 'Closed native observation required' USING ERRCODE='22023'; END IF;
 SELECT owner INTO o FROM public.assistant_native_file_intents WHERE id=(p_observation->>'ticket_id')::uuid;
 IF o IS NULL THEN RAISE EXCEPTION 'Actual native ticket unavailable' USING ERRCODE='P0002'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 SELECT * INTO STRICT t FROM public.assistant_native_file_intents WHERE owner=o AND id=(p_observation->>'ticket_id')::uuid FOR UPDATE;
 IF t.nonce IS DISTINCT FROM (p_observation->>'nonce')::uuid OR t.generation IS DISTINCT FROM (p_observation->>'generation')::int
 OR t.state='issued' THEN RAISE EXCEPTION 'Claimed correlated native operation required' USING ERRCODE='40001'; END IF;
 kind:=p_observation->>'result';observed:=(p_observation->>'observed_at')::timestamptz;
 IF kind IS NULL OR kind NOT IN ('bytes_verified','absent_after_delete','outcome_unknown') OR observed IS NULL
 OR p_observation->>'observed_at'!~'(Z|[+-][0-9]{2}:[0-9]{2})$'
 OR (kind='bytes_verified' AND (t.operation<>'upload' OR p_observation->>'checksum' IS DISTINCT FROM t.target->>'checksum'
  OR p_observation->>'bucket_id' IS DISTINCT FROM t.bucket_id OR jsonb_typeof(p_observation->'byte_size') IS DISTINCT FROM 'number' OR (p_observation->>'byte_size')::int IS DISTINCT FROM (t.target->>'byte_size')::int))
 OR (kind='absent_after_delete' AND (t.operation<>'delete' OR p_observation->>'bucket_id' IS DISTINCT FROM t.bucket_id
  OR p_observation->>'checksum' IS NOT NULL OR p_observation->>'byte_size' IS NOT NULL
  OR NOT EXISTS(SELECT 1 FROM public.assistant_native_media_deletions WHERE owner=o AND native_ticket_id=t.id AND bucket_id=t.bucket_id AND object_ref=t.object_ref)))
 OR (kind='outcome_unknown' AND (p_observation->>'checksum' IS NOT NULL OR p_observation->>'byte_size' IS NOT NULL OR p_observation->>'bucket_id' IS NOT NULL)) THEN
  RAISE EXCEPTION 'Actual native observation binding differs' USING ERRCODE='22023'; END IF;
 SELECT * INTO v FROM public.assistant_native_file_observations WHERE ticket_id=t.id AND generation=t.generation AND result<>'outcome_unknown';
 IF NOT FOUND THEN
  INSERT INTO public.assistant_native_file_observations(id,owner,ticket_id,generation,result,checksum,byte_size,bucket_id,observed_at)
   VALUES(gen_random_uuid(),o,t.id,t.generation,kind,p_observation->>'checksum',(p_observation->>'byte_size')::int,p_observation->>'bucket_id',observed)
   ON CONFLICT(ticket_id,generation,result) DO NOTHING;
  SELECT * INTO STRICT v FROM public.assistant_native_file_observations WHERE ticket_id=t.id AND generation=t.generation AND result=kind;
  UPDATE public.assistant_native_file_intents SET state=CASE WHEN kind='outcome_unknown' THEN 'unknown' ELSE 'settled' END WHERE owner=o AND id=t.id;
 ELSIF kind<>'outcome_unknown' AND v.result<>kind THEN RAISE EXCEPTION 'Native terminal observation cannot change' USING ERRCODE='23505'; END IF;
 RETURN jsonb_build_object('family','native_object','ticket_id',t.id,'verification_id',v.id,'generation',t.generation,'result',v.result);
END $$;
ALTER FUNCTION assistant_evidence.record_native_media_observation(jsonb) OWNER TO assistant_evidence_owner;
REVOKE ALL ON FUNCTION assistant_evidence.record_native_media_observation(jsonb) FROM PUBLIC,anon,authenticated,service_role,assistant_workflow_owner,assistant_message_owner;
GRANT EXECUTE ON FUNCTION assistant_evidence.record_native_media_observation(jsonb) TO assistant_evidence_login;

CREATE FUNCTION public.assistant_native_file_reference(p_owner uuid,p_bucket text,p_path text,p_checksum text,p_size integer) RETURNS boolean
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE t public.assistant_native_file_intents%ROWTYPE;
BEGIN
 IF p_owner IS DISTINCT FROM public.assistant_patient_uid() THEN RAISE EXCEPTION 'Owned native reference required' USING ERRCODE='42501'; END IF;
 IF EXISTS(SELECT 1 FROM public.assistant_native_media_deletions WHERE owner=p_owner AND bucket_id=p_bucket AND object_ref=p_path) THEN
  RAISE EXCEPTION 'Deleting native file cannot be referenced' USING ERRCODE='40001'; END IF;
 SELECT i.* INTO t FROM public.assistant_native_file_intents i JOIN public.assistant_native_file_observations v
  ON v.owner=i.owner AND v.ticket_id=i.id AND v.generation=i.generation
  WHERE i.owner=p_owner AND i.bucket_id=p_bucket AND i.object_ref=p_path AND i.operation='upload' AND i.state='settled'
  AND v.result='bytes_verified' AND v.checksum=p_checksum AND v.bucket_id=p_bucket AND v.byte_size=(i.target->>'byte_size')::int
  AND i.target->>'checksum'=p_checksum AND (p_size IS NULL OR p_size=v.byte_size);
 IF NOT FOUND THEN RETURN false; END IF;
 UPDATE public.assistant_native_file_intents SET published=true WHERE owner=p_owner AND id=t.id;
 RETURN true;
END $$;
CREATE FUNCTION public.assistant_native_file_ack(p_owner uuid,p_bucket text,p_path text,p_ref jsonb) RETURNS boolean
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE t public.assistant_native_file_intents%ROWTYPE;current_native jsonb;
BEGIN
 IF p_owner IS DISTINCT FROM public.assistant_patient_uid() THEN RAISE EXCEPTION 'Owned cleanup acknowledgement required' USING ERRCODE='42501'; END IF;
 SELECT i.* INTO t FROM public.assistant_native_file_intents i JOIN public.assistant_native_file_observations v
  ON v.owner=i.owner AND v.ticket_id=i.id AND v.generation=i.generation
  WHERE i.owner=p_owner AND i.bucket_id=p_bucket AND i.object_ref=p_path AND i.operation='delete' AND i.state='settled'
  AND v.result='absent_after_delete' AND v.bucket_id=p_bucket;
 IF NOT FOUND THEN RETURN false; END IF;
 current_native:=public.assistant_native_file_delete_current(p_owner,p_bucket,p_path);
 IF current_native->'ref' IS DISTINCT FROM t.native_ref OR current_native->>'hash' IS DISTINCT FROM t.native_hash OR t.native_ref IS DISTINCT FROM p_ref
 OR NOT EXISTS(SELECT 1 FROM public.assistant_native_media_deletions WHERE owner=p_owner AND bucket_id=p_bucket AND object_ref=p_path AND native_ticket_id=t.id) THEN
  RAISE EXCEPTION 'Native cleanup receipt/reference changed' USING ERRCODE='40001'; END IF;
 RETURN true;
END $$;

-- Native publication and acknowledgement adopt facts in their existing owner transaction.
CREATE OR REPLACE FUNCTION public.assistant_media_reference_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=public.assistant_patient_uid();path text;bucket text;image jsonb;native_id uuid;med uuid;v_checksum text;native_size integer;
BEGIN
 IF o IS NULL OR NEW.patient_id IS DISTINCT FROM o THEN RAISE EXCEPTION 'Verified owned reference required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 IF TG_TABLE_NAME='medication_images' THEN
  IF TG_OP='UPDATE' THEN
   IF NEW.data->>'storage_path' IS NOT DISTINCT FROM OLD.data->>'storage_path' AND NEW.source_id IS NOT DISTINCT FROM OLD.source_id THEN RETURN NEW; END IF;
  END IF;
  path:=NEW.data->>'storage_path';bucket:='visual-references';native_id:=NEW.id;med:=NEW.medication_id;v_checksum:=NEW.data->>'checksum';
 ELSIF TG_TABLE_NAME='medication_library_files' THEN
  IF TG_OP='UPDATE' THEN
   IF NEW.storage_path IS NOT DISTINCT FROM OLD.storage_path AND NEW.source_document_id IS NOT DISTINCT FROM OLD.source_document_id
   AND NEW.regimen_version_id IS NOT DISTINCT FROM OLD.regimen_version_id THEN RETURN NEW; END IF;
  END IF;
  path:=NEW.storage_path;bucket:='medication-sources';native_id:=NEW.id;med:=NEW.medication_id;v_checksum:=NEW.checksum;native_size:=NEW.byte_size;
 ELSE
  -- Source association may reference several images; reject any deleting key.
  IF EXISTS(SELECT 1 FROM public.medication_images i JOIN public.assistant_native_media_deletions d
   ON d.owner=i.patient_id AND d.bucket_id='visual-references' AND d.object_ref=i.data->>'storage_path'
   WHERE i.patient_id=o AND i.source_id=NEW.source_id) THEN RAISE EXCEPTION 'Deleting source cannot acquire new associations' USING ERRCODE='40001'; END IF;
  RETURN NEW;
 END IF;
 IF path IS NULL OR EXISTS(SELECT 1 FROM public.assistant_native_media_deletions d WHERE d.owner=o AND d.bucket_id=bucket AND d.object_ref=path) THEN
  RAISE EXCEPTION 'Deleting native object cannot acquire references' USING ERRCODE='40001'; END IF;
 IF NOT public.assistant_native_file_reference(o,bucket,path,v_checksum,native_size)
 AND NOT EXISTS(SELECT 1 FROM public.assistant_media_copy_tickets t JOIN public.assistant_media_copy_verifications v ON v.owner=t.owner AND v.ticket_id=t.id AND v.generation=t.generation
  WHERE t.owner=o AND t.bucket_id=bucket AND t.object_ref=path AND t.target->>'native_id'=native_id::text AND t.target->>'medication_id'=med::text
  AND t.target->>'checksum'=v_checksum AND v.result='bytes_verified' AND v.checksum=v_checksum AND v.bucket_id=bucket
  AND v.byte_size=(t.target->>'byte_size')::int AND (native_size IS NULL OR native_size=v.byte_size) AND v.source_checksum=t.source_checksum) THEN
  RAISE EXCEPTION 'Actual independently verified native bytes required' USING ERRCODE='40001'; END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION public.assistant_media_ack(p_id uuid,p_photo boolean) RETURNS void
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE o uuid:=public.assistant_patient_uid();t public.assistant_media_delete_tickets%ROWTYPE;v public.assistant_media_delete_verifications%ROWTYPE;result jsonb;n jsonb;path text;bucket text;ref jsonb;
BEGIN
 IF o IS NULL OR public.assistant_patient_role() IS DISTINCT FROM 'authenticated' THEN RAISE EXCEPTION 'Verified owner required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 n:=public.assistant_media_native(o,p_photo,p_id);
 path:=n->>'storage_path';bucket:=CASE WHEN p_photo THEN 'visual-references' ELSE 'medication-sources' END;
 ref:=jsonb_build_object('kind','file','id',p_id,'version',coalesce(n->'metadata_version',n->'version'));
 IF public.assistant_native_file_ack(o,bucket,path,ref) THEN
  IF p_photo THEN PERFORM public.assistant_media_photo_ack_legacy_031(p_id);
  ELSE PERFORM public.assistant_media_pdf_ack_legacy_031(p_id); END IF;
  RETURN;
 END IF;
 SELECT * INTO t FROM public.assistant_media_delete_tickets WHERE owner=o AND native_ref->>'id'=p_id::text AND media_kind=CASE WHEN p_photo THEN 'photo' ELSE 'pdf' END;
 SELECT p.* INTO v FROM public.assistant_media_delete_verifications p WHERE p.owner=o AND p.ticket_id=t.id AND p.generation=t.generation AND p.result='absent_after_delete' AND p.bucket_id=t.bucket_id;
 IF t.owner IS NULL OR v.owner IS NULL THEN RAISE EXCEPTION 'Independent native deletion proof required' USING ERRCODE='40001'; END IF;
 result:=public.assistant_media_cleanup_command(jsonb_build_object('kind','settle','reference',jsonb_build_object('family','native_media_delete',
  'ticket_id',t.id,'verification_id',v.id,'generation',v.generation,'result',v.result)));
 IF result ? 'error' THEN RAISE EXCEPTION 'Native cleanup settlement unavailable' USING ERRCODE='40001'; END IF;
END $$;
CREATE OR REPLACE FUNCTION public.assistant_media_delete_current(p_owner uuid,p_action uuid) RETURNS jsonb
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
 IF EXISTS(SELECT 1 FROM public.assistant_native_file_intents WHERE owner=p_owner AND bucket_id=bucket AND object_ref=path
  AND operation='upload' AND state<>'settled') THEN RAISE EXCEPTION 'Unresolved ordinary native writer protected' USING ERRCODE='40001'; END IF;
 RETURN n;
END $$;

-- Preserve the existing native signature, owner and ACL. An ACK cannot invent absence.
CREATE OR REPLACE FUNCTION public.ack_draft_image_cleanup(p_kind text,p_id uuid,p_path text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=public.assistant_patient_uid();r public.draft_deletion_receipts%ROWTYPE;ref jsonb;
BEGIN
 IF o IS NULL OR public.assistant_patient_role() IS DISTINCT FROM 'authenticated' THEN RAISE EXCEPTION 'Verified owner required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 SELECT * INTO r FROM public.draft_deletion_receipts WHERE patient_id=o AND kind=p_kind AND target_id=p_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Owned draft deletion receipt required' USING ERRCODE='P0002'; END IF;
 IF NOT p_path=ANY(r.storage_paths) THEN RETURN; END IF;
 ref:=jsonb_build_object('kind',CASE WHEN p_kind='draft' THEN 'regimen' ELSE 'enrollment_task' END,'id',p_id);
 IF NOT public.assistant_native_file_ack(o,'visual-references',p_path,ref) THEN
  RAISE EXCEPTION 'Independently verified native draft absence required' USING ERRCODE='40001'; END IF;
 UPDATE public.draft_deletion_receipts SET storage_paths=array_remove(storage_paths,p_path) WHERE patient_id=o AND kind=p_kind AND target_id=p_id;
END $$;
DO $$ DECLARE signature text; BEGIN
 FOREACH signature IN ARRAY ARRAY['assistant_native_file_target(uuid,jsonb,boolean)',
 'assistant_native_file_delete_current(uuid,text,text)','assistant_native_file_projection(uuid)','assistant_native_file_proof(uuid)',
 'assistant_native_file_reference(uuid,text,text,text,integer)','assistant_native_file_ack(uuid,text,text,jsonb)'] LOOP
  EXECUTE 'ALTER FUNCTION public.'||signature||' OWNER TO assistant_workflow_owner';
  EXECUTE 'REVOKE ALL ON FUNCTION public.'||signature||' FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner';
 END LOOP;
END $$;
-- Existing native-reference/ACK owners and ACL are preserved; no new clinical grants.
COMMIT;
