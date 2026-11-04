-- REVIEW ONLY / NOT APPLIED. Never remove a live exclusion or unknown writer.
BEGIN;
SET LOCAL lock_timeout='5s';
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.assistant_original_deletions)
 OR EXISTS(SELECT 1 FROM public.assistant_storage_tickets)
 OR EXISTS(SELECT 1 FROM public.assistant_workflow_attachments)
 OR EXISTS(SELECT 1 FROM public.assistant_workflow_operations WHERE record_type='cleanup') THEN
  RAISE EXCEPTION 'Original metadata is nonempty; retain proof, exclusions and compatibility fences';
 END IF;
END $$;
DROP FUNCTION public.assistant_original_object_access(uuid,uuid,text);

DROP FUNCTION public.assistant_original_command(jsonb);
DROP FUNCTION assistant_evidence.storage_ticket_projection(uuid);
-- Preserve the private035 implementation, public proof-denying wrapper and
-- original reference/metadata compatibility guards. Exact baseline restoration
-- requires a separately reviewed full035/036 recovery; this down never destroys data.
-- Keep the empty exclusion table because the retained compatibility triggers
-- still consult it. Dropping it would break all subsequent035 native writes.
DROP POLICY assistant_storage_patient_command ON public.assistant_storage_tickets;
DROP POLICY assistant_verified_patient_command ON public.assistant_verified_operations;
REVOKE SELECT,INSERT,UPDATE ON public.assistant_storage_tickets FROM assistant_workflow_owner;
REVOKE SELECT ON public.assistant_verified_operations FROM assistant_workflow_owner;
COMMIT;
