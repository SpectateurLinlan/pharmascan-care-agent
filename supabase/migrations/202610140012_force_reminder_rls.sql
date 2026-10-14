-- Align the existing reminder table with all other patient-owned tables.
BEGIN;
ALTER TABLE public.dose_reminders FORCE ROW LEVEL SECURITY;
NOTIFY pgrst, 'reload schema';
COMMIT;
