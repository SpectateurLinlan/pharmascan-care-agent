-- REVIEW ONLY / NOT APPLIED. Empty-only recovery; disable features to retain data.
BEGIN;
SET LOCAL lock_timeout='5s';
DO $$
BEGIN
 IF EXISTS(SELECT 1 FROM public.assistant_storage_tickets)
 OR EXISTS(SELECT 1 FROM public.assistant_verified_operations)
 OR EXISTS(SELECT 1 FROM public.assistant_business_receipts)
 OR EXISTS(SELECT 1 FROM public.assistant_runtime_runs)
 OR EXISTS(SELECT 1 FROM public.assistant_runtime_events) THEN
  RAISE EXCEPTION 'Refuse rollback of nonempty persistence metadata';
 END IF;
END $$;
DROP FUNCTION public.assistant_workflow_mutate(jsonb);
DROP FUNCTION assistant_evidence.record_storage_observation(jsonb);
DROP TABLE public.assistant_runtime_events;
DROP TABLE public.assistant_runtime_runs;
DROP TABLE public.assistant_business_receipts;
DROP TABLE public.assistant_verified_operations;
DROP TABLE public.assistant_storage_tickets;
-- Roles/schema and existing035/036 remain; separately approved provisioning owns them.
COMMIT;
