-- REVIEW ONLY / NOT APPLIED. Keep native profiles, contacts, feedback and history.
BEGIN;
SET LOCAL lock_timeout='5s';
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.assistant_settings_commands) THEN RAISE EXCEPTION 'Nonempty settings command metadata must be retained'; END IF;
END $$;
REVOKE ALL ON FUNCTION public.assistant_settings_revision(),public.assistant_settings_prepare(jsonb),public.assistant_settings_write(jsonb),public.assistant_settings_read(jsonb) FROM authenticated;
-- Epoch/owner fences and empty metadata remain dependencies. A whole-foundation
-- teardown or route rollback needs a separately reviewed recovery sequence.
COMMIT;
