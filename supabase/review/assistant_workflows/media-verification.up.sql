-- REVIEW ONLY / NOT APPLIED. I11 technical evidence dependency, after I02-I10.
-- No role creation, clinical grants, Storage policies, object I/O or scheduling.
-- Native media commands/compatibility and every target gate are separate.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';

CREATE TABLE public.assistant_media_copy_tickets (
 owner uuid NOT NULL,id uuid PRIMARY KEY,nonce uuid NOT NULL UNIQUE,task_id uuid NOT NULL,
 task_revision integer NOT NULL CHECK(task_revision>0),capability_id text NOT NULL CHECK(capability_id ~ '^[a-z][a-z0-9_.]{1,119}$'),
 attachment_id uuid NOT NULL,writer_id uuid NOT NULL,generation integer NOT NULL CHECK(generation>0),
 source_checksum text NOT NULL CHECK(source_checksum ~ '^[a-f0-9]{64}$'),
 source_byte_size integer NOT NULL CHECK(source_byte_size BETWEEN 1 AND 10485760),
 target jsonb NOT NULL CHECK(coalesce(octet_length(target::text)<=2048 AND
  public.assistant_wf_keys(target,ARRAY['owner','medication_id','native_id','media_kind','source_kind','checksum','content_type','byte_size'])
  AND target ?& ARRAY['owner','medication_id','native_id','media_kind','checksum','content_type','byte_size']
  AND target->>'owner'=owner::text AND (target->>'medication_id')::uuid IS NOT NULL
  AND (target->>'native_id')::uuid IS NOT NULL AND target->>'checksum' ~ '^[a-f0-9]{64}$'
  AND jsonb_typeof(target->'byte_size')='number' AND target->>'byte_size' ~ '^[1-9][0-9]*$'
  AND ((target->>'media_kind'='photo' AND target->>'source_kind' IS NULL AND target->>'content_type'='image/png' AND (target->>'byte_size')::bigint<=8000000)
   OR (target->>'media_kind'='source_image' AND target->>'source_kind' IN ('package','pharmacy_label','prescription')
    AND target->>'content_type'='image/png' AND (target->>'byte_size')::bigint<=8000000)
   OR (target->>'media_kind'='pdf' AND target->>'source_kind' IS NULL AND target->>'content_type'='application/pdf' AND (target->>'byte_size')::bigint<=10485760)),false)),
 bucket_id text NOT NULL CHECK(bucket_id IN ('visual-references','medication-sources')),
 object_ref text NOT NULL CHECK(length(object_ref)<=400),run_binding jsonb CHECK(run_binding IS NULL OR coalesce(
  octet_length(run_binding::text)<=256 AND public.assistant_wf_keys(run_binding,ARRAY['run_id','epoch'])
  AND run_binding ?& ARRAY['run_id','epoch'] AND (run_binding->>'run_id')::uuid IS NOT NULL
  AND jsonb_typeof(run_binding->'epoch')='number' AND run_binding->>'epoch' ~ '^[1-9][0-9]*$',false)),
 expires_at timestamptz NOT NULL,state text NOT NULL DEFAULT 'issued' CHECK(state IN ('issued','inflight','unknown','settled')),
 UNIQUE(owner,id),UNIQUE(owner,writer_id),UNIQUE(owner,bucket_id,object_ref,generation),
 CHECK(bucket_id=CASE WHEN target->>'media_kind'='pdf' THEN 'medication-sources' ELSE 'visual-references' END),
 CHECK(object_ref=CASE WHEN target->>'media_kind'='pdf' THEN owner::text||'/library/'||(target->>'medication_id')||'/'||(target->>'checksum')||'.pdf'
  ELSE owner::text||'/'||(target->>'medication_id')||'/'||(target->>'checksum')||'.png' END)
);
CREATE TABLE public.assistant_media_delete_tickets (
 owner uuid NOT NULL,id uuid PRIMARY KEY,nonce uuid NOT NULL UNIQUE,generation integer NOT NULL CHECK(generation>0),
 task_id uuid NOT NULL,task_revision integer NOT NULL CHECK(task_revision>0),action_key uuid NOT NULL,
 media_kind text NOT NULL CHECK(media_kind IN ('photo','pdf')),medication_id uuid NOT NULL,
 native_ref jsonb NOT NULL CHECK(coalesce(public.assistant_wf_keys(native_ref,ARRAY['kind','id','version'])
  AND native_ref ?& ARRAY['kind','id','version'] AND native_ref->>'kind'='file'
  AND (native_ref->>'id')::uuid IS NOT NULL AND jsonb_typeof(native_ref->'version')='number'
  AND native_ref->>'version' ~ '^[1-9][0-9]*$',false)),
 bucket_id text NOT NULL CHECK(bucket_id IN ('visual-references','medication-sources')),
 object_ref text NOT NULL CHECK(length(object_ref)<=400),checksum text NOT NULL CHECK(checksum ~ '^[a-f0-9]{64}$'),
 expires_at timestamptz NOT NULL,state text NOT NULL DEFAULT 'issued' CHECK(state IN ('issued','inflight','unknown','settled')),
 UNIQUE(owner,id),UNIQUE(owner,action_key),UNIQUE(owner,bucket_id,object_ref),
 FOREIGN KEY(owner,action_key) REFERENCES public.assistant_business_receipts(owner,action_key),
 CHECK(bucket_id=CASE WHEN media_kind='photo' THEN 'visual-references' ELSE 'medication-sources' END),
 CHECK(object_ref=CASE WHEN media_kind='photo' THEN owner::text||'/'||medication_id::text||'/'||checksum||'.png'
  ELSE owner::text||'/library/'||medication_id::text||'/'||checksum||'.pdf' END)
);
CREATE TABLE public.assistant_native_media_deletions (
 owner uuid NOT NULL,bucket_id text NOT NULL,object_ref text NOT NULL,ticket_id uuid,native_ticket_id uuid,
 PRIMARY KEY(owner,bucket_id,object_ref),FOREIGN KEY(owner,ticket_id) REFERENCES public.assistant_media_delete_tickets(owner,id),
 CHECK(num_nonnulls(ticket_id,native_ticket_id)=1)
);
CREATE TABLE public.assistant_media_copy_verifications (
 id uuid PRIMARY KEY,owner uuid NOT NULL,ticket_id uuid NOT NULL,generation integer NOT NULL CHECK(generation>0),
 result text NOT NULL CHECK(result IN ('bytes_verified','definitely_not_started','outcome_unknown')),
 source_checksum text,checksum text,byte_size integer,bucket_id text,observed_at timestamptz NOT NULL,
 UNIQUE(ticket_id,generation,result),FOREIGN KEY(owner,ticket_id) REFERENCES public.assistant_media_copy_tickets(owner,id),
 CHECK(coalesce(CASE WHEN result='bytes_verified' THEN source_checksum IS NOT NULL AND source_checksum ~ '^[a-f0-9]{64}$'
  AND checksum IS NOT NULL AND checksum ~ '^[a-f0-9]{64}$' AND byte_size BETWEEN 1 AND 10485760
  AND bucket_id IN ('visual-references','medication-sources')
 ELSE source_checksum IS NULL AND checksum IS NULL AND byte_size IS NULL AND bucket_id IS NULL END,false))
);
CREATE TABLE public.assistant_media_delete_verifications (
 id uuid PRIMARY KEY,owner uuid NOT NULL,ticket_id uuid NOT NULL,generation integer NOT NULL CHECK(generation>0),
 result text NOT NULL CHECK(result IN ('absent_after_delete','outcome_unknown')),bucket_id text,observed_at timestamptz NOT NULL,
 UNIQUE(ticket_id,generation,result),FOREIGN KEY(owner,ticket_id) REFERENCES public.assistant_media_delete_tickets(owner,id),
 CHECK(CASE WHEN result='absent_after_delete' THEN bucket_id IS NOT NULL AND bucket_id IN ('visual-references','medication-sources')
  ELSE bucket_id IS NULL END)
);
-- The restricted login receives no table access, membership or clinical rights.
-- Its definer owner can read issued technical metadata and settle only states.
DO $$ DECLARE relation_name text; BEGIN
 FOREACH relation_name IN ARRAY ARRAY['assistant_media_copy_tickets','assistant_media_delete_tickets',
  'assistant_native_media_deletions','assistant_media_copy_verifications','assistant_media_delete_verifications'] LOOP
  EXECUTE format('ALTER TABLE public.%I OWNER TO assistant_evidence_owner',relation_name);
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',relation_name);
  EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',relation_name);
  EXECUTE format('CREATE POLICY assistant_media_technical_owner ON public.%I TO assistant_evidence_owner USING(true) WITH CHECK(true)',relation_name);
  EXECUTE format('CREATE POLICY assistant_media_patient_command ON public.%I TO assistant_workflow_owner USING(owner=auth.uid()) WITH CHECK(owner=auth.uid())',relation_name);
  EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_workflow_owner',relation_name);
 END LOOP;
END $$;
GRANT SELECT,INSERT,UPDATE ON public.assistant_media_copy_tickets,public.assistant_media_delete_tickets TO assistant_workflow_owner;
GRANT SELECT,INSERT ON public.assistant_native_media_deletions TO assistant_workflow_owner;
GRANT SELECT ON public.assistant_media_copy_verifications,public.assistant_media_delete_verifications TO assistant_workflow_owner;

CREATE FUNCTION assistant_evidence.media_ticket_immutable() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
BEGIN
 IF TG_OP='DELETE' OR (to_jsonb(NEW)-'state') IS DISTINCT FROM (to_jsonb(OLD)-'state')
 OR NOT ((OLD.state='issued' AND NEW.state='inflight')
  OR (OLD.state IN ('inflight','unknown') AND NEW.state IN ('unknown','settled'))
  OR (OLD.state='settled' AND NEW.state='settled')) THEN
  RAISE EXCEPTION 'Media operation binding/state is immutable' USING ERRCODE='40001'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION assistant_evidence.media_proof_immutable() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
BEGIN RAISE EXCEPTION 'Media evidence and deletion exclusions are append-only' USING ERRCODE='42501'; END $$;
CREATE TRIGGER assistant_media_copy_binding BEFORE UPDATE OR DELETE ON public.assistant_media_copy_tickets
 FOR EACH ROW EXECUTE FUNCTION assistant_evidence.media_ticket_immutable();
CREATE TRIGGER assistant_media_delete_binding BEFORE UPDATE OR DELETE ON public.assistant_media_delete_tickets
 FOR EACH ROW EXECUTE FUNCTION assistant_evidence.media_ticket_immutable();
DO $$ DECLARE relation_name text; BEGIN
 FOREACH relation_name IN ARRAY ARRAY['assistant_media_copy_verifications','assistant_media_delete_verifications','assistant_native_media_deletions'] LOOP
  EXECUTE format('CREATE TRIGGER assistant_media_proof_immutable BEFORE UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION assistant_evidence.media_proof_immutable()',relation_name);
 END LOOP;
END $$;

CREATE FUNCTION assistant_evidence.record_media_storage_observation(p_observation jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE t public.assistant_media_copy_tickets%ROWTYPE;v public.assistant_media_copy_verifications%ROWTYPE;
 o uuid;kind text;observed timestamptz;
BEGIN
 IF session_user<>'assistant_evidence_login' THEN RAISE EXCEPTION 'Restricted verification identity required' USING ERRCODE='42501'; END IF;
 IF NOT coalesce(public.assistant_wf_keys(p_observation,ARRAY['ticket_id','nonce','generation','result',
 'source_checksum','checksum','byte_size','bucket_id','observed_at']),false)
 OR NOT(p_observation ?& ARRAY['ticket_id','nonce','generation','result','observed_at'])
 OR octet_length(p_observation::text)>4096 OR jsonb_typeof(p_observation->'generation') IS DISTINCT FROM 'number'
 OR p_observation->>'generation' !~ '^[1-9][0-9]*$' THEN
  RAISE EXCEPTION 'Closed media observation required' USING ERRCODE='22023'; END IF;
 SELECT owner INTO o FROM public.assistant_media_copy_tickets WHERE id=(p_observation->>'ticket_id')::uuid;
 IF o IS NULL THEN RAISE EXCEPTION 'Media ticket unavailable' USING ERRCODE='P0002'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 SELECT * INTO STRICT t FROM public.assistant_media_copy_tickets WHERE owner=o AND id=(p_observation->>'ticket_id')::uuid FOR UPDATE;
 IF t.nonce IS DISTINCT FROM (p_observation->>'nonce')::uuid OR t.generation IS DISTINCT FROM (p_observation->>'generation')::int
 OR t.state='issued' THEN RAISE EXCEPTION 'Media copy was not claimed or its binding changed' USING ERRCODE='40001'; END IF;
 kind:=p_observation->>'result';observed:=(p_observation->>'observed_at')::timestamptz;
 IF kind IS NULL OR kind NOT IN ('bytes_verified','definitely_not_started','outcome_unknown') OR observed IS NULL
 OR p_observation->>'observed_at' !~ '(Z|[+-][0-9]{2}:[0-9]{2})$'
 OR (kind='bytes_verified' AND (p_observation->>'source_checksum' IS DISTINCT FROM t.source_checksum
  OR p_observation->>'checksum' IS DISTINCT FROM t.target->>'checksum'
  OR p_observation->>'bucket_id' IS DISTINCT FROM t.bucket_id
  OR jsonb_typeof(p_observation->'byte_size') IS DISTINCT FROM 'number'
  OR (p_observation->>'byte_size')::int IS DISTINCT FROM (t.target->>'byte_size')::int))
 OR (kind<>'bytes_verified' AND (p_observation->>'source_checksum' IS NOT NULL OR p_observation->>'checksum' IS NOT NULL
  OR p_observation->>'byte_size' IS NOT NULL OR p_observation->>'bucket_id' IS NOT NULL)) THEN
  RAISE EXCEPTION 'Source/native/bucket evidence differs from issued operation' USING ERRCODE='22023'; END IF;
 SELECT * INTO v FROM public.assistant_media_copy_verifications WHERE ticket_id=t.id AND generation=t.generation AND result<>'outcome_unknown';
 IF FOUND THEN
  IF kind<>v.result AND kind<>'outcome_unknown' THEN RAISE EXCEPTION 'Conflicting native copy evidence' USING ERRCODE='40001'; END IF;
 ELSE
  INSERT INTO public.assistant_media_copy_verifications(id,owner,ticket_id,generation,result,source_checksum,checksum,byte_size,bucket_id,observed_at)
  VALUES(gen_random_uuid(),o,t.id,t.generation,kind,p_observation->>'source_checksum',p_observation->>'checksum',
   (p_observation->>'byte_size')::int,p_observation->>'bucket_id',observed) ON CONFLICT(ticket_id,generation,result) DO NOTHING;
  SELECT * INTO STRICT v FROM public.assistant_media_copy_verifications WHERE ticket_id=t.id AND generation=t.generation AND result=kind;
  UPDATE public.assistant_media_copy_tickets SET state=CASE WHEN kind='outcome_unknown' THEN 'unknown' ELSE 'settled' END WHERE id=t.id;
 END IF;
 RETURN jsonb_build_object('family','native_media','ticket_id',t.id,'verification_id',v.id,'generation',v.generation,'result',v.result);
END $$;

CREATE FUNCTION assistant_evidence.record_media_delete_observation(p_observation jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE t public.assistant_media_delete_tickets%ROWTYPE;v public.assistant_media_delete_verifications%ROWTYPE;
 o uuid;kind text;observed timestamptz;
BEGIN
 IF session_user<>'assistant_evidence_login' THEN RAISE EXCEPTION 'Restricted verification identity required' USING ERRCODE='42501'; END IF;
 IF NOT coalesce(public.assistant_wf_keys(p_observation,ARRAY['ticket_id','nonce','generation','result','bucket_id','observed_at']),false)
 OR NOT(p_observation ?& ARRAY['ticket_id','nonce','generation','result','observed_at']) OR octet_length(p_observation::text)>2048
 OR jsonb_typeof(p_observation->'generation') IS DISTINCT FROM 'number' OR p_observation->>'generation' !~ '^[1-9][0-9]*$' THEN
  RAISE EXCEPTION 'Closed media deletion observation required' USING ERRCODE='22023'; END IF;
 SELECT owner INTO o FROM public.assistant_media_delete_tickets WHERE id=(p_observation->>'ticket_id')::uuid;
 IF o IS NULL THEN RAISE EXCEPTION 'Native delete ticket unavailable' USING ERRCODE='P0002'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 SELECT * INTO STRICT t FROM public.assistant_media_delete_tickets WHERE owner=o AND id=(p_observation->>'ticket_id')::uuid FOR UPDATE;
 IF t.nonce IS DISTINCT FROM (p_observation->>'nonce')::uuid OR t.generation IS DISTINCT FROM (p_observation->>'generation')::int
 OR t.state='issued' OR NOT EXISTS(SELECT 1 FROM public.assistant_native_media_deletions d
  WHERE d.owner=o AND d.ticket_id=t.id AND d.bucket_id=t.bucket_id AND d.object_ref=t.object_ref) THEN
  RAISE EXCEPTION 'Claimed native delete exclusion required' USING ERRCODE='40001'; END IF;
 kind:=p_observation->>'result';observed:=(p_observation->>'observed_at')::timestamptz;
 IF kind IS NULL OR kind NOT IN ('absent_after_delete','outcome_unknown') OR observed IS NULL
 OR p_observation->>'observed_at' !~ '(Z|[+-][0-9]{2}:[0-9]{2})$'
 OR (kind='absent_after_delete' AND p_observation->>'bucket_id' IS DISTINCT FROM t.bucket_id)
 OR (kind='outcome_unknown' AND p_observation->>'bucket_id' IS NOT NULL) THEN
  RAISE EXCEPTION 'Observed native deletion/bucket does not match its operation' USING ERRCODE='22023'; END IF;
 SELECT * INTO v FROM public.assistant_media_delete_verifications WHERE ticket_id=t.id AND generation=t.generation AND result='absent_after_delete';
 IF NOT FOUND THEN
  INSERT INTO public.assistant_media_delete_verifications(id,owner,ticket_id,generation,result,bucket_id,observed_at)
  VALUES(gen_random_uuid(),o,t.id,t.generation,kind,p_observation->>'bucket_id',observed)
  ON CONFLICT(ticket_id,generation,result) DO NOTHING;
  SELECT * INTO STRICT v FROM public.assistant_media_delete_verifications WHERE ticket_id=t.id AND generation=t.generation AND result=kind;
  UPDATE public.assistant_media_delete_tickets SET state=CASE WHEN kind='outcome_unknown' THEN 'unknown' ELSE 'settled' END WHERE id=t.id;
 END IF;
 RETURN jsonb_build_object('family','native_media_delete','ticket_id',t.id,'verification_id',v.id,'generation',v.generation,'result',v.result);
END $$;

ALTER FUNCTION assistant_evidence.media_ticket_immutable() OWNER TO assistant_evidence_owner;
ALTER FUNCTION assistant_evidence.media_proof_immutable() OWNER TO assistant_evidence_owner;
ALTER FUNCTION assistant_evidence.record_media_storage_observation(jsonb) OWNER TO assistant_evidence_owner;
ALTER FUNCTION assistant_evidence.record_media_delete_observation(jsonb) OWNER TO assistant_evidence_owner;
REVOKE ALL ON FUNCTION assistant_evidence.media_ticket_immutable(),assistant_evidence.media_proof_immutable(),
 assistant_evidence.record_media_storage_observation(jsonb),assistant_evidence.record_media_delete_observation(jsonb)
 FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_workflow_owner;
GRANT EXECUTE ON FUNCTION assistant_evidence.record_media_storage_observation(jsonb),
 assistant_evidence.record_media_delete_observation(jsonb) TO assistant_evidence_login;
GRANT USAGE ON SCHEMA assistant_evidence TO assistant_workflow_owner;
GRANT EXECUTE ON FUNCTION assistant_evidence.media_ticket_immutable(),assistant_evidence.media_proof_immutable()
 TO assistant_workflow_owner;
COMMIT;
