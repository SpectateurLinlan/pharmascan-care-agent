-- REVIEW ONLY / NOT APPLIED. Withdraw new evidence interfaces after native entry points.
BEGIN;
SET LOCAL lock_timeout='5s';
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.assistant_media_copy_tickets)
 OR EXISTS(SELECT 1 FROM public.assistant_media_delete_tickets)
 OR EXISTS(SELECT 1 FROM public.assistant_media_copy_verifications)
 OR EXISTS(SELECT 1 FROM public.assistant_media_delete_verifications)
 OR EXISTS(SELECT 1 FROM public.assistant_native_media_deletions) THEN
  RAISE EXCEPTION 'Nonempty native media evidence and exclusions must be retained'; END IF;
END $$;
REVOKE ALL ON FUNCTION assistant_evidence.record_media_storage_observation(jsonb),
 assistant_evidence.record_media_delete_observation(jsonb) FROM assistant_evidence_login;
-- Retain technical tables, immutable guards, RLS and support functions.
-- No patient records, audit, objects or exclusions are removed. Not a full restore.
COMMIT;
