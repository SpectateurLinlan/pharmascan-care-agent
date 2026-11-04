-- REVIEW DRAFT. Disabling the feature is the first recovery action.
-- Do not infer physical Storage removal from these database tables.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';
DO $$
BEGIN
 IF EXISTS(SELECT 1 FROM public.assistant_workflow_tasks)
 OR EXISTS(SELECT 1 FROM public.assistant_workflow_attachments)
 OR EXISTS(SELECT 1 FROM public.assistant_workflow_operations) THEN
  RAISE EXCEPTION 'Workflow records remain; preserve data and use feature rollback';
 END IF;
 IF current_setting('medithread.workflow_storage_verified_empty',true) IS DISTINCT FROM 'true' THEN
  RAISE EXCEPTION 'Explicit externally verified empty Storage prefix is required';
 END IF;
END $$;
DROP FUNCTION public.assistant_workflow_command(text,jsonb);
DROP TABLE public.assistant_workflow_attachments;
DROP TABLE public.assistant_workflow_tasks;
DROP TABLE public.assistant_workflow_operations;
DROP FUNCTION public.assistant_wf_ref(jsonb);
DROP FUNCTION public.assistant_wf_writer_ids(jsonb);
DROP FUNCTION public.assistant_wf_keys(jsonb,text[]);
COMMIT;
