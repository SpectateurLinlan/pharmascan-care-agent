-- REVIEW DRAFT, NOT APPLIED. Requires 035 and scoped SQL/security approval.
-- Manual, unactivated preparations only. RPC execution is deliberately NOT granted.
-- No Storage, secrets, provider, notification, historical-dose or feature enablement.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';

CREATE TABLE public.assistant_enrollment_generations (
 owner uuid PRIMARY KEY REFERENCES public.patient_profiles(user_id),
 revision bigint NOT NULL DEFAULT 0 CHECK(revision>=0)
);
CREATE TABLE public.assistant_enrollment_operations (
 owner uuid NOT NULL REFERENCES public.patient_profiles(user_id), action_key uuid NOT NULL,
 workflow_task_id uuid NOT NULL, binding_revision int NOT NULL CHECK(binding_revision>0),
 binding_digest text NOT NULL CHECK(binding_digest ~ '^[a-f0-9]{64}$'),
 regimen_id uuid NOT NULL, medication_id uuid NOT NULL, source_id uuid NOT NULL,
 version_no int NOT NULL CHECK(version_no>0),
 PRIMARY KEY(owner,action_key), UNIQUE(owner,regimen_id), UNIQUE(owner,workflow_task_id,binding_revision)
 -- No task-body FK: 035 must still erase revoked task fields. Minimal receipts survive.
 -- Owned clinical bindings are checked by the fixed publisher; reads recheck current rows.
);
ALTER TABLE public.assistant_enrollment_generations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assistant_enrollment_generations FORCE ROW LEVEL SECURITY;
ALTER TABLE public.assistant_enrollment_operations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assistant_enrollment_operations FORCE ROW LEVEL SECURITY;
CREATE POLICY assistant_enrollment_generation_owner ON public.assistant_enrollment_generations
 FOR SELECT TO authenticated USING(owner=(SELECT auth.uid()));
CREATE POLICY assistant_enrollment_operation_owner ON public.assistant_enrollment_operations
 FOR SELECT TO authenticated USING(owner=(SELECT auth.uid()));
REVOKE ALL ON public.assistant_enrollment_generations,public.assistant_enrollment_operations
 FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT ON public.assistant_enrollment_generations,public.assistant_enrollment_operations TO authenticated;

CREATE FUNCTION public.assistant_enrollment_generation() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid;
BEGIN
 o:=CASE WHEN TG_OP='DELETE' THEN OLD.patient_id ELSE NEW.patient_id END;
 IF TG_OP='UPDATE' AND OLD.patient_id IS DISTINCT FROM NEW.patient_id THEN
  RAISE EXCEPTION 'Enrollment ownership is immutable';
 END IF;
 -- Same owner lock as 035; existing clinical writes participate in the fence.
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 INSERT INTO public.assistant_enrollment_generations(owner,revision) VALUES(o,1)
 ON CONFLICT(owner) DO UPDATE SET revision=public.assistant_enrollment_generations.revision+1;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER assistant_enrollment_generation_sources BEFORE INSERT OR UPDATE OR DELETE ON public.source_documents
 FOR EACH ROW EXECUTE FUNCTION public.assistant_enrollment_generation();
CREATE TRIGGER assistant_enrollment_generation_fields BEFORE INSERT OR UPDATE OR DELETE ON public.source_fields
 FOR EACH ROW EXECUTE FUNCTION public.assistant_enrollment_generation();
CREATE TRIGGER assistant_enrollment_generation_medications BEFORE INSERT OR UPDATE OR DELETE ON public.patient_medications
 FOR EACH ROW EXECUTE FUNCTION public.assistant_enrollment_generation();
CREATE TRIGGER assistant_enrollment_generation_regimens BEFORE INSERT OR UPDATE OR DELETE ON public.regimen_versions
 FOR EACH ROW EXECUTE FUNCTION public.assistant_enrollment_generation();

CREATE FUNCTION public.assistant_enrollment_assert_current(o uuid,rid uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE b public.assistant_enrollment_operations%ROWTYPE; t jsonb; c jsonb; n int;
BEGIN
 SELECT * INTO b FROM public.assistant_enrollment_operations WHERE owner=o AND regimen_id=rid;
 IF NOT FOUND THEN RETURN; END IF; -- Legacy, unbound enrollments retain their original guards.
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 IF auth.uid() IS DISTINCT FROM o THEN RAISE EXCEPTION 'Current enrollment identity is required'; END IF;
 SELECT data INTO t FROM public.assistant_workflow_tasks WHERE owner=o AND id=b.workflow_task_id;
 SELECT data INTO c FROM public.assistant_workflow_operations
  WHERE owner=o AND record_type='control' AND task_id=b.workflow_task_id AND id=b.workflow_task_id;
 SELECT version_no INTO n FROM public.regimen_versions WHERE patient_id=o AND id=rid;
 IF t IS NULL OR c IS NULL OR c->>'mode' IS DISTINCT FROM 'allowed'
 OR c->>'revoked' IS DISTINCT FROM 'false' OR c->>'status' IS DISTINCT FROM 'idle'
 OR t->>'state' IS DISTINCT FROM 'awaiting_confirmation' OR n IS DISTINCT FROM b.version_no
 OR NOT (t->'business_refs' @> jsonb_build_array(jsonb_build_object('kind','regimen','id',rid,'version',n))) THEN
  RAISE EXCEPTION 'Enrollment review changed; reopen the current saved draft';
 END IF;
END $$;
CREATE FUNCTION public.assistant_enrollment_review_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE rid uuid; sid uuid;
BEGIN
 IF TG_TABLE_NAME='confirmation_challenges' THEN
  IF NEW.action='activate_regimen' THEN
   PERFORM public.assistant_enrollment_assert_current(NEW.patient_id,NEW.regimen_id);
  END IF;
 ELSIF TG_TABLE_NAME='regimen_versions' THEN
  IF NEW.state='active' THEN PERFORM public.assistant_enrollment_assert_current(NEW.patient_id,NEW.id); END IF;
 ELSE
  IF TG_TABLE_NAME='source_documents' THEN sid:=NEW.id; ELSE sid:=NEW.source_id; END IF;
  FOR rid IN SELECT regimen_id FROM public.assistant_enrollment_operations
   WHERE owner=NEW.patient_id AND source_id=sid
  LOOP PERFORM public.assistant_enrollment_assert_current(NEW.patient_id,rid); END LOOP;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER assistant_enrollment_guard_source BEFORE UPDATE ON public.source_documents
 FOR EACH ROW EXECUTE FUNCTION public.assistant_enrollment_review_guard();
CREATE TRIGGER assistant_enrollment_guard_field BEFORE UPDATE ON public.source_fields
 FOR EACH ROW EXECUTE FUNCTION public.assistant_enrollment_review_guard();
CREATE TRIGGER assistant_enrollment_guard_challenge BEFORE INSERT OR UPDATE ON public.confirmation_challenges
 FOR EACH ROW EXECUTE FUNCTION public.assistant_enrollment_review_guard();
CREATE TRIGGER assistant_enrollment_guard_activation BEFORE UPDATE ON public.regimen_versions
 FOR EACH ROW EXECUTE FUNCTION public.assistant_enrollment_review_guard();

CREATE FUNCTION public.assistant_enrollment_prepare_once(
 p_action_key uuid,p_task_id uuid,p_expected_task_revision int,p_expected_clinical_revision bigint,
 p_binding_digest text,p_source_checksum text,p_prepared jsonb
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=auth.uid(); b public.assistant_enrollment_operations%ROWTYPE;
 t jsonb; c jsonb; s jsonb; m jsonb; r jsonb; f jsonb; result jsonb; g bigint; next_version int; sid uuid; mid uuid; rid uuid;
BEGIN
 IF o IS NULL OR coalesce(nullif(current_setting('request.jwt.claim.role',true),''),
  current_setting('request.jwt.claims',true)::jsonb->>'role') IS DISTINCT FROM 'authenticated' THEN
  RETURN jsonb_build_object('error','invalid');
 END IF;
 IF p_action_key IS NULL OR p_task_id IS NULL OR p_binding_digest !~ '^[a-f0-9]{64}$'
 OR p_source_checksum !~ '^[a-f0-9]{64}$' OR p_binding_digest IS NULL OR p_source_checksum IS NULL
 OR jsonb_typeof(p_prepared) IS DISTINCT FROM 'object' OR octet_length(convert_to(p_prepared::text,'UTF8'))>98304
 OR NOT public.assistant_wf_keys(p_prepared,ARRAY['workflow_task_id','workflow_revision','source','result',
 'create_medication','already_persisted','attachment_ids','source_candidate_index']) THEN
  RETURN jsonb_build_object('error','invalid');
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 SELECT * INTO b FROM public.assistant_enrollment_operations WHERE owner=o AND action_key=p_action_key;
 IF FOUND THEN
  IF b.binding_digest IS DISTINCT FROM p_binding_digest OR b.workflow_task_id IS DISTINCT FROM p_task_id THEN
   RETURN jsonb_build_object('error','duplicate');
  END IF;
 ELSE
  SELECT data INTO t FROM public.assistant_workflow_tasks WHERE owner=o AND id=p_task_id FOR UPDATE;
  SELECT data INTO c FROM public.assistant_workflow_operations WHERE owner=o AND record_type='control'
   AND task_id=p_task_id AND id=p_task_id FOR UPDATE;
  SELECT revision INTO g FROM public.assistant_enrollment_generations WHERE owner=o;
  IF t IS NULL OR c IS NULL OR (t->>'revision')::int IS DISTINCT FROM p_expected_task_revision
  OR (c->>'revision')::int IS DISTINCT FROM p_expected_task_revision
  OR coalesce(g,0) IS DISTINCT FROM p_expected_clinical_revision
  OR c->>'mode' IS DISTINCT FROM 'allowed' OR c->>'revoked' IS DISTINCT FROM 'false'
  OR c->>'status' IS DISTINCT FROM 'idle' OR t->>'state' IS DISTINCT FROM 'ready_for_review'
  OR t->>'capability_id' IS DISTINCT FROM 'medication.enroll' THEN RETURN jsonb_build_object('error','stale'); END IF;
  s:=p_prepared->'source'; result:=p_prepared->'result'; m:=result->'medication'; r:=result->'regimen';
  IF p_prepared->>'workflow_task_id' IS DISTINCT FROM p_task_id::text
  OR (p_prepared->>'workflow_revision')::int IS DISTINCT FROM p_expected_task_revision
  OR p_prepared->>'already_persisted' IS DISTINCT FROM 'false'
  OR p_prepared->'attachment_ids' IS DISTINCT FROM '[]'::jsonb
  OR nullif(p_prepared->'source_candidate_index','null'::jsonb) IS NOT NULL
  OR NOT public.assistant_wf_keys(result,ARRAY['medication','regimen','source_fields','missing_instructions'])
  OR NOT public.assistant_wf_keys(s,ARRAY['id','patient_id','source_kind','review_status','reviewed_at','dose_basis','extraction_evidence','demo_only'])
  OR NOT public.assistant_wf_keys(m,ARRAY['id','patient_id','display_name','product_id','source_id','identity_status','archived_at','demo_only'])
  OR NOT public.assistant_wf_keys(r,ARRAY['id','patient_id','patient_medication_id','source_id','version_no','state',
   'dose_amount','dose_unit','frequency_rule','is_prn','route','food_instruction','effective_from','effective_to',
   'course_start_date','course_end_date','patient_edited','supersedes_id','confirmation_challenge_id','created_at','evidence_task_id','demo_only'])
  OR s->>'patient_id' IS DISTINCT FROM o::text OR m->>'patient_id' IS DISTINCT FROM o::text
  OR r->>'patient_id' IS DISTINCT FROM o::text OR s->>'source_kind' IS DISTINCT FROM 'user_manual'
  OR s->>'review_status' IS DISTINCT FROM 'extracted' OR nullif(s->'reviewed_at','null'::jsonb) IS NOT NULL
  OR nullif(s->'extraction_evidence','null'::jsonb) IS NOT NULL
  OR r->>'state' NOT IN ('draft','pending_clarification')
  OR nullif(r->'effective_from','null'::jsonb) IS NOT NULL OR nullif(r->'effective_to','null'::jsonb) IS NOT NULL
  OR nullif(r->'confirmation_challenge_id','null'::jsonb) IS NOT NULL
  OR nullif(r->'evidence_task_id','null'::jsonb) IS NOT NULL
  OR jsonb_typeof(result->'source_fields') IS DISTINCT FROM 'array'
  OR jsonb_array_length(result->'source_fields')>20 THEN RETURN jsonb_build_object('error','invalid'); END IF;
  sid:=(s->>'id')::uuid; mid:=(m->>'id')::uuid; rid:=(r->>'id')::uuid;
  IF sid IS NULL OR mid IS NULL OR rid IS NULL OR (r->>'source_id')::uuid IS DISTINCT FROM sid
  OR (r->>'patient_medication_id')::uuid IS DISTINCT FROM mid THEN RETURN jsonb_build_object('error','invalid'); END IF;
  IF (p_prepared->>'create_medication')::boolean THEN
   IF m->>'identity_status' IS DISTINCT FROM 'unverified' OR (m->>'source_id')::uuid IS DISTINCT FROM sid
   OR nullif(m->'archived_at','null'::jsonb) IS NOT NULL OR nullif(m->'product_id','null'::jsonb) IS NOT NULL THEN
    RETURN jsonb_build_object('error','invalid'); END IF;
  ELSE
   IF NOT EXISTS(SELECT 1 FROM public.patient_medications WHERE patient_id=o AND id=mid AND archived_at IS NULL
    AND display_name=m->>'display_name' AND source_id IS NOT DISTINCT FROM (m->>'source_id')::uuid
    AND product_id IS NOT DISTINCT FROM (m->>'product_id')::uuid) THEN RETURN jsonb_build_object('error','stale'); END IF;
  END IF;
  SELECT coalesce(max(version_no),0)+1 INTO next_version FROM public.regimen_versions WHERE patient_id=o AND patient_medication_id=mid;
  IF (r->>'version_no')::int IS DISTINCT FROM next_version THEN RETURN jsonb_build_object('error','stale'); END IF;
  INSERT INTO public.source_documents(id,patient_id,source_kind,review_status,reviewed_at,checksum,dose_basis,extraction_evidence)
   VALUES(sid,o,'user_manual','extracted',NULL,p_source_checksum,nullif(s->'dose_basis','null'::jsonb),NULL);
  FOR f IN SELECT value FROM jsonb_array_elements(result->'source_fields') LOOP
   IF NOT public.assistant_wf_keys(f,ARRAY['id','patient_id','source_id','field_name','field_value','review_status','reviewed_at','demo_only'])
   OR f->>'patient_id' IS DISTINCT FROM o::text OR (f->>'source_id')::uuid IS DISTINCT FROM sid
   OR f->>'review_status' IS DISTINCT FROM 'extracted' OR nullif(f->'reviewed_at','null'::jsonb) IS NOT NULL THEN
    RAISE EXCEPTION 'Invalid unreviewed enrollment field'; END IF;
   INSERT INTO public.source_fields(id,patient_id,source_id,field_name,field_value,evidence_locator,extraction_method,review_status)
    VALUES((f->>'id')::uuid,o,sid,f->>'field_name',f->'field_value','synthetic:field:'||(f->>'id'),'manual','extracted');
  END LOOP;
  IF (p_prepared->>'create_medication')::boolean THEN
   INSERT INTO public.patient_medications(id,patient_id,display_name,source_id,identity_status)
    VALUES(mid,o,m->>'display_name',sid,'unverified');
  END IF;
  INSERT INTO public.regimen_versions(id,patient_id,patient_medication_id,source_id,version_no,state,dose_amount,dose_unit,
   frequency_rule,is_prn,route,food_instruction,course_start_date,course_end_date,patient_edited,supersedes_id,created_at)
   VALUES(rid,o,mid,sid,next_version,r->>'state',(r->>'dose_amount')::numeric,r->>'dose_unit',nullif(r->'frequency_rule','null'::jsonb),
    (r->>'is_prn')::boolean,r->>'route',r->>'food_instruction',(r->>'course_start_date')::date,(r->>'course_end_date')::date,
    (r->>'patient_edited')::boolean,(r->>'supersedes_id')::uuid,(r->>'created_at')::timestamptz);
  INSERT INTO public.assistant_enrollment_operations(owner,action_key,workflow_task_id,binding_revision,binding_digest,
   regimen_id,medication_id,source_id,version_no) VALUES(o,p_action_key,p_task_id,p_expected_task_revision+1,p_binding_digest,rid,mid,sid,next_version)
   RETURNING * INTO b;
  -- Task association is a separate coordinator CAS. A lost CAS must reconcile this
  -- receipt; it must never replay insertion. No independent review is allowed
  -- until the task actually contains this current owned/versioned business_ref.
 END IF;
 RETURN jsonb_build_object('result',jsonb_build_object('workflow_task_id',b.workflow_task_id,'binding_digest',b.binding_digest,
  'regimen_id',b.regimen_id,'medication_id',b.medication_id,'source_id',b.source_id,'version_no',b.version_no));
EXCEPTION WHEN check_violation OR not_null_violation OR invalid_text_representation OR foreign_key_violation
 OR unique_violation OR raise_exception THEN RETURN jsonb_build_object('error','invalid');
END $$;

REVOKE ALL ON FUNCTION public.assistant_enrollment_generation() FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.assistant_enrollment_assert_current(uuid,uuid) FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.assistant_enrollment_review_guard() FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.assistant_enrollment_prepare_once(uuid,uuid,int,bigint,text,text,jsonb)
 FROM PUBLIC,anon,authenticated,service_role;
-- No execution GRANT: target, invoker/definer, concurrency, revocation and rollback tests remain gated.
COMMIT;
