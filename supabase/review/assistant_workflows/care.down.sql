-- REVIEW ONLY / NOT APPLIED. Disable new entry points; never erase native care.
BEGIN;
SET LOCAL lock_timeout='5s';
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.assistant_care_commands) THEN
  RAISE EXCEPTION 'Nonempty care transaction metadata must be retained'; END IF;
END $$;
REVOKE ALL ON FUNCTION public.assistant_care_prepare(jsonb),public.assistant_care_write(jsonb),
 public.assistant_care_read(jsonb),public.assistant_care_revision() FROM authenticated;
DROP FUNCTION public.assistant_care_prepare(jsonb),public.assistant_care_write(jsonb),
 public.assistant_care_read(jsonb),public.assistant_care_revision();
-- Keep empty metadata, epoch triggers, private helpers and native owner-fenced
-- compatibility wrappers. A full foundation restore requires separate review.
-- No observations, counts, follow-up history, barriers or audit are removed.
COMMIT;
