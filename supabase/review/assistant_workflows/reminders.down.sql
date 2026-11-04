-- REVIEW ONLY / NOT APPLIED. No reminder/native occurrence/history deletion.
BEGIN;
SET LOCAL lock_timeout='5s';
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.assistant_reminder_commands) THEN RAISE EXCEPTION 'Nonempty reminder command metadata must be retained'; END IF;
END $$;
REVOKE ALL ON FUNCTION public.assistant_reminder_revision(),public.assistant_reminder_prepare(jsonb),public.assistant_reminder_write(jsonb),public.assistant_reminder_read(jsonb) FROM authenticated;
-- Keep native attention guards, epochs and dependencies; route/foundation
-- recovery needs a reviewed sequence, never a blind teardown or sender enablement.
COMMIT;
