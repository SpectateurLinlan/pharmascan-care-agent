-- REVIEW ONLY / NOT APPLIED. I10; apply only after all target gates and approval.
-- Requires I02-I09 candidates, native034, and an ALREADY available UUIDv5 helper.
-- No extension installation, notification dispatch, schedule or history backfill.
BEGIN;
SET LOCAL lock_timeout='5s';
DO $$ BEGIN
 IF to_regprocedure('extensions.uuid_generate_v5(uuid,text)') IS NULL THEN
  RAISE EXCEPTION 'Existing extensions.uuid_generate_v5 is required; do not install it implicitly';
 END IF;
END $$;
GRANT USAGE ON SCHEMA extensions TO assistant_workflow_owner;
GRANT EXECUTE ON FUNCTION extensions.uuid_generate_v5(uuid,text) TO assistant_workflow_owner;

CREATE TABLE public.assistant_care_generations (
 owner uuid PRIMARY KEY REFERENCES public.patient_profiles(user_id), revision bigint NOT NULL DEFAULT 0 CHECK(revision>=0)
);
CREATE TABLE public.assistant_care_commands (
 owner uuid NOT NULL,action_key uuid NOT NULL,task_id uuid NOT NULL,capability_id text NOT NULL,
 binding_revision integer NOT NULL CHECK(binding_revision>=1),kind text NOT NULL CHECK(kind IN
 ('prepare_care','save_observation','delete_observation','stock','barrier','create_followup','update_followup')),
 command_digest text NOT NULL CHECK(command_digest ~ '^[0-9a-f]{64}$'),prepared_ref jsonb NOT NULL,
 domain_revision bigint NOT NULL CHECK(domain_revision>=0),snapshot_hash text CHECK(snapshot_hash ~ '^[0-9a-f]{64}$'),
 native_hash text CHECK(native_hash ~ '^[0-9a-f]{64}$'),
 PRIMARY KEY(owner,action_key),FOREIGN KEY(owner,task_id) REFERENCES public.assistant_workflow_tasks(owner,id),
 FOREIGN KEY(owner,action_key) REFERENCES public.assistant_business_receipts(owner,action_key) DEFERRABLE INITIALLY DEFERRED
);
ALTER TABLE public.assistant_care_generations OWNER TO assistant_workflow_owner;
ALTER TABLE public.assistant_care_commands OWNER TO assistant_workflow_owner;
ALTER TABLE public.assistant_care_generations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assistant_care_generations FORCE ROW LEVEL SECURITY;
ALTER TABLE public.assistant_care_commands ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assistant_care_commands FORCE ROW LEVEL SECURITY;
CREATE POLICY assistant_care_epoch_owner ON public.assistant_care_generations TO assistant_workflow_owner
 USING(owner=auth.uid()) WITH CHECK(owner=auth.uid());
CREATE POLICY assistant_care_command_owner ON public.assistant_care_commands TO assistant_workflow_owner
 USING(owner=auth.uid()) WITH CHECK(owner=auth.uid());
REVOKE ALL ON public.assistant_care_generations,public.assistant_care_commands
 FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;

GRANT SELECT,INSERT,UPDATE,DELETE ON public.health_observations TO assistant_workflow_owner;
GRANT SELECT,INSERT ON public.adherence_barriers TO assistant_workflow_owner;
GRANT SELECT ON public.inventory_transactions,public.medication_care_tasks,public.dose_rules TO assistant_workflow_owner;
GRANT SELECT ON public.effective_dose_events TO assistant_workflow_owner;
DO $$ DECLARE relation_name text; BEGIN
 FOREACH relation_name IN ARRAY ARRAY['health_observations','adherence_barriers','inventory_transactions',
 'medication_care_tasks','dose_rules'] LOOP
  EXECUTE format('CREATE POLICY assistant_care_owned_command ON public.%I TO assistant_workflow_owner USING(patient_id=auth.uid()) WITH CHECK(patient_id=auth.uid())',relation_name);
 END LOOP;
END $$;

-- Native unbound writers acquire the same owner fence before profile/domain locks.
ALTER FUNCTION public.record_inventory_transaction(uuid,jsonb) RENAME TO assistant_care_inventory_legacy_022;
ALTER FUNCTION public.create_medication_care_task(jsonb) RENAME TO assistant_care_create_legacy_034;
ALTER FUNCTION public.update_medication_care_task(uuid,jsonb) RENAME TO assistant_care_update_legacy_034;
REVOKE ALL ON FUNCTION public.assistant_care_inventory_legacy_022(uuid,jsonb),
 public.assistant_care_create_legacy_034(jsonb),public.assistant_care_update_legacy_034(uuid,jsonb)
 FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner;
GRANT EXECUTE ON FUNCTION public.assistant_care_inventory_legacy_022(uuid,jsonb),
 public.assistant_care_create_legacy_034(jsonb),public.assistant_care_update_legacy_034(uuid,jsonb)
 TO assistant_workflow_owner;

CREATE FUNCTION public.record_inventory_transaction(p_medication_id uuid,p_values jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF auth.uid() IS NULL OR auth.role() IS DISTINCT FROM 'authenticated' THEN RAISE EXCEPTION 'Verified patient required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(auth.uid()::text,35035));
 RETURN public.assistant_care_inventory_legacy_022(p_medication_id,p_values);
END $$;
CREATE FUNCTION public.create_medication_care_task(p_task jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF auth.uid() IS NULL OR auth.role() IS DISTINCT FROM 'authenticated' THEN RAISE EXCEPTION 'Verified patient required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(auth.uid()::text,35035));
 RETURN public.assistant_care_create_legacy_034(p_task);
END $$;
CREATE FUNCTION public.update_medication_care_task(p_task_id uuid,p_change jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF auth.uid() IS NULL OR auth.role() IS DISTINCT FROM 'authenticated' THEN RAISE EXCEPTION 'Verified patient required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(auth.uid()::text,35035));
 RETURN public.assistant_care_update_legacy_034(p_task_id,p_change);
END $$;

CREATE FUNCTION public.assistant_care_epoch_changed() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid; row_json jsonb;
BEGIN
 row_json:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
 o:=coalesce((row_json->>'patient_id')::uuid,(row_json->>'user_id')::uuid);
 IF o IS DISTINCT FROM auth.uid() THEN RAISE EXCEPTION 'Owned care epoch required' USING ERRCODE='42501'; END IF;
 INSERT INTO public.assistant_care_generations(owner,revision) VALUES(o,1)
 ON CONFLICT(owner) DO UPDATE SET revision=public.assistant_care_generations.revision+1;
 RETURN NULL;
END $$;
DO $$ DECLARE relation_name text; BEGIN
 FOREACH relation_name IN ARRAY ARRAY['health_observations','inventory_transactions','medication_care_tasks',
 'adherence_barriers','patient_medications','regimen_versions','source_documents','source_fields','dose_rules',
 'dose_events','dose_report_entries','patient_profiles'] LOOP
  EXECUTE format('CREATE TRIGGER assistant_care_owner_first BEFORE INSERT OR UPDATE OR DELETE ON public.%I FOR EACH STATEMENT EXECUTE FUNCTION public.assistant_medication_owner_fence()',relation_name);
  EXECUTE format('CREATE TRIGGER assistant_care_epoch AFTER INSERT OR UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.assistant_care_epoch_changed()',relation_name);
 END LOOP;
END $$;

CREATE FUNCTION public.assistant_care_revision() RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=auth.uid();n bigint;
BEGIN
 IF o IS NULL OR auth.role() IS DISTINCT FROM 'authenticated' THEN RAISE EXCEPTION 'Verified patient required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 SELECT coalesce((SELECT g.revision FROM public.assistant_care_generations g WHERE g.owner=o),0) INTO n;
 RETURN jsonb_build_object('revision',n);
END $$;

-- Translate the existing inventory estimator. No occurrence generation or writes.
-- Consumption uses effective self-reports, never missing reports or label quantity.
CREATE FUNCTION public.assistant_care_inventory(p_owner uuid,p_medication uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE physical public.inventory_transactions%ROWTYPE;latest public.inventory_transactions%ROWTYPE;
 plan public.regimen_versions%ROWTYPE;active_count int;zone text;daily double precision;used double precision;
 remaining double precision;uncertain boolean;frequency jsonb;times int;days int;stamp timestamptz:=clock_timestamp();
BEGIN
 SELECT * INTO physical FROM public.inventory_transactions WHERE patient_id=p_owner AND medication_id=p_medication
 AND kind='count' ORDER BY recorded_at DESC,id DESC LIMIT 1;
 IF NOT FOUND THEN RETURN jsonb_build_object('low_stock',false,'daily_requirement',NULL,'estimated_remaining',NULL); END IF;
 SELECT * INTO STRICT latest FROM public.inventory_transactions WHERE patient_id=p_owner AND medication_id=p_medication ORDER BY recorded_at DESC,id DESC LIMIT 1;
 SELECT timezone INTO STRICT zone FROM public.patient_profiles WHERE user_id=p_owner;
 SELECT count(*) INTO active_count FROM public.regimen_versions r WHERE patient_id=p_owner AND patient_medication_id=p_medication
 AND state='active' AND (effective_to IS NULL OR effective_to>stamp)
 AND (course_start_date IS NULL OR course_start_date<=(stamp AT TIME ZONE coalesce((SELECT d.timezone FROM public.dose_rules d
  WHERE d.patient_id=p_owner AND d.regimen_id=r.id ORDER BY d.id LIMIT 1),zone))::date)
 AND (course_end_date IS NULL OR course_end_date>=(stamp AT TIME ZONE coalesce((SELECT d.timezone FROM public.dose_rules d
  WHERE d.patient_id=p_owner AND d.regimen_id=r.id ORDER BY d.id LIMIT 1),zone))::date);
 IF active_count=1 THEN
  SELECT * INTO STRICT plan FROM public.regimen_versions r WHERE patient_id=p_owner AND patient_medication_id=p_medication
  AND state='active' AND (effective_to IS NULL OR effective_to>stamp)
  AND (course_start_date IS NULL OR course_start_date<=(stamp AT TIME ZONE coalesce((SELECT d.timezone FROM public.dose_rules d
   WHERE d.patient_id=p_owner AND d.regimen_id=r.id ORDER BY d.id LIMIT 1),zone))::date)
  AND (course_end_date IS NULL OR course_end_date>=(stamp AT TIME ZONE coalesce((SELECT d.timezone FROM public.dose_rules d
   WHERE d.patient_id=p_owner AND d.regimen_id=r.id ORDER BY d.id LIMIT 1),zone))::date);
  frequency:=plan.frequency_rule;times:=jsonb_array_length(coalesce(frequency->'local_times','[]'));
  IF NOT plan.is_prn AND plan.dose_amount>0 AND
  CASE lower(btrim(plan.dose_unit)) WHEN 'tablet' THEN 'tablet' WHEN 'tablets' THEN 'tablet'
   WHEN 'capsule' THEN 'capsule' WHEN 'capsules' THEN 'capsule' END=physical.unit AND times>0 THEN
   IF frequency->>'kind'='daily' THEN daily:=plan.dose_amount*times;
   ELSIF frequency->>'kind'='weekly' THEN
    SELECT count(DISTINCT x) INTO days FROM jsonb_array_elements(coalesce(frequency->'days_of_week','[]')) x;
    IF days>0 THEN daily:=plan.dose_amount*times*days/7.0; END IF;
   END IF;
  END IF;
 END IF;
 SELECT coalesce(bool_or(e.reported_late AND e.actual_administration_at IS NULL),false),
 coalesce(sum(CASE WHEN r.dose_amount IS NOT NULL AND CASE lower(btrim(r.dose_unit))
 WHEN 'tablet' THEN 'tablet' WHEN 'tablets' THEN 'tablet' WHEN 'capsule' THEN 'capsule' WHEN 'capsules' THEN 'capsule' END=physical.unit
 AND (NOT e.reported_late OR e.actual_administration_at>=physical.recorded_at) THEN r.dose_amount ELSE 0 END),0)
 INTO uncertain,used FROM public.effective_dose_events e JOIN public.regimen_versions r
 ON r.patient_id=e.patient_id AND r.id=e.regimen_id WHERE e.patient_id=p_owner AND r.patient_medication_id=p_medication
 AND e.event_time>=physical.recorded_at AND e.event_time<stamp+interval '1 microsecond' AND e.intake_status='reported_taken';
 remaining:=greatest(0,latest.stock_after-used);
 RETURN jsonb_build_object('low_stock',coalesce(NOT uncertain AND daily>0 AND remaining<=latest.low_threshold,false),
 'daily_requirement',daily,'estimated_remaining',CASE WHEN uncertain THEN NULL ELSE remaining END);
END $$;

CREATE FUNCTION public.assistant_care_reconcile_refill(p_owner uuid,p_medication uuid) RETURNS void
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE estimate jsonb;latest uuid;task public.medication_care_tasks%ROWTYPE;key uuid;ignored jsonb;
BEGIN
 estimate:=public.assistant_care_inventory(p_owner,p_medication);
 SELECT id INTO STRICT latest FROM public.inventory_transactions WHERE patient_id=p_owner AND medication_id=p_medication ORDER BY recorded_at DESC,id DESC LIMIT 1;
 IF estimate->'low_stock'='true'::jsonb THEN
  IF NOT EXISTS(SELECT 1 FROM public.medication_care_tasks WHERE patient_id=p_owner AND medication_id=p_medication
   AND source='stock_estimate' AND status IN ('open','contacted','deferred')) THEN
   key:=extensions.uuid_generate_v5(p_medication,'refill:'||latest::text);
   ignored:=public.assistant_care_create_legacy_034(jsonb_build_object('id',key,'medication_id',p_medication,
    'regimen_id',NULL,'category','refill','title','Review medication supply','due_at',clock_timestamp(),
    'source','stock_estimate','notes','Low-stock estimate; contact your pharmacy to check supply. This is not an automatic refill.',
    'reminder_minutes',0,'historical_entry',false));
  END IF;
 ELSIF NOT (estimate->'estimated_remaining'='null'::jsonb AND estimate->'daily_requirement'<>'null'::jsonb) THEN
  FOR task IN SELECT * FROM public.medication_care_tasks WHERE patient_id=p_owner AND medication_id=p_medication
   AND source='stock_estimate' AND status IN ('open','contacted','deferred') ORDER BY id FOR UPDATE LOOP
   key:=extensions.uuid_generate_v5(task.id,'stock:'||latest::text);
   ignored:=public.assistant_care_update_legacy_034(task.id,jsonb_build_object('id',key,'expected_version',task.version,
    'status',CASE WHEN (estimate->>'daily_requirement')::double precision>0 THEN 'completed' ELSE 'cancelled' END,
    'notes',CASE WHEN (estimate->>'daily_requirement')::double precision>0 THEN 'Supply rechecked' ELSE 'No applicable scheduled plan' END));
  END LOOP;
 END IF;
END $$;

-- Pure projection of CURRENT owned task fields through the existing care rules.
-- No caller-supplied native draft or action metadata is trusted as preparation.
CREATE FUNCTION public.assistant_care_native_projection(p_owner uuid,p_task jsonb,p_review uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE cap text:=p_task->>'capability_id';f jsonb:=p_task->'fields';v jsonb;target uuid;kind text;
 old public.medication_care_tasks%ROWTYPE;allowed text[];key text;medicine uuid;plan uuid;followup uuid;status text;
BEGIN
 allowed:=CASE
 WHEN cap IN ('observation.add','observation.edit') THEN ARRAY['observation_id','description','occurred_at','kind','value','secondary_value','unit','severity','notes','medication_id']
 WHEN cap='observation.delete' THEN ARRAY['observation_id','page']
 WHEN cap='inventory.count' THEN ARRAY['medication_id','kind','quantity','unit','low_threshold','note','page']
 WHEN cap='barrier.add' THEN ARRAY['category','occurred_at','regimen_id','description','chosen_action','follow_up_task_id']
 WHEN cap='followup.add' THEN ARRAY['title','category','due_at','medication_id','regimen_id','notes','reminder_minutes']
 WHEN cap IN ('followup.edit','followup.contacted','followup.complete','followup.defer','followup.cancel') THEN
 ARRAY['task_id','expected_version','title','category','due_at','notes','status','medication_id','regimen_id','clear_plan','reminder_minutes','disable_reminder','page'] END;
 IF allowed IS NULL OR NOT coalesce(public.assistant_wf_keys(f,allowed),false) THEN
  RAISE EXCEPTION 'Unknown care capability or patient draft field' USING ERRCODE='22023'; END IF;
 IF cap IN ('observation.add','observation.edit') THEN
  target:=CASE WHEN cap='observation.add' THEN p_review ELSE (f->>'observation_id')::uuid END;
  IF target IS NULL OR (cap='observation.add' AND f->>'observation_id' IS NOT NULL)
  OR (cap='observation.edit' AND NOT EXISTS(SELECT 1 FROM public.health_observations WHERE patient_id=p_owner AND id=target)) THEN
   RAISE EXCEPTION 'Owned observation target required' USING ERRCODE='40001'; END IF;
  kind:='save_observation';
  v:=jsonb_build_object('kind','note','value',NULL,'secondary_value',NULL,'unit',NULL,'severity',NULL,'notes',NULL,'medication_id',NULL)
   ||(f-'observation_id')||jsonb_build_object('id',target);
  IF nullif(btrim(v->>'description'),'') IS NULL OR v->>'occurred_at' IS NULL
  OR (v->>'occurred_at')::timestamptz>clock_timestamp()+interval '5 minutes' THEN
   RAISE EXCEPTION 'Complete current observation required' USING ERRCODE='22023'; END IF;
 ELSIF cap='observation.delete' THEN
  kind:='delete_observation';target:=(f->>'observation_id')::uuid;v:='{}';
  IF NOT EXISTS(SELECT 1 FROM public.health_observations WHERE patient_id=p_owner AND id=target) THEN
   RAISE EXCEPTION 'Owned observation target required' USING ERRCODE='40001'; END IF;
 ELSIF cap='inventory.count' THEN
  kind:='stock';target:=(f->>'medication_id')::uuid;
  v:=jsonb_build_object('kind','count','low_threshold',7,'note','')||(f-ARRAY['page','medication_id'])||jsonb_build_object('id',p_review);
  IF v->>'quantity' IS NULL OR v->>'unit' IS NULL THEN RAISE EXCEPTION 'Physical quantity and unit required' USING ERRCODE='22023'; END IF;
 ELSIF cap='barrier.add' THEN
  kind:='barrier';v:=jsonb_build_object('regimen_id',NULL,'description','','chosen_action','','follow_up_task_id',NULL)||f||jsonb_build_object('id',p_review);
  IF v->>'category' IS NULL OR v->>'occurred_at' IS NULL OR (v->>'occurred_at')::timestamptz>clock_timestamp()+interval '5 minutes' THEN
   RAISE EXCEPTION 'Complete current patient report required' USING ERRCODE='22023'; END IF;
 ELSIF cap='followup.add' THEN
  kind:='create_followup';v:=jsonb_build_object('category','medication_review','medication_id',NULL,'regimen_id',NULL,
   'notes','','reminder_minutes',NULL,'reminder_offsets',NULL)||f||jsonb_build_object('id',p_review);
  IF nullif(btrim(v->>'title'),'') IS NULL OR v->>'due_at' IS NULL THEN
   RAISE EXCEPTION 'Complete current follow-up required' USING ERRCODE='22023'; END IF;
 ELSE
  kind:='update_followup';target:=(f->>'task_id')::uuid;
  SELECT * INTO old FROM public.medication_care_tasks WHERE patient_id=p_owner AND id=target;
  IF NOT FOUND OR old.version IS DISTINCT FROM (f->>'expected_version')::int THEN
   RAISE EXCEPTION 'Current follow-up version required' USING ERRCODE='40001'; END IF;
  v:=jsonb_strip_nulls(f-ARRAY['page','task_id','status','clear_plan','disable_reminder']);
  IF NOT (v ? 'notes') THEN v:=v||jsonb_build_object('notes',old.notes); END IF;
  IF f->'clear_plan'='true'::jsonb THEN v:=v||jsonb_build_object('medication_id',NULL,'regimen_id',NULL);
  ELSIF f->>'regimen_id' IS NOT NULL THEN
   SELECT patient_medication_id INTO medicine FROM public.regimen_versions WHERE patient_id=p_owner AND id=(f->>'regimen_id')::uuid;
   v:=v||jsonb_build_object('medication_id',medicine);
  END IF;
  IF f->'disable_reminder'='true'::jsonb THEN v:=v||jsonb_build_object('reminder_minutes',NULL); END IF;
  IF cap<>'followup.edit' AND (f->>'status' IS NOT NULL OR v ?| ARRAY['title','category','medication_id','regimen_id','reminder_minutes']) THEN
   RAISE EXCEPTION 'Use separate follow-up edit action' USING ERRCODE='22023'; END IF;
  IF old.status IN ('completed','cancelled') AND cap<>'followup.edit' THEN
   RAISE EXCEPTION 'Reopen the current follow-up first' USING ERRCODE='40001'; END IF;
  status:=CASE cap WHEN 'followup.contacted' THEN 'contacted' WHEN 'followup.complete' THEN 'completed'
   WHEN 'followup.defer' THEN 'deferred' WHEN 'followup.cancel' THEN 'cancelled'
   ELSE coalesce(f->>'status',CASE WHEN old.status IN ('completed','cancelled') THEN 'open' ELSE old.status END) END;
  IF old.source='stock_estimate' AND v ?| ARRAY['title','category'] THEN
   RAISE EXCEPTION 'Supply follow-up retains type and title' USING ERRCODE='22023'; END IF;
  IF status='deferred' AND (v->>'due_at' IS NULL OR (v->>'due_at')::timestamptz<=clock_timestamp()) THEN
   RAISE EXCEPTION 'Choose a future follow-up time' USING ERRCODE='22023'; END IF;
  v:=v||jsonb_build_object('id',p_review,'status',status);
 END IF;
 medicine:=CASE WHEN kind='stock' THEN target ELSE (v->>'medication_id')::uuid END;
 plan:=(v->>'regimen_id')::uuid;followup:=(v->>'follow_up_task_id')::uuid;
 IF medicine IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.patient_medications WHERE patient_id=p_owner AND id=medicine)
 OR plan IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.regimen_versions WHERE patient_id=p_owner AND id=plan
  AND (medicine IS NULL OR patient_medication_id=medicine))
 OR followup IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.medication_care_tasks WHERE patient_id=p_owner AND id=followup) THEN
  RAISE EXCEPTION 'Owned matching care associations required' USING ERRCODE='42501'; END IF;
 RETURN jsonb_build_object('kind',kind,'target_id',target,'values',v);
END $$;

CREATE FUNCTION public.assistant_care_snapshot(p_owner uuid,p_task jsonb) RETURNS text
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE value jsonb;cap text:=p_task->>'capability_id';f jsonb:=p_task->'fields';
BEGIN
 IF cap='inventory.count' THEN value:=public.assistant_care_inventory(p_owner,(f->>'medication_id')::uuid);
 ELSIF cap IN ('observation.edit','observation.delete') THEN
  SELECT to_jsonb(x) INTO value FROM public.health_observations x WHERE patient_id=p_owner AND id=(f->>'observation_id')::uuid;
 ELSIF cap LIKE 'followup.%' AND f->>'task_id' IS NOT NULL THEN
  SELECT to_jsonb(x) INTO value FROM public.medication_care_tasks x WHERE patient_id=p_owner AND id=(f->>'task_id')::uuid;
 ELSE value:='"care_prepared"'; END IF;
 RETURN encode(sha256(convert_to(coalesce(value,'null')::text,'UTF8')),'hex');
END $$;

CREATE FUNCTION public.assistant_care_native_result(p_owner uuid,p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE receipt jsonb;row_json jsonb;cmd public.assistant_care_commands%ROWTYPE;ref jsonb;
BEGIN
 SELECT * INTO STRICT cmd FROM public.assistant_care_commands WHERE owner=p_owner AND action_key=(p_command->'binding'->>'action_key')::uuid;
 SELECT to_jsonb(r) INTO STRICT receipt FROM public.assistant_business_receipts r WHERE owner=p_owner AND action_key=cmd.action_key;
 ref:=receipt->'business_ref';
 IF cmd.kind='delete_observation' AND EXISTS(SELECT 1 FROM public.health_observations WHERE patient_id=p_owner AND id=(ref->>'id')::uuid) THEN
  RAISE EXCEPTION 'Observation was recreated; retain the original deletion receipt' USING ERRCODE='40001'; END IF;
 IF cmd.kind IN ('prepare_care','delete_observation') THEN row_json:='null';
 ELSIF cmd.kind='save_observation' THEN SELECT to_jsonb(x) INTO row_json FROM public.health_observations x WHERE patient_id=p_owner AND id=(ref->>'id')::uuid;
 ELSIF cmd.kind='stock' THEN SELECT to_jsonb(x) INTO row_json FROM public.inventory_transactions x WHERE patient_id=p_owner AND id=(ref->>'id')::uuid;
 ELSIF cmd.kind='barrier' THEN SELECT to_jsonb(x) INTO row_json FROM public.adherence_barriers x WHERE patient_id=p_owner AND id=(ref->>'id')::uuid;
 ELSE SELECT to_jsonb(x) INTO row_json FROM public.medication_care_tasks x WHERE patient_id=p_owner AND id=(ref->>'id')::uuid; END IF;
 IF row_json IS NULL OR (cmd.native_hash IS NOT NULL AND cmd.native_hash IS DISTINCT FROM encode(sha256(convert_to(row_json::text,'UTF8')),'hex')) THEN
  RAISE EXCEPTION 'Native care row changed or was deleted; retain prior receipt' USING ERRCODE='40001'; END IF;
 RETURN jsonb_build_object('receipt',receipt,'result',row_json);
END $$;

CREATE FUNCTION public.assistant_care_apply(p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE o uuid:=auth.uid();b jsonb:=p_command->'binding';kind text:=p_command->>'kind';preparing boolean:=kind='prepare_care';
 tid uuid;aid uuid;revision int;ref jsonb:=b->'prepared_ref';t jsonb;ctl jsonb;digest text;generation bigint;allowed text[];
 prior public.assistant_care_commands%ROWTYPE;prep public.assistant_care_commands%ROWTYPE;snapshot text;projection jsonb;
 v jsonb:=p_command->'values';target uuid;row_json jsonb;native_ref jsonb;child jsonb;action_json jsonb;stamp timestamptz;
BEGIN
 IF o IS NULL OR auth.role() IS DISTINCT FROM 'authenticated' THEN RAISE EXCEPTION 'Verified patient required' USING ERRCODE='42501'; END IF;
 allowed:=CASE kind WHEN 'prepare_care' THEN ARRAY['kind','binding'] WHEN 'delete_observation' THEN ARRAY['kind','binding','confirmed','observation_id']
 WHEN 'stock' THEN ARRAY['kind','binding','confirmed','medication_id','values']
 WHEN 'update_followup' THEN ARRAY['kind','binding','confirmed','task_id','expected_version','values']
 WHEN 'save_observation' THEN ARRAY['kind','binding','confirmed','values']
 WHEN 'barrier' THEN ARRAY['kind','binding','confirmed','values']
 WHEN 'create_followup' THEN ARRAY['kind','binding','confirmed','values'] END;
 IF allowed IS NULL OR NOT coalesce(public.assistant_wf_keys(p_command,allowed),false)
 OR NOT coalesce(public.assistant_wf_keys(b,ARRAY['task_id','task_revision','capability_id','action_key','prepared_ref','expected_domain_revision','run_binding']),false)
 OR (NOT preparing AND p_command->'confirmed' IS DISTINCT FROM 'true'::jsonb)
 OR (NOT preparing AND kind<>'delete_observation' AND v->'confirmed' IS DISTINCT FROM 'true'::jsonb)
 OR NOT coalesce(public.assistant_wf_keys(ref,ARRAY['kind','id','version']),false)
 OR ref->>'kind' IS DISTINCT FROM 'care_review' OR ref->'version' IS DISTINCT FROM '1'::jsonb THEN
  RAISE EXCEPTION 'Closed independently confirmed care command required' USING ERRCODE='22023'; END IF;
 tid:=(b->>'task_id')::uuid;aid:=(b->>'action_key')::uuid;revision:=(b->>'task_revision')::int;
 IF tid IS NULL OR aid IS NULL OR revision IS NULL OR revision<1 OR b->>'expected_domain_revision' IS NULL THEN
  RAISE EXCEPTION 'Complete care binding required' USING ERRCODE='22023'; END IF;
 digest:=encode(sha256(convert_to(p_command::text,'UTF8')),'hex');
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 SELECT data INTO t FROM public.assistant_workflow_tasks WHERE owner=o AND id=tid FOR UPDATE;
 SELECT data INTO ctl FROM public.assistant_workflow_operations WHERE owner=o AND task_id=tid AND id=tid AND record_type='control' FOR UPDATE;
 SELECT * INTO prior FROM public.assistant_care_commands WHERE owner=o AND action_key=aid;
 IF FOUND THEN
  IF prior.command_digest IS DISTINCT FROM digest OR prior.task_id IS DISTINCT FROM tid THEN RAISE EXCEPTION 'Action reused' USING ERRCODE='23505'; END IF;
  RETURN jsonb_build_object('result',public.assistant_care_native_result(o,p_command),'replayed',true);
 END IF;
 IF EXISTS(SELECT 1 FROM public.assistant_business_receipts WHERE owner=o AND action_key=aid) THEN RAISE EXCEPTION 'Action belongs to another transaction' USING ERRCODE='23505'; END IF;
 SELECT coalesce((SELECT g.revision FROM public.assistant_care_generations g WHERE g.owner=o),0) INTO generation;
 IF t IS NULL OR ctl IS NULL OR t->>'capability_id' IS DISTINCT FROM b->>'capability_id' OR ctl->>'capability_id' IS DISTINCT FROM b->>'capability_id'
 OR (t->>'revision')::int IS DISTINCT FROM revision OR (ctl->>'revision')::int IS DISTINCT FROM revision
 OR t->>'save_mode' IS DISTINCT FROM 'allowed' OR ctl->>'mode' IS DISTINCT FROM 'allowed'
 OR ctl->'revoked' IS DISTINCT FROM 'false'::jsonb OR ctl->>'status' IS DISTINCT FROM 'idle'
 OR generation IS DISTINCT FROM (b->>'expected_domain_revision')::bigint THEN
  RAISE EXCEPTION 'Current owned care review changed' USING ERRCODE='40001'; END IF;
 IF nullif(b->'run_binding','null'::jsonb) IS NOT NULL THEN PERFORM public.assistant_run_assert_current(o,b->'run_binding'); END IF;
 snapshot:=public.assistant_care_snapshot(o,t);
 IF preparing THEN
  IF (ref->>'id')::uuid IS DISTINCT FROM aid THEN RAISE EXCEPTION 'Owned technical marker required' USING ERRCODE='22023'; END IF;
  IF t->>'state' IS DISTINCT FROM 'ready_for_review' THEN
   SELECT * INTO prep FROM public.assistant_care_commands c WHERE c.owner=o AND c.task_id=tid AND c.kind='prepare_care'
    AND c.prepared_ref=t->'business_refs'->0;
   IF t->>'state' IS DISTINCT FROM 'awaiting_confirmation' OR jsonb_array_length(t->'business_refs')<>1 OR prep.owner IS NULL
   OR NOT (prep.binding_revision<revision OR prep.domain_revision<>generation OR prep.snapshot_hash IS DISTINCT FROM snapshot) THEN
    RAISE EXCEPTION 'Prepare after current input or native state changes' USING ERRCODE='40001'; END IF;
  END IF;
  projection:=public.assistant_care_native_projection(o,t,aid);
  IF EXISTS(SELECT 1 FROM public.assistant_workflow_operations WHERE owner=o AND record_type='action' AND id=aid) THEN
   RAISE EXCEPTION 'Preparation action already used' USING ERRCODE='23505'; END IF;
  action_json:=jsonb_build_object('action_key',aid,'task_id',tid,'capability_id',b->>'capability_id','binding_revision',revision,
   'state','pending','business_ref',ref,'safe_reason','care_prepared','updated_at',clock_timestamp());
  INSERT INTO public.assistant_workflow_operations(owner,record_type,id,task_id,data) VALUES(o,'action',aid,tid,action_json);
  row_json:='null';native_ref:=ref;
 ELSE
  SELECT * INTO prep FROM public.assistant_care_commands c WHERE c.owner=o AND c.task_id=tid AND c.kind='prepare_care' AND c.prepared_ref=ref;
  IF prep.owner IS NULL OR prep.binding_revision<>revision OR prep.capability_id IS DISTINCT FROM b->>'capability_id'
  OR prep.domain_revision<>generation OR prep.snapshot_hash IS DISTINCT FROM snapshot
  OR t->>'state' IS DISTINCT FROM 'awaiting_confirmation' OR NOT(t->'business_refs' @> jsonb_build_array(ref)) THEN
   RAISE EXCEPTION 'Fresh independent care review required' USING ERRCODE='40001'; END IF;
  projection:=public.assistant_care_native_projection(o,t,(ref->>'id')::uuid);
  target:=(projection->>'target_id')::uuid;
  IF projection->>'kind' IS DISTINCT FROM kind OR (kind='delete_observation' AND target IS DISTINCT FROM (p_command->>'observation_id')::uuid)
  OR (kind='stock' AND target IS DISTINCT FROM (p_command->>'medication_id')::uuid)
  OR (kind='update_followup' AND (target IS DISTINCT FROM (p_command->>'task_id')::uuid
   OR p_command->'expected_version' IS DISTINCT FROM projection->'values'->'expected_version'))
  OR (kind<>'delete_observation' AND (v-ARRAY['confirmed','historical_confirmed']) IS DISTINCT FROM projection->'values') THEN
   RAISE EXCEPTION 'Native values differ from the saved patient review' USING ERRCODE='40001'; END IF;
  stamp:=clock_timestamp();
  IF kind='save_observation' THEN
   INSERT INTO public.health_observations(patient_id,id,occurred_at,description,severity,notes,medication_id,source,created_at,updated_at,kind,value,secondary_value,unit)
   VALUES(o,(v->>'id')::uuid,(v->>'occurred_at')::timestamptz,btrim(v->>'description'),v->>'severity',v->>'notes',
    (v->>'medication_id')::uuid,'patient_reported',stamp,stamp,v->>'kind',(v->>'value')::double precision,
    (v->>'secondary_value')::double precision,v->>'unit')
   ON CONFLICT(patient_id,id) DO UPDATE SET occurred_at=EXCLUDED.occurred_at,description=EXCLUDED.description,
    severity=EXCLUDED.severity,notes=EXCLUDED.notes,medication_id=EXCLUDED.medication_id,kind=EXCLUDED.kind,
    value=EXCLUDED.value,secondary_value=EXCLUDED.secondary_value,unit=EXCLUDED.unit,updated_at=EXCLUDED.updated_at;
   SELECT to_jsonb(x) INTO STRICT row_json FROM public.health_observations x WHERE patient_id=o AND id=(v->>'id')::uuid;
   native_ref:=jsonb_build_object('kind','observation','id',v->'id','version',NULL);
  ELSIF kind='delete_observation' THEN
   DELETE FROM public.health_observations WHERE patient_id=o AND id=target;
   IF NOT FOUND THEN RAISE EXCEPTION 'Observation changed' USING ERRCODE='40001'; END IF;
   row_json:='null';native_ref:=jsonb_build_object('kind','observation','id',target,'version',NULL);
  ELSIF kind='stock' THEN
   IF EXISTS(SELECT 1 FROM public.inventory_transactions WHERE patient_id=o AND id=(v->>'id')::uuid) THEN
    RAISE EXCEPTION 'Inspect the original stock receipt' USING ERRCODE='40001'; END IF;
   row_json:=public.assistant_care_inventory_legacy_022(target,v-'confirmed');
   PERFORM public.assistant_care_reconcile_refill(o,target);
   native_ref:=jsonb_build_object('kind','stock','id',row_json->'id','version',NULL);
  ELSIF kind='barrier' THEN
   INSERT INTO public.adherence_barriers(patient_id,id,regimen_id,follow_up_task_id,category,occurred_at,description,chosen_action,recorded_at)
   VALUES(o,(v->>'id')::uuid,(v->>'regimen_id')::uuid,(v->>'follow_up_task_id')::uuid,v->>'category',
    (v->>'occurred_at')::timestamptz,coalesce(v->>'description',''),coalesce(v->>'chosen_action',''),stamp);
   SELECT to_jsonb(x) INTO STRICT row_json FROM public.adherence_barriers x WHERE patient_id=o AND id=(v->>'id')::uuid;
   native_ref:=jsonb_build_object('kind','barrier','id',v->'id','version',NULL);
  ELSIF kind='create_followup' THEN
   row_json:=public.assistant_care_create_legacy_034((v-ARRAY['confirmed','historical_confirmed'])||jsonb_build_object(
    'source','patient_reported','historical_entry',coalesce((v->>'historical_confirmed')::boolean,false)));
   native_ref:=jsonb_build_object('kind','care_task','id',row_json->'id','version',row_json->'version');
  ELSE
   row_json:=public.assistant_care_update_legacy_034(target,v-'confirmed');
   native_ref:=jsonb_build_object('kind','care_task','id',row_json->'id','version',row_json->'version');
  END IF;
 END IF;
 IF nullif(b->'run_binding','null'::jsonb) IS NOT NULL THEN PERFORM public.assistant_run_assert_current(o,b->'run_binding'); END IF;
 child:=public.assistant_workflow_command_legacy_035('task_cas',jsonb_build_object('task_id',tid,'expected_revision',revision,
  'event_id',aid,'request_digest',digest,'update',jsonb_build_object('state',CASE WHEN preparing THEN 'awaiting_confirmation' ELSE 'completed' END,
   'save_mode','allowed','storage_state','saved','fields',t->'fields','missing_fields','[]'::jsonb,
   'attachment_ids',t->'attachment_ids','business_refs',jsonb_build_array(native_ref))));
 IF child ? 'error' THEN RAISE EXCEPTION 'Task changed after native care publication' USING ERRCODE='40001'; END IF;
 SELECT coalesce((SELECT g.revision FROM public.assistant_care_generations g WHERE g.owner=o),0) INTO generation;
 INSERT INTO public.assistant_business_receipts(owner,action_key,task_id,capability_id,binding_revision,business_ref,domain_revision,outcome)
 VALUES(o,aid,tid,b->>'capability_id',revision+1,native_ref,generation,CASE WHEN preparing THEN 'prepared' ELSE 'applied' END);
 INSERT INTO public.assistant_care_commands(owner,action_key,task_id,capability_id,binding_revision,kind,command_digest,prepared_ref,domain_revision,snapshot_hash,native_hash)
 VALUES(o,aid,tid,b->>'capability_id',revision+1,kind,digest,ref,generation,CASE WHEN preparing THEN snapshot END,
  CASE WHEN row_json<>'null'::jsonb THEN encode(sha256(convert_to(row_json::text,'UTF8')),'hex') END);
 RETURN jsonb_build_object('result',public.assistant_care_native_result(o,p_command),'replayed',false);
END $$;

CREATE FUNCTION public.assistant_care_prepare(p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF p_command->>'kind' IS DISTINCT FROM 'prepare_care' THEN RETURN jsonb_build_object('error','invalid'); END IF;
 RETURN public.assistant_care_apply(p_command);
EXCEPTION WHEN SQLSTATE '40001' THEN RETURN jsonb_build_object('error','stale');
 WHEN unique_violation THEN RETURN jsonb_build_object('error','duplicate');
 WHEN invalid_parameter_value OR invalid_text_representation OR check_violation OR not_null_violation THEN RETURN jsonb_build_object('error','invalid');
END $$;
CREATE FUNCTION public.assistant_care_write(p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF p_command->>'kind' IS NOT DISTINCT FROM 'prepare_care' THEN RETURN jsonb_build_object('error','invalid'); END IF;
 RETURN public.assistant_care_apply(p_command);
EXCEPTION WHEN SQLSTATE '40001' THEN RETURN jsonb_build_object('error','stale');
 WHEN unique_violation THEN RETURN jsonb_build_object('error','duplicate');
 WHEN invalid_parameter_value OR invalid_text_representation OR check_violation OR not_null_violation THEN RETURN jsonb_build_object('error','invalid');
END $$;
CREATE FUNCTION public.assistant_care_read(p_command jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE o uuid:=auth.uid();prior public.assistant_care_commands%ROWTYPE;
BEGIN
 IF o IS NULL OR auth.role() IS DISTINCT FROM 'authenticated' THEN RAISE EXCEPTION 'Verified patient required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text,35035));
 SELECT * INTO prior FROM public.assistant_care_commands WHERE owner=o AND action_key=(p_command->'binding'->>'action_key')::uuid;
 IF NOT FOUND THEN RETURN jsonb_build_object('error','not_found'); END IF;
 IF prior.command_digest IS DISTINCT FROM encode(sha256(convert_to(p_command::text,'UTF8')),'hex') THEN RETURN jsonb_build_object('error','duplicate'); END IF;
 RETURN jsonb_build_object('result',public.assistant_care_native_result(o,p_command),'replayed',true);
EXCEPTION WHEN SQLSTATE '40001' THEN RETURN jsonb_build_object('error','stale');
 WHEN invalid_text_representation THEN RETURN jsonb_build_object('error','invalid');
END $$;

-- Closed privilege inventory: verifier identities have no entry/clinical access.
DO $$ DECLARE signature text; BEGIN
 FOREACH signature IN ARRAY ARRAY['assistant_care_epoch_changed()','assistant_care_revision()',
 'assistant_care_inventory(uuid,uuid)','assistant_care_reconcile_refill(uuid,uuid)',
 'assistant_care_native_projection(uuid,jsonb,uuid)','assistant_care_snapshot(uuid,jsonb)',
 'assistant_care_native_result(uuid,jsonb)','assistant_care_apply(jsonb)',
 'assistant_care_prepare(jsonb)','assistant_care_write(jsonb)','assistant_care_read(jsonb)',
 'record_inventory_transaction(uuid,jsonb)','create_medication_care_task(jsonb)','update_medication_care_task(uuid,jsonb)'] LOOP
  EXECUTE 'ALTER FUNCTION public.'||signature||' OWNER TO assistant_workflow_owner';
  EXECUTE 'REVOKE ALL ON FUNCTION public.'||signature||' FROM PUBLIC,anon,authenticated,service_role,assistant_evidence_login,assistant_evidence_owner';
 END LOOP;
END $$;
GRANT EXECUTE ON FUNCTION public.assistant_care_revision(),public.assistant_care_prepare(jsonb),
 public.assistant_care_write(jsonb),public.assistant_care_read(jsonb),public.record_inventory_transaction(uuid,jsonb),
 public.create_medication_care_task(jsonb),public.update_medication_care_task(uuid,jsonb) TO authenticated;
COMMIT;
