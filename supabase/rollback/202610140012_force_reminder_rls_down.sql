-- Disposable database only. Never weaken shared/development patient isolation.
BEGIN;
DO $$ BEGIN
 IF current_setting('pharmascan.allow_destructive_rollback',true) IS DISTINCT FROM 'disposable_test_database'
 THEN RAISE EXCEPTION 'Disposable test database acknowledgement required';END IF;
END $$;
ALTER TABLE public.dose_reminders NO FORCE ROW LEVEL SECURITY;
COMMIT;
