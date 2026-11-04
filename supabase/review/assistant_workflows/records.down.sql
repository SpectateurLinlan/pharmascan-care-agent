-- REVIEW ONLY / NOT APPLIED. Never remove patient events, corrections or audit.
BEGIN;
SET LOCAL lock_timeout='5s';
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.assistant_record_commands) THEN
  RAISE EXCEPTION 'Nonempty record transaction metadata must be retained'; END IF;
END $$;
REVOKE ALL ON FUNCTION public.assistant_record_write(jsonb),public.assistant_record_prepare(jsonb),public.assistant_record_read(jsonb),
 public.assistant_record_review_receipt(uuid,integer),public.assistant_record_result(uuid)
 FROM authenticated;
DROP FUNCTION public.assistant_record_write(jsonb),public.assistant_record_prepare(jsonb),public.assistant_record_read(jsonb),
 public.assistant_record_review_receipt(uuid,integer),public.assistant_record_result(uuid);
-- Retain empty command metadata and all native compatibility wrappers, guards,
-- supporting fixed helpers, owner policies and permissions. Native unbound APIs
-- still execute their original rules; no retained bound challenge is orphaned.
-- This disables new workflow entry points and is not a full foundation restore.
-- Further removal needs a reviewed sequence and must never delete native history.
COMMIT;
