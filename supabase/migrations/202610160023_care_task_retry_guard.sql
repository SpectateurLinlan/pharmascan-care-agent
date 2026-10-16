-- Preserve the original confirmation payload when rejecting changed retry keys.
BEGIN;
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
NOTIFY pgrst,'reload schema';
COMMIT;
