-- REVIEW ONLY / NOT APPLIED. Keep nonempty technical evidence and all patient data.
BEGIN;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.assistant_runtime_runs) OR EXISTS(SELECT 1 FROM public.assistant_runtime_events) THEN
  RAISE EXCEPTION 'Refuse rollback of nonempty run evidence'; END IF;
END $$;
DROP FUNCTION assistant_evidence.record_run_observation(jsonb);
DROP FUNCTION public.assistant_run_control(jsonb);
DROP FUNCTION public.assistant_run_assert_current(uuid,jsonb);
DROP FUNCTION assistant_evidence.append_run_event(uuid,uuid,uuid,text,text,text,numeric);
DROP FUNCTION assistant_evidence.run_projection(uuid,uuid,boolean);
DROP POLICY assistant_runtime_patient_command ON public.assistant_runtime_runs;
DROP POLICY assistant_runtime_event_patient_command ON public.assistant_runtime_events;
REVOKE SELECT,INSERT,UPDATE ON public.assistant_runtime_runs FROM assistant_workflow_owner;
REVOKE SELECT,INSERT ON public.assistant_runtime_events FROM assistant_workflow_owner;
ALTER TABLE public.assistant_runtime_runs DROP COLUMN operations,DROP COLUMN active_spans,DROP COLUMN attempts,DROP COLUMN responses;
COMMIT;
