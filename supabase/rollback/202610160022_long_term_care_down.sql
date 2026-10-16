-- Disposable environments only. Removes new records; never run on shared patient data.
BEGIN;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.notification_deliveries WHERE task_id IS NOT NULL)
 OR EXISTS(SELECT 1 FROM public.inventory_transactions)
 OR EXISTS(SELECT 1 FROM public.adherence_barriers)
 OR EXISTS(SELECT 1 FROM public.medication_care_tasks)
 OR EXISTS(SELECT 1 FROM public.health_observations WHERE kind<>'note')
 OR EXISTS(SELECT 1 FROM public.agent_tool_calls WHERE tool_name IN ('get_long_term_care','prepare_care_action'))
 THEN RAISE EXCEPTION 'Rollback requires an empty disposable feature dataset; no records were deleted'; END IF;
END $$;
ALTER TABLE public.notification_deliveries
 DROP CONSTRAINT delivery_care_task_fk,DROP CONSTRAINT delivery_one_source,DROP CONSTRAINT delivery_task_slot,
 DROP COLUMN task_id,ALTER COLUMN occurrence_id SET NOT NULL,ALTER COLUMN regimen_id SET NOT NULL,
 ALTER COLUMN rule_id SET NOT NULL;
ALTER TABLE public.agent_tool_calls DROP CONSTRAINT agent_tool_calls_tool_name_check;
ALTER TABLE public.agent_tool_calls ADD CONSTRAINT agent_tool_calls_tool_name_check CHECK(tool_name IN
 ('list_active_medications','get_medication_history','get_dose_status','enroll_medication_draft',
 'confirm_regimen_draft','check_due_dose','record_self_report','create_reminder','reconcile_medication_sources'));
DROP FUNCTION public.update_medication_care_task(uuid,jsonb);
DROP FUNCTION public.create_medication_care_task(jsonb);
DROP FUNCTION public.record_inventory_transaction(uuid,jsonb);
DROP TABLE public.adherence_barriers,public.medication_care_tasks,public.inventory_transactions;
ALTER TABLE public.health_observations DROP CONSTRAINT observation_measurement_check;
ALTER TABLE public.health_observations DROP COLUMN kind,DROP COLUMN value,DROP COLUMN secondary_value,DROP COLUMN unit;
COMMIT;
