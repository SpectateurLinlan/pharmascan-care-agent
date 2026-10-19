-- Explicit operator rollback only; refuse to discard new task semantics or history.
BEGIN;
LOCK TABLE public.medication_care_tasks IN ACCESS EXCLUSIVE MODE;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.medication_care_tasks t WHERE historical_entry
  OR reminder_minutes IS DISTINCT FROM 0 OR EXISTS(SELECT 1 FROM jsonb_array_elements(t.history) e
   WHERE e ?| ARRAY['title','category','medication_id','regimen_id','reminder_minutes']))
 THEN RAISE EXCEPTION 'New task history exists; retain schema and apply a forward fix'; END IF;
END $$;
CREATE OR REPLACE FUNCTION public.create_medication_care_task(p_task jsonb) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE owner_id uuid:=auth.uid(); result public.medication_care_tasks; original jsonb;
BEGIN
 IF owner_id IS NULL THEN RAISE EXCEPTION 'Authentication required' USING ERRCODE='42501'; END IF;
 PERFORM 1 FROM public.patient_profiles WHERE user_id=owner_id FOR UPDATE;
 SELECT * INTO result FROM public.medication_care_tasks WHERE patient_id=owner_id AND id=(p_task->>'id')::uuid;
 IF FOUND THEN
   original:=result.history->0;
   IF result.category<>p_task->>'category' OR result.title<>p_task->>'title' OR result.source<>p_task->>'source'
      OR result.medication_id IS DISTINCT FROM (p_task->>'medication_id')::uuid
      OR result.regimen_id IS DISTINCT FROM (p_task->>'regimen_id')::uuid
      OR (result.source<>'stock_estimate' AND (
        (original->>'due_at')::timestamptz IS DISTINCT FROM (p_task->>'due_at')::timestamptz
        OR original->>'notes' IS DISTINCT FROM p_task->>'notes'))
   THEN RAISE EXCEPTION 'Task key reused' USING ERRCODE='22023'; END IF;
   RETURN to_jsonb(result);
 END IF;
 IF p_task->>'regimen_id' IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.regimen_versions
   WHERE patient_id=owner_id AND id=(p_task->>'regimen_id')::uuid
   AND (p_task->>'medication_id' IS NULL OR patient_medication_id=(p_task->>'medication_id')::uuid))
 THEN RAISE EXCEPTION 'Regimen not found' USING ERRCODE='42501'; END IF;
 INSERT INTO public.medication_care_tasks(patient_id,id,medication_id,regimen_id,category,title,due_at,notes,source,history)
 VALUES(owner_id,(p_task->>'id')::uuid,(p_task->>'medication_id')::uuid,(p_task->>'regimen_id')::uuid,
 p_task->>'category',p_task->>'title',(p_task->>'due_at')::timestamptz,p_task->>'notes',p_task->>'source',
 jsonb_build_array(jsonb_build_object('id',p_task->>'id','status','open','due_at',(p_task->>'due_at')::timestamptz,
 'notes',p_task->>'notes','recorded_at',clock_timestamp()))) RETURNING * INTO result;
 RETURN to_jsonb(result);
END $$;
CREATE OR REPLACE FUNCTION public.update_medication_care_task(p_task_id uuid,p_change jsonb) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE owner_id uuid:=auth.uid(); result public.medication_care_tasks; old_event jsonb; event jsonb;
BEGIN
 IF owner_id IS NULL THEN RAISE EXCEPTION 'Authentication required' USING ERRCODE='42501'; END IF;
 SELECT * INTO result FROM public.medication_care_tasks WHERE patient_id=owner_id AND id=p_task_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Task not found' USING ERRCODE='42501'; END IF;
 SELECT value INTO old_event FROM jsonb_array_elements(result.history) WHERE value->>'id'=p_change->>'id';
 IF old_event IS NOT NULL THEN
   IF old_event->>'status'<>p_change->>'status' OR old_event->>'notes'<>p_change->>'notes'
   OR (p_change->>'due_at' IS NOT NULL AND (old_event->>'due_at')::timestamptz<>(p_change->>'due_at')::timestamptz)
   THEN RAISE EXCEPTION 'Update key reused' USING ERRCODE='22023'; END IF;
   RETURN to_jsonb(result);
 END IF;
 IF result.version<>(p_change->>'expected_version')::integer OR result.status IN ('completed','cancelled')
 THEN RAISE EXCEPTION 'Task changed or closed' USING ERRCODE='22023'; END IF;
 IF p_change->>'status'='deferred' AND (p_change->>'due_at' IS NULL OR (p_change->>'due_at')::timestamptz<=now())
 THEN RAISE EXCEPTION 'Choose a future time' USING ERRCODE='22023'; END IF;
 event:=jsonb_build_object('id',p_change->>'id','status',p_change->>'status','notes',p_change->>'notes',
   'due_at',COALESCE((p_change->>'due_at')::timestamptz,result.due_at),'recorded_at',clock_timestamp());
 UPDATE public.medication_care_tasks SET status=p_change->>'status',notes=p_change->>'notes',
 due_at=COALESCE((p_change->>'due_at')::timestamptz,due_at),version=version+1,history=history||jsonb_build_array(event),
 updated_at=clock_timestamp() WHERE patient_id=owner_id AND id=p_task_id RETURNING * INTO result;
 RETURN to_jsonb(result);
END $$;
ALTER TABLE public.medication_care_tasks DROP COLUMN reminder_minutes, DROP COLUMN historical_entry;
NOTIFY pgrst,'reload schema';
COMMIT;
