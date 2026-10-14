-- Destructive: disposable database only, never run against shared/dev patient contacts.
BEGIN;
DROP TABLE public.caregiver_contacts;
COMMIT;
