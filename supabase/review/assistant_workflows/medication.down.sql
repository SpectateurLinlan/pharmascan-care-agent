-- REVIEW ONLY / NOT APPLIED. Preserve all clinical facts, audit and nonempty receipts.
BEGIN;
SET LOCAL lock_timeout='5s';
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.assistant_medication_commands)
 OR EXISTS(SELECT 1 FROM public.assistant_enrollment_originals)
 OR EXISTS(SELECT 1 FROM public.assistant_enrollment_operations) THEN
  RAISE EXCEPTION 'Nonempty medication workflow metadata; retain native history and compatibility fences';
 END IF;
END $$;
DROP FUNCTION public.assistant_draft_deletion_result(text,uuid);

REVOKE ALL ON FUNCTION public.assistant_medication_write(jsonb) FROM authenticated;
REVOKE ALL ON FUNCTION public.assistant_medication_read(jsonb) FROM authenticated;
DROP FUNCTION public.assistant_medication_read(jsonb);
DROP FUNCTION public.assistant_medication_write(jsonb);
DROP FUNCTION public.assistant_medication_registration(uuid,jsonb,jsonb,jsonb,jsonb);
DROP FUNCTION public.assistant_medication_native_source(uuid,jsonb,jsonb);
DROP FUNCTION public.assistant_medication_assert_original(uuid,uuid,uuid,jsonb);
DROP FUNCTION public.assistant_medication_native_result(uuid,uuid);
DROP FUNCTION public.assistant_medication_native_enrollment(uuid,jsonb,jsonb,jsonb,text);
DROP FUNCTION public.assistant_medication_prepared_fields(jsonb,jsonb);
DROP FUNCTION public.assistant_medication_printed_matches(jsonb,jsonb);
DROP FUNCTION public.assistant_medication_rule_matches(jsonb,jsonb,text);
DROP FUNCTION public.assistant_medication_projection(jsonb,text);
-- Keep empty command/original association metadata,036-compatible columns,
-- owner-first native wrappers, statement triggers and the narrow review guard.
-- They are compatibility fences, not data cleanup. Removing their dependencies
-- or restoring old function ACL/owners requires separately reviewed recovery.
-- This down disables the new fixed entry point; it is not a full035/036 restore.
COMMIT;
