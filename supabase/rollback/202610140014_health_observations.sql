-- Destructive rollback: disposable database only; never run against shared development data.
BEGIN;
DROP TABLE public.health_observations;
COMMIT;
