-- Additive long-term medication care. No regimen or dose-event mutations.
BEGIN;
ALTER TABLE public.agent_tool_calls DROP CONSTRAINT agent_tool_calls_tool_name_check;
ALTER TABLE public.agent_tool_calls ADD CONSTRAINT agent_tool_calls_tool_name_check CHECK(tool_name IN
 ('list_active_medications','get_medication_history','get_dose_status','enroll_medication_draft',
 'confirm_regimen_draft','check_due_dose','record_self_report','create_reminder','reconcile_medication_sources',
 'get_long_term_care','prepare_care_action'));
ALTER TABLE public.health_observations
 ADD COLUMN kind text NOT NULL DEFAULT 'note',
 ADD COLUMN value double precision,
 ADD COLUMN secondary_value double precision,
 ADD COLUMN unit text;
ALTER TABLE public.health_observations ADD CONSTRAINT observation_measurement_check CHECK (
 (kind='note' AND value IS NULL AND secondary_value IS NULL AND unit IS NULL) OR
 (value IS NOT NULL AND unit IS NOT NULL AND value BETWEEN 0 AND 10000 AND (
   (kind='blood_pressure' AND unit='mmHg' AND secondary_value IS NOT NULL AND secondary_value BETWEEN 0 AND 10000) OR
   (secondary_value IS NULL AND ((kind='blood_glucose' AND unit IN ('mmol/L','mg/dL')) OR
    (kind='weight' AND unit='kg') OR (kind='sleep' AND unit='hours') OR (kind='mood' AND unit='score')))
 )));

CREATE TABLE public.inventory_transactions (
 patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id) ON DELETE RESTRICT,
 medication_id uuid NOT NULL, id uuid NOT NULL,
 kind text NOT NULL CHECK(kind IN ('count','refill','adjustment','lost','discarded','damaged')),
 quantity double precision NOT NULL CHECK(quantity BETWEEN -100000 AND 100000),
 unit text NOT NULL CHECK(unit IN ('tablet','capsule')),
 low_threshold double precision NOT NULL CHECK(low_threshold BETWEEN 0 AND 10000),
 note text NOT NULL DEFAULT '' CHECK(length(note)<=500),
 stock_after double precision NOT NULL CHECK(stock_after BETWEEN 0 AND 10000000),
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 source text NOT NULL DEFAULT 'patient_confirmed' CHECK(source='patient_confirmed'),
 demo_only boolean NOT NULL DEFAULT true CHECK(demo_only),
 PRIMARY KEY(patient_id,id),
 FOREIGN KEY(patient_id,medication_id) REFERENCES public.patient_medications(patient_id,id) ON DELETE RESTRICT,
 CHECK(kind='adjustment' OR (kind='count' AND quantity>=0) OR (kind IN ('refill','lost','discarded','damaged') AND quantity>0))
);
CREATE INDEX inventory_medication_time ON public.inventory_transactions(patient_id,medication_id,recorded_at,id);

CREATE TABLE public.medication_care_tasks (
 patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id) ON DELETE RESTRICT,
 id uuid NOT NULL, medication_id uuid, regimen_id uuid,
 category text NOT NULL CHECK(category IN ('medication_review','medication_follow_up','refill','monitoring','adherence','symptom_follow_up','expiry_storage')),
 title text NOT NULL CHECK(length(trim(title)) BETWEEN 1 AND 160),
 due_at timestamptz NOT NULL,
 status text NOT NULL DEFAULT 'open' CHECK(status IN ('open','contacted','deferred','completed','cancelled')),
 notes text NOT NULL DEFAULT '' CHECK(length(notes)<=1000),
 source text NOT NULL DEFAULT 'patient_reported' CHECK(source IN ('patient_reported','stock_estimate')),
 version integer NOT NULL DEFAULT 1 CHECK(version>=1),
 history jsonb NOT NULL DEFAULT '[]'::jsonb CHECK(jsonb_typeof(history)='array' AND jsonb_array_length(history)<=100),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 demo_only boolean NOT NULL DEFAULT true CHECK(demo_only),
 PRIMARY KEY(patient_id,id),
 FOREIGN KEY(patient_id,medication_id) REFERENCES public.patient_medications(patient_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(patient_id,regimen_id) REFERENCES public.regimen_versions(patient_id,id) ON DELETE RESTRICT
);
CREATE INDEX medication_tasks_due ON public.medication_care_tasks(patient_id,status,due_at);
CREATE TABLE public.adherence_barriers (
 patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id) ON DELETE RESTRICT,
 id uuid NOT NULL, regimen_id uuid, follow_up_task_id uuid,
 category text NOT NULL CHECK(category IN ('forgetfulness','running_out','side_effect_concern','scheduling','unclear_instructions','complexity','unsure_taken','other','prefer_not_to_say')),
 occurred_at timestamptz NOT NULL,
 description text NOT NULL DEFAULT '' CHECK(length(description)<=1000),
 chosen_action text NOT NULL DEFAULT '' CHECK(length(chosen_action)<=500),
 recorded_at timestamptz NOT NULL DEFAULT now(),
 source text NOT NULL DEFAULT 'patient_reported' CHECK(source='patient_reported'),
 demo_only boolean NOT NULL DEFAULT true CHECK(demo_only),
 PRIMARY KEY(patient_id,id),
 FOREIGN KEY(patient_id,regimen_id) REFERENCES public.regimen_versions(patient_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(patient_id,follow_up_task_id) REFERENCES public.medication_care_tasks(patient_id,id) ON DELETE RESTRICT
);
CREATE INDEX adherence_barriers_time ON public.adherence_barriers(patient_id,occurred_at);

-- Reuse the existing notification queue/worker; tasks are an alternate source.
ALTER TABLE public.notification_deliveries
 ALTER COLUMN occurrence_id DROP NOT NULL, ALTER COLUMN regimen_id DROP NOT NULL, ALTER COLUMN rule_id DROP NOT NULL,
 ADD COLUMN task_id uuid,
 ADD CONSTRAINT delivery_care_task_fk FOREIGN KEY(patient_id,task_id)
   REFERENCES public.medication_care_tasks(patient_id,id) ON DELETE RESTRICT,
 ADD CONSTRAINT delivery_one_source CHECK(
   (task_id IS NULL AND occurrence_id IS NOT NULL AND regimen_id IS NOT NULL AND rule_id IS NOT NULL) OR
   (task_id IS NOT NULL AND occurrence_id IS NULL AND regimen_id IS NULL AND rule_id IS NULL)),
 ADD CONSTRAINT delivery_task_slot UNIQUE(task_id,subscription_id,slot);

ALTER TABLE public.inventory_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.inventory_transactions FORCE ROW LEVEL SECURITY;
ALTER TABLE public.medication_care_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.medication_care_tasks FORCE ROW LEVEL SECURITY;
ALTER TABLE public.adherence_barriers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.adherence_barriers FORCE ROW LEVEL SECURITY;
CREATE POLICY inventory_owner ON public.inventory_transactions TO authenticated USING(patient_id=auth.uid()) WITH CHECK(patient_id=auth.uid());
CREATE POLICY medication_tasks_owner ON public.medication_care_tasks TO authenticated USING(patient_id=auth.uid()) WITH CHECK(patient_id=auth.uid());
CREATE POLICY adherence_barriers_owner ON public.adherence_barriers TO authenticated USING(patient_id=auth.uid()) WITH CHECK(patient_id=auth.uid());
REVOKE ALL ON public.inventory_transactions,public.medication_care_tasks,public.adherence_barriers FROM PUBLIC,anon,authenticated;
GRANT SELECT ON public.inventory_transactions,public.medication_care_tasks,public.adherence_barriers TO authenticated;
GRANT INSERT ON public.adherence_barriers TO authenticated;

-- Atomic narrow RPCs bind ownership to auth.uid(), never supplied patient IDs.
-- Direct ledger/task writes are not granted to authenticated callers.
CREATE FUNCTION public.record_inventory_transaction(p_medication_id uuid,p_values jsonb) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE owner_id uuid:=auth.uid(); previous public.inventory_transactions; existing public.inventory_transactions;
 balance double precision; delta double precision; stamp timestamptz; result public.inventory_transactions;
BEGIN
 IF owner_id IS NULL THEN RAISE EXCEPTION 'Authentication required' USING ERRCODE='42501'; END IF;
 PERFORM 1 FROM public.patient_medications WHERE patient_id=owner_id AND id=p_medication_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Medication not found' USING ERRCODE='42501'; END IF;
 SELECT * INTO existing FROM public.inventory_transactions WHERE patient_id=owner_id AND id=(p_values->>'id')::uuid;
 IF FOUND THEN
   IF existing.medication_id<>p_medication_id OR
      (to_jsonb(existing)-ARRAY['patient_id','medication_id','stock_after','recorded_at','source','demo_only'])<>p_values
   THEN RAISE EXCEPTION 'Stock key reused' USING ERRCODE='22023'; END IF;
   RETURN to_jsonb(existing);
 END IF;
 SELECT * INTO previous FROM public.inventory_transactions WHERE patient_id=owner_id AND medication_id=p_medication_id
 ORDER BY recorded_at DESC,id DESC LIMIT 1;
 IF previous.id IS NOT NULL AND previous.unit<>p_values->>'unit' THEN
   RAISE EXCEPTION 'Stock unit mismatch' USING ERRCODE='22023'; END IF;
 delta:=(p_values->>'quantity')::double precision;
 IF p_values->>'kind'='count' THEN balance:=delta;
 ELSE
   IF previous.id IS NULL THEN RAISE EXCEPTION 'Count stock first' USING ERRCODE='22023'; END IF;
   IF p_values->>'kind' IN ('lost','discarded','damaged') THEN delta:=-delta; END IF;
   balance:=previous.stock_after+delta;
 END IF;
 stamp:=clock_timestamp();
 INSERT INTO public.inventory_transactions(patient_id,medication_id,id,kind,quantity,unit,low_threshold,note,stock_after,recorded_at)
 VALUES(owner_id,p_medication_id,(p_values->>'id')::uuid,p_values->>'kind',(p_values->>'quantity')::double precision,
 p_values->>'unit',(p_values->>'low_threshold')::double precision,p_values->>'note',balance,stamp) RETURNING * INTO result;
 RETURN to_jsonb(result);
END $$;

CREATE FUNCTION public.create_medication_care_task(p_task jsonb) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE owner_id uuid:=auth.uid(); result public.medication_care_tasks;
BEGIN
 IF owner_id IS NULL THEN RAISE EXCEPTION 'Authentication required' USING ERRCODE='42501'; END IF;
 PERFORM 1 FROM public.patient_profiles WHERE user_id=owner_id FOR UPDATE;
 SELECT * INTO result FROM public.medication_care_tasks WHERE patient_id=owner_id AND id=(p_task->>'id')::uuid;
 IF FOUND THEN
   IF result.category<>p_task->>'category' OR result.title<>p_task->>'title'
      OR result.medication_id IS DISTINCT FROM (p_task->>'medication_id')::uuid
      OR result.regimen_id IS DISTINCT FROM (p_task->>'regimen_id')::uuid
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

CREATE FUNCTION public.update_medication_care_task(p_task_id uuid,p_change jsonb) RETURNS jsonb
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
REVOKE ALL ON FUNCTION public.record_inventory_transaction(uuid,jsonb),public.create_medication_care_task(jsonb),public.update_medication_care_task(uuid,jsonb) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.record_inventory_transaction(uuid,jsonb),public.create_medication_care_task(jsonb),public.update_medication_care_task(uuid,jsonb) TO authenticated;
NOTIFY pgrst,'reload schema';
COMMIT;
