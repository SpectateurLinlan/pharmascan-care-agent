-- Disposable database only; preserve submitted feedback on shared/dev projects.
BEGIN;
DO $$ BEGIN
 IF current_setting('pharmascan.allow_destructive_rollback',true) IS DISTINCT FROM 'disposable_test_database'
 THEN RAISE EXCEPTION 'Disposable test database acknowledgement required';END IF;
 IF EXISTS(SELECT 1 FROM public.patient_feedback) THEN RAISE EXCEPTION 'Feedback exists; rollback refused';END IF;
END $$;
DROP TABLE public.patient_feedback RESTRICT;
COMMIT;
