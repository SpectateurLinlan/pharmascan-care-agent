-- REVIEW ONLY. Requires the paired workflow/native-media candidates and their roles.
-- Installation publishes no acceptance. An operator must verify the target first.
BEGIN;

CREATE TABLE assistant_evidence.runtime_releases (
    release_id uuid PRIMARY KEY,
    contract_version text NOT NULL CHECK (contract_version = 'assistant-persistence-v1'),
    application_hash text NOT NULL CHECK (application_hash ~ '^[a-f0-9]{64}$'),
    catalog_digest text NOT NULL CHECK (catalog_digest ~ '^[a-f0-9]{32}$'),
    evidence_digest text NOT NULL CHECK (evidence_digest ~ '^[a-f0-9]{64}$'),
    native_media_ready boolean NOT NULL DEFAULT false,
    accepted_at timestamptz NOT NULL,
    revoked_at timestamptz CHECK (revoked_at IS NULL OR revoked_at >= accepted_at)
);
CREATE UNIQUE INDEX runtime_releases_one_active
    ON assistant_evidence.runtime_releases (contract_version) WHERE revoked_at IS NULL;
ALTER TABLE assistant_evidence.runtime_releases ENABLE ROW LEVEL SECURITY;
ALTER TABLE assistant_evidence.runtime_releases FORCE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE assistant_evidence.runtime_releases
    FROM PUBLIC, anon, authenticated, assistant_evidence_login, assistant_evidence_owner;
GRANT USAGE ON SCHEMA assistant_evidence TO assistant_workflow_owner;
GRANT SELECT ON TABLE assistant_evidence.runtime_releases TO assistant_workflow_owner;
CREATE POLICY runtime_release_technical_read ON assistant_evidence.runtime_releases
    FOR SELECT TO assistant_workflow_owner USING (true);

CREATE FUNCTION assistant_evidence.runtime_readiness() RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, assistant_evidence
AS $$
DECLARE
    observed_digest text;
    source_count integer;
    required_present boolean;
    release assistant_evidence.runtime_releases%ROWTYPE;
BEGIN
    -- Hash metadata only. No patient, auth-user, object bytes or credential rows.
    -- Changes to definitions, ACLs, RLS, columns, indexes or role membership revoke
    -- admission until an operator reviews and publishes a new acceptance record.
    WITH metadata AS (
        SELECT 'function:' || n.nspname || '.' || p.proname || ':' ||
               pg_catalog.pg_get_function_identity_arguments(p.oid) || ':' ||
               pg_catalog.pg_get_functiondef(p.oid) || ':' ||
               p.proowner::text || ':' || coalesce(p.proacl::text, '') AS value
        FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname IN ('public', 'assistant_evidence', 'auth', 'storage')
          AND p.prokind IN ('f', 'p')
        UNION ALL
        SELECT 'table:' || c.oid::text || ':' || c.relname || ':' || c.relowner::text || ':' ||
               c.relrowsecurity::text || ':' || c.relforcerowsecurity::text || ':' ||
               coalesce(c.relacl::text, '')
        FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname IN ('public', 'assistant_evidence', 'auth', 'storage')
          AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
        UNION ALL
        SELECT 'column:' || a.attrelid::text || ':' || a.attnum::text || ':' ||
               a.attname || ':' || a.atttypid::text || ':' || a.atttypmod::text || ':' ||
               a.attnotnull::text || ':' || a.attisdropped::text || ':' ||
               coalesce(a.attacl::text, '') || ':' || coalesce(pg_catalog.pg_get_expr(d.adbin, d.adrelid), '')
        FROM pg_catalog.pg_attribute a
        JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_catalog.pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
        WHERE n.nspname IN ('public', 'assistant_evidence', 'auth', 'storage') AND a.attnum > 0
        UNION ALL
        SELECT 'policy:' || p.polrelid::text || ':' || p.polname || ':' || p.polcmd || ':' ||
               p.polpermissive::text || ':' || p.polroles::text || ':' ||
               coalesce(pg_catalog.pg_get_expr(p.polqual, p.polrelid), '') || ':' ||
               coalesce(pg_catalog.pg_get_expr(p.polwithcheck, p.polrelid), '')
        FROM pg_catalog.pg_policy p
        JOIN pg_catalog.pg_class c ON c.oid = p.polrelid
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname IN ('public', 'assistant_evidence', 'auth', 'storage')
        UNION ALL
        SELECT 'index:' || i.indexrelid::text || ':' || pg_catalog.pg_get_indexdef(i.indexrelid) || ':' ||
               i.indisvalid::text || ':' || i.indisready::text || ':' || i.indislive::text
        FROM pg_catalog.pg_index i JOIN pg_catalog.pg_class c ON c.oid = i.indrelid
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname IN ('public', 'assistant_evidence', 'auth', 'storage')
        UNION ALL
        SELECT 'constraint:' || c.oid::text || ':' || pg_catalog.pg_get_constraintdef(c.oid) || ':' ||
               c.convalidated::text
        FROM pg_catalog.pg_constraint c JOIN pg_catalog.pg_namespace n ON n.oid = c.connamespace
        WHERE n.nspname IN ('public', 'assistant_evidence', 'auth', 'storage')
        UNION ALL
        SELECT 'trigger:' || t.tgrelid::text || ':' || t.tgname || ':' || t.tgenabled || ':' ||
               pg_catalog.pg_get_triggerdef(t.oid)
        FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_class c ON c.oid = t.tgrelid
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname IN ('public', 'assistant_evidence', 'auth', 'storage')
        UNION ALL
        SELECT 'rule:' || r.ev_class::text || ':' || r.rulename || ':' || r.ev_enabled || ':' ||
               pg_catalog.pg_get_ruledef(r.oid)
        FROM pg_catalog.pg_rewrite r JOIN pg_catalog.pg_class c ON c.oid = r.ev_class
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname IN ('public', 'assistant_evidence', 'auth', 'storage')
        UNION ALL
        SELECT 'role:' || r.rolname || ':' || r.rolsuper::text || ':' || r.rolinherit::text || ':' ||
               r.rolcreaterole::text || ':' || r.rolcreatedb::text || ':' || r.rolcanlogin::text || ':' ||
               r.rolreplication::text || ':' || r.rolbypassrls::text
        FROM pg_catalog.pg_roles r
        WHERE r.rolname LIKE 'assistant_%' OR r.rolname IN ('anon', 'authenticated')
        UNION ALL
        SELECT 'member:' || m.roleid::text || ':' || m.member::text || ':' || m.admin_option::text
        FROM pg_catalog.pg_auth_members m
        UNION ALL
        SELECT 'schema:' || n.nspname || ':' || n.nspowner::text || ':' || coalesce(n.nspacl::text, '')
        FROM pg_catalog.pg_namespace n WHERE n.nspname IN ('public', 'assistant_evidence', 'auth', 'storage')
        UNION ALL
        SELECT 'default:' || d.defaclrole::text || ':' || d.defaclnamespace::text || ':' ||
               d.defaclobjtype || ':' || d.defaclacl::text FROM pg_catalog.pg_default_acl d
    ) SELECT md5(string_agg(value, E'\n' ORDER BY value COLLATE "C")) INTO observed_digest FROM metadata;

    SELECT bool_and(to_regprocedure(name) IS NOT NULL) INTO required_present
    FROM unnest(ARRAY[
        'public.assistant_workflow_mutate(jsonb)', 'public.assistant_message_command(jsonb)',
        'public.assistant_conversation_transition(jsonb)', 'public.assistant_notification_transition(jsonb)',
        'public.assistant_run_control(jsonb)', 'public.assistant_original_command(jsonb)',
        'public.assistant_original_object_access(uuid,uuid,text)', 'public.assistant_native_media_command(jsonb)',
        'public.assistant_medication_write(jsonb)', 'public.assistant_medication_read(jsonb)',
        'public.assistant_record_write(jsonb)', 'public.assistant_record_read(jsonb)',
        'public.assistant_care_write(jsonb)', 'public.assistant_care_read(jsonb)',
        'public.assistant_media_write(jsonb)', 'public.assistant_media_read(jsonb)',
        'public.assistant_settings_write(jsonb)', 'public.assistant_settings_read(jsonb)',
        'public.assistant_reminder_write(jsonb)', 'public.assistant_reminder_read(jsonb)',
        'assistant_evidence.record_storage_observation(jsonb)',
        'assistant_evidence.record_run_observation(jsonb)',
        'assistant_evidence.record_media_storage_observation(jsonb)',
        'assistant_evidence.record_media_delete_observation(jsonb)',
        'assistant_evidence.record_native_media_observation(jsonb)',
        'public.assistant_runtime_readiness()'
    ]) AS name;
    SELECT count(*) INTO source_count FROM assistant_evidence.runtime_releases
        WHERE contract_version = 'assistant-persistence-v1' AND revoked_at IS NULL;
    SELECT * INTO release FROM assistant_evidence.runtime_releases
        WHERE contract_version = 'assistant-persistence-v1' AND revoked_at IS NULL LIMIT 1;
    RETURN jsonb_build_object(
        'contract_version', 'assistant-persistence-v1',
        'accepted', coalesce(source_count = 1 AND required_present AND
                    release.catalog_digest = observed_digest, false),
        'release_id', release.release_id,
        'application_hash', release.application_hash,
        'catalog_digest', observed_digest,
        'native_media_ready', coalesce(release.native_media_ready, false)
    );
END;
$$;
ALTER FUNCTION assistant_evidence.runtime_readiness() OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION assistant_evidence.runtime_readiness() FROM PUBLIC, anon, authenticated, assistant_evidence_owner;
GRANT EXECUTE ON FUNCTION assistant_evidence.runtime_readiness() TO assistant_evidence_login, assistant_workflow_owner;

CREATE FUNCTION public.assistant_runtime_readiness() RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, assistant_evidence
AS $$ SELECT assistant_evidence.runtime_readiness() $$;
ALTER FUNCTION public.assistant_runtime_readiness() OWNER TO assistant_workflow_owner;
REVOKE ALL ON FUNCTION public.assistant_runtime_readiness() FROM PUBLIC, anon, assistant_evidence_login, assistant_evidence_owner;
GRANT EXECUTE ON FUNCTION public.assistant_runtime_readiness() TO authenticated;
COMMIT;
