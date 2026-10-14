-- Gate1 / Session 3D: RLS-enforced patient access path.
--
-- WHY THIS FILE EXISTS
-- --------------------
-- Until now the application connected as the ``DATABASE_URL`` role, which is
-- ``postgres`` on the Supabase development project. That role has
-- ``rolbypassrls = true`` (verified live: see status/WORK_LOG.md Session 3D),
-- so the row-level security policies of 202610130001_core.sql did **not**
-- protect the normal patient CRUD path. Isolation rested entirely on the
-- repository adapters remembering to write ``patient_id = %s``.
--
-- That is a single control. This migration adds a second, independent one by
-- introducing a dedicated role that the database itself enforces RLS for.
--
-- THE TRUST BOUNDARY
-- ------------------
--   privileged (``postgres``, BYPASSRLS)
--       migrations, schema verification, maintenance, and *admin setup* only
--       (e.g. provisioning a synthetic demo patient). Never the normal
--       patient read/write path.
--
--   patient (``pharmascan_patient``, NOBYPASSRLS)
--       every normal authenticated patient request. The application opens a
--       transaction, ``SET LOCAL ROLE pharmascan_patient`` and sets
--       ``request.jwt.claims.sub`` from the **verified** access token, so
--       ``auth.uid()`` resolves to that patient and the existing
--       ``*_owner`` policies apply. A forgotten ``WHERE patient_id = ...``
--       can therefore no longer leak another patient's row.
--
-- WHY NOT MAKE ``authenticated`` ITSELF WRITABLE
-- ----------------------------------------------
-- ``authenticated`` is the role PostgREST assumes from a user JWT. Its
-- ``EXECUTE`` grants are what decide which functions become callable RPCs at
-- ``/rest/v1/rpc/...``. The guard triggers are ``SECURITY INVOKER`` and call
-- ``public.core_consume_confirmation`` internally, so granting ``authenticated``
-- the DML it would need also means granting it ``EXECUTE`` on those guards —
-- turning them into directly callable write RPCs, which the core migration
-- explicitly forbids ("Supabase 默认函数权限不能成为 PostgREST 中可直接调用的确认/写入
-- RPC"). ``pharmascan_patient`` is ``NOLOGIN`` and is not a member of
-- ``authenticator``, so PostgREST can never ``SET ROLE`` into it: the guards
-- stay unreachable over the Data API while the patient role still gets the
-- DML it needs.
--
-- WHAT THIS MIGRATION DOES NOT DO
-- -------------------------------
-- It creates no patient row, stores no data and weakens no existing
-- constraint. Every ``*_owner`` policy is left exactly as it was; the new role
-- only *inherits* the ability to be matched by them.
--
-- Rollback: supabase/rollback/202610130004_patient_rls_role_down.sql
BEGIN;
SET LOCAL TIME ZONE 'UTC';
SET LOCAL search_path = pg_catalog, public;

-- 1) The dedicated, non-PostgREST patient role.
--
--    NOLOGIN   : nothing can connect as it; it is only ever assumed by SET ROLE.
--    NOBYPASSRLS: the whole point — RLS applies to it.
--    INHERIT   : default, and required so it inherits ``authenticated`` below.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pharmascan_patient') THEN
        CREATE ROLE pharmascan_patient
            NOLOGIN
            NOSUPERUSER
            NOCREATEDB
            NOCREATEROLE
            NOBYPASSRLS;
    END IF;
END;
$$;

-- 2) Let the application's own connection assume the role for one transaction.
--    Granting to ``current_user`` (rather than a hard-coded ``postgres``) keeps
--    the file portable across environments; the runner always applies
--    migrations as the DATABASE_URL role.
DO $$
BEGIN
    EXECUTE format('GRANT pharmascan_patient TO %I', current_user);
END;
$$;

-- 3) Inherit ``authenticated`` so the role is matched by the existing
--    ``*_owner`` policies, already holds USAGE on the ``auth`` schema (needed
--    for ``auth.uid()``) and can execute ``auth.uid()`` itself. The ``auth``
--    schema is owned by ``supabase_admin`` and cannot be granted directly, so
--    inheritance is the supported route.
GRANT authenticated TO pharmascan_patient;

-- 4) Schema and table privileges.
--
--    ``medication_products`` and ``audit_events`` are read-only for the patient
--    path: the product catalogue is shared synthetic data and the audit log is
--    append-only history the application does not write from a patient request.
--    ``dose_events`` is append-only by trigger (``core_reject_mutation``), so it
--    receives no UPDATE/DELETE, mirroring the ``service_role`` grant set.
GRANT USAGE ON SCHEMA public TO pharmascan_patient;

GRANT SELECT ON TABLE public.medication_products, public.audit_events
    TO pharmascan_patient;
GRANT SELECT, INSERT ON TABLE public.dose_events TO pharmascan_patient;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
    public.patient_profiles,
    public.source_documents,
    public.source_fields,
    public.patient_medications,
    public.regimen_versions,
    public.dose_rules,
    public.dose_occurrences,
    public.agent_sessions,
    public.confirmation_challenges,
    public.agent_tool_calls
TO pharmascan_patient;

-- 5) Function privileges.
--
--    The guard triggers are SECURITY INVOKER, so the role that performs the
--    write must itself be able to execute them and the helpers they call.
--    These grants do NOT make them PostgREST RPCs: only the role name
--    ``pharmascan_patient`` is granted, and PostgREST cannot assume it.
GRANT EXECUTE ON FUNCTION public.core_trace_summary_is_safe(jsonb),
    public.core_validate_timezone(),
    public.core_freeze_reviewed_source(),
    public.core_consume_confirmation(uuid, uuid, text, uuid, uuid, text, text),
    public.core_guard_challenge(),
    public.core_guard_regimen(),
    public.core_guard_medication_history(),
    public.core_guard_rule(),
    public.core_guard_occurrence(),
    public.core_guard_dose_event(),
    public.core_reject_mutation(),
    public.core_guard_tool_call()
TO pharmascan_patient;

-- 6) Administrative separation: the migration ledger is runner bookkeeping, not
--    domain data, and must not be reachable from an end-user request.
--
--    Verified live before this fix: ``anon`` and ``authenticated`` both held
--    SELECT/INSERT/UPDATE/DELETE/TRUNCATE on ``public.core_schema_migrations``,
--    which PostgREST exposes — i.e. any anonymous caller could have erased or
--    rewritten the record of which migrations have been applied. The ledger is
--    created by the runner, so this is guarded for the case where the migration
--    is applied to a database whose ledger does not exist yet.
DO $$
BEGIN
    IF to_regclass('public.core_schema_migrations') IS NOT NULL THEN
        EXECUTE 'REVOKE ALL ON TABLE public.core_schema_migrations '
                'FROM PUBLIC, anon, authenticated, pharmascan_patient';
    END IF;
END;
$$;

COMMIT;
