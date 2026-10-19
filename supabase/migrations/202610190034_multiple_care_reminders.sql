-- Owner-requested local extension. Production execution requires separate approval.
BEGIN;
ALTER TABLE public.medication_care_tasks ADD COLUMN reminder_offsets integer[]
 CHECK(reminder_offsets IS NULL OR (cardinality(reminder_offsets)<=8
 AND array_position(reminder_offsets,NULL) IS NULL AND 0<=ALL(reminder_offsets) AND 10080>=ALL(reminder_offsets)));
-- NULL preserves the legacy scalar reminder without rewriting any existing task.
CREATE FUNCTION public.core_care_reminder_offsets(values_json jsonb, legacy integer) RETURNS integer[]
LANGUAGE plpgsql IMMUTABLE SET search_path='' AS $$
DECLARE result integer[];
BEGIN
 IF values_json IS NULL OR values_json='null'::jsonb THEN
  RETURN CASE WHEN legacy IS NULL THEN '{}'::integer[] ELSE ARRAY[legacy] END;
 END IF;
 IF jsonb_typeof(values_json)<>'array' OR jsonb_array_length(values_json)>8 THEN
  RAISE EXCEPTION 'Use at most eight reminder times' USING ERRCODE='22023'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(values_json) x WHERE jsonb_typeof(x)<>'number' OR x::text !~ '^[0-9]+$'
    OR (x::text)::numeric>10080) THEN RAISE EXCEPTION 'Invalid reminder minutes' USING ERRCODE='22023'; END IF;
 SELECT coalesce(array_agg(x ORDER BY x DESC),'{}'::integer[]) INTO result
 FROM (SELECT DISTINCT value::integer x FROM jsonb_array_elements_text(values_json)) normalized;
 RETURN result;
END $$;
REVOKE ALL ON FUNCTION public.core_care_reminder_offsets(jsonb,integer) FROM PUBLIC,anon,authenticated,service_role;
CREATE OR REPLACE FUNCTION public.create_medication_care_task(p_task jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE owner_id uuid:=auth.uid(); result public.medication_care_tasks; original jsonb;
 offsets integer[]; due timestamptz:=(p_task->>'due_at')::timestamptz; lead integer:=CASE WHEN p_task ? 'reminder_minutes' THEN (p_task->>'reminder_minutes')::int ELSE 0 END;
BEGIN
 IF owner_id IS NULL THEN RAISE EXCEPTION 'Authentication required' USING ERRCODE='42501'; END IF;
 offsets:=public.core_care_reminder_offsets(p_task->'reminder_offsets',lead);
 SELECT max(x) INTO lead FROM unnest(offsets) x;
 PERFORM 1 FROM public.patient_profiles WHERE user_id=owner_id FOR UPDATE;
 SELECT * INTO result FROM public.medication_care_tasks WHERE patient_id=owner_id AND id=(p_task->>'id')::uuid;
 IF FOUND THEN
  original:=result.history->0;
  IF coalesce(original->>'title',result.title) IS DISTINCT FROM p_task->>'title'
   OR coalesce(original->>'category',result.category) IS DISTINCT FROM p_task->>'category'
   OR (CASE WHEN original ? 'medication_id' THEN (original->>'medication_id')::uuid ELSE result.medication_id END) IS DISTINCT FROM (p_task->>'medication_id')::uuid
   OR (CASE WHEN original ? 'regimen_id' THEN (original->>'regimen_id')::uuid ELSE result.regimen_id END) IS DISTINCT FROM (p_task->>'regimen_id')::uuid
   OR result.source IS DISTINCT FROM p_task->>'source'
   OR (result.source<>'stock_estimate' AND ((original->>'due_at')::timestamptz IS DISTINCT FROM due
     OR original->>'notes' IS DISTINCT FROM p_task->>'notes'
     OR public.core_care_reminder_offsets(original->'reminder_offsets',CASE WHEN original ? 'reminder_minutes' THEN (original->>'reminder_minutes')::int ELSE 0 END) IS DISTINCT FROM offsets
     OR CASE WHEN original ? 'reminder_minutes' THEN (original->>'reminder_minutes')::int ELSE 0 END IS DISTINCT FROM lead))
  THEN RAISE EXCEPTION 'Task key reused' USING ERRCODE='22023'; END IF;
  RETURN to_jsonb(result);
 END IF;
 IF p_task->>'source'<>'stock_estimate' THEN
  IF due<now() AND NOT coalesce((p_task->>'historical_entry')::boolean,false) THEN
   RAISE EXCEPTION 'Confirm historical entry' USING ERRCODE='22023'; END IF;
  IF lead IS NOT NULL AND due-make_interval(mins=>lead)<now() THEN
   RAISE EXCEPTION 'Reminder must be in the future' USING ERRCODE='22023'; END IF;
 END IF;
 IF p_task->>'regimen_id' IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.regimen_versions
  WHERE patient_id=owner_id AND id=(p_task->>'regimen_id')::uuid
  AND (p_task->>'medication_id' IS NULL OR patient_medication_id=(p_task->>'medication_id')::uuid))
 THEN RAISE EXCEPTION 'Owned matching regimen required' USING ERRCODE='42501'; END IF;
 INSERT INTO public.medication_care_tasks(patient_id,id,medication_id,regimen_id,category,title,due_at,notes,source,reminder_minutes,reminder_offsets,historical_entry,history)
 VALUES(owner_id,(p_task->>'id')::uuid,(p_task->>'medication_id')::uuid,(p_task->>'regimen_id')::uuid,
 p_task->>'category',btrim(p_task->>'title'),due,coalesce(p_task->>'notes',''),p_task->>'source',lead,offsets,
 coalesce((p_task->>'historical_entry')::boolean,false),'[]') RETURNING * INTO result;
 UPDATE public.medication_care_tasks SET history=jsonb_build_array(jsonb_build_object('id',result.id,'status',result.status,'due_at',result.due_at,'notes',result.notes,
   'title',result.title,'category',result.category,'medication_id',result.medication_id,'regimen_id',result.regimen_id,
   'reminder_minutes',result.reminder_minutes,'reminder_offsets',to_jsonb(result.reminder_offsets),'historical_confirmed',result.historical_entry,'recorded_at',result.created_at)) WHERE patient_id=owner_id AND id=result.id RETURNING * INTO result;
 RETURN to_jsonb(result);
END $$;
CREATE OR REPLACE FUNCTION public.update_medication_care_task(p_task_id uuid,p_change jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE owner_id uuid:=auth.uid(); result public.medication_care_tasks; original jsonb; event jsonb;
 due timestamptz; lead integer; offsets integer[]; med uuid; plan uuid; proposed public.medication_care_tasks;
BEGIN
 IF owner_id IS NULL THEN RAISE EXCEPTION 'Authentication required' USING ERRCODE='42501'; END IF;
 SELECT * INTO result FROM public.medication_care_tasks WHERE patient_id=owner_id AND id=p_task_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Task not found' USING ERRCODE='42501'; END IF;
 IF p_change ? 'reminder_offsets' THEN
  offsets:=public.core_care_reminder_offsets(p_change->'reminder_offsets',NULL);
  SELECT max(x) INTO lead FROM unnest(offsets) x;
  p_change:=p_change||jsonb_build_object('reminder_offsets',offsets,'reminder_minutes',lead);
 END IF;
 SELECT value INTO original FROM jsonb_array_elements(result.history) WHERE value->>'id'=p_change->>'id';
 IF original IS NOT NULL THEN
  IF EXISTS(SELECT 1 FROM jsonb_each(p_change-ARRAY['id','expected_version','confirmed','historical_confirmed']) x
     WHERE original->x.key IS DISTINCT FROM x.value AND (x.key<>'due_at' OR x.value<>'null'::jsonb))
  THEN RAISE EXCEPTION 'Update key reused' USING ERRCODE='22023'; END IF;
  RETURN to_jsonb(result);
 END IF;
 IF result.version<>(p_change->>'expected_version')::int OR jsonb_array_length(result.history)>=100
  OR (result.status IN ('completed','cancelled') AND p_change->>'status'<>'open')
 THEN RAISE EXCEPTION 'Task changed; reopen or reload first' USING ERRCODE='22023'; END IF;
 IF result.source='stock_estimate' AND p_change ?| ARRAY['title','category','medication_id','regimen_id']
 THEN RAISE EXCEPTION 'Supply task retains original association' USING ERRCODE='22023'; END IF;
 due:=coalesce((p_change->>'due_at')::timestamptz,result.due_at);
 lead:=CASE WHEN p_change ? 'reminder_minutes' THEN (p_change->>'reminder_minutes')::int ELSE result.reminder_minutes END;
 offsets:=CASE WHEN p_change ? 'reminder_offsets' THEN public.core_care_reminder_offsets(p_change->'reminder_offsets',lead)
  WHEN p_change ? 'reminder_minutes' THEN public.core_care_reminder_offsets(NULL,lead)
  ELSE coalesce(result.reminder_offsets,public.core_care_reminder_offsets(NULL,result.reminder_minutes)) END;
 IF p_change->>'status'='deferred' AND due<=now() THEN RAISE EXCEPTION 'Choose future time' USING ERRCODE='22023'; END IF;
 IF p_change->>'status' NOT IN ('completed','cancelled') AND
   (due IS DISTINCT FROM result.due_at OR offsets IS DISTINCT FROM coalesce(result.reminder_offsets,public.core_care_reminder_offsets(NULL,result.reminder_minutes)) OR lead IS DISTINCT FROM result.reminder_minutes OR result.status IN ('completed','cancelled')) THEN
  IF due<now() AND NOT coalesce((p_change->>'historical_confirmed')::boolean,false) THEN
   RAISE EXCEPTION 'Confirm historical entry' USING ERRCODE='22023'; END IF;
  IF lead IS NOT NULL AND due-make_interval(mins=>lead)<now() THEN RAISE EXCEPTION 'Reminder must be future' USING ERRCODE='22023'; END IF;
 END IF;
 med:=CASE WHEN p_change ? 'medication_id' THEN (p_change->>'medication_id')::uuid ELSE result.medication_id END;
 plan:=CASE WHEN p_change ? 'regimen_id' THEN (p_change->>'regimen_id')::uuid ELSE result.regimen_id END;
 IF plan IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.regimen_versions WHERE patient_id=owner_id AND id=plan
  AND (med IS NULL OR patient_medication_id=med)) THEN RAISE EXCEPTION 'Owned matching regimen required' USING ERRCODE='42501'; END IF;
 proposed:=jsonb_populate_record(result,p_change-ARRAY['id','expected_version','confirmed','historical_confirmed','due_at']);
 event:=jsonb_build_object('id',p_change->>'id','status',proposed.status,'due_at',due,'notes',proposed.notes,
  'title',proposed.title,'category',proposed.category,'medication_id',med,'regimen_id',plan,
  'reminder_minutes',lead,'reminder_offsets',to_jsonb(offsets),'historical_confirmed',coalesce((p_change->>'historical_confirmed')::boolean,false),'recorded_at',clock_timestamp());
 UPDATE public.medication_care_tasks SET status=proposed.status,title=btrim(proposed.title),category=proposed.category,
 medication_id=med,regimen_id=plan,notes=proposed.notes,due_at=due,reminder_minutes=lead,reminder_offsets=offsets,
 version=version+1,history=history||jsonb_build_array(event),updated_at=clock_timestamp()
 WHERE patient_id=owner_id AND id=p_task_id RETURNING * INTO result;
 RETURN to_jsonb(result);
END $$;
-- Existing owner checks, RPC ACL and RLS are retained.
NOTIFY pgrst,'reload schema';
COMMIT;
