-- REVIEW ONLY / NOT APPLIED. Disable I11 typed entry points without destroying
-- native history, references, receipts, evidence or permanent deleting fences.
BEGIN;
SET LOCAL lock_timeout='5s';
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.assistant_media_copy_tickets) OR EXISTS(SELECT 1 FROM public.assistant_media_delete_tickets)
 OR EXISTS(SELECT 1 FROM public.assistant_media_commands) OR EXISTS(SELECT 1 FROM public.assistant_media_original_links)
 OR EXISTS(SELECT 1 FROM public.assistant_media_cleanup_settlements) OR EXISTS(SELECT 1 FROM public.assistant_native_media_deletions) THEN
  RAISE EXCEPTION 'Nonempty media operation metadata must be retained'; END IF;
END $$;
REVOKE ALL ON FUNCTION public.assistant_original_verification_ref(uuid,uuid),public.assistant_media_copy_command(jsonb),
 public.assistant_media_prepare(jsonb),public.assistant_media_write(jsonb),public.assistant_media_read(jsonb),
 public.assistant_media_revision(),public.assistant_media_cleanup_command(jsonb) FROM authenticated;
-- Keep compatibility wrappers and ACK proof requirements: restoring the old
-- trust-on-caller ACK would reopen a physical-deletion bypass. Graph shutdown
-- and route recovery require the I14/I15 reviewed operator procedure; this file
-- is not an automatic inverse and does not silently reactivate legacy routes.
COMMIT;
