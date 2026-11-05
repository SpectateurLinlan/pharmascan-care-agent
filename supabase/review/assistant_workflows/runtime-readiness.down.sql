-- REVIEW ONLY. Disable runtime flags first. Preserve every acceptance/revocation.
BEGIN;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM assistant_evidence.runtime_releases) THEN
        RAISE EXCEPTION 'Release history exists; preserve the readiness schema';
    END IF;
END $$;
DROP FUNCTION public.assistant_runtime_readiness();
DROP FUNCTION assistant_evidence.runtime_readiness();
DROP TABLE assistant_evidence.runtime_releases;
COMMIT;
