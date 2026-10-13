-- Gate1 storage ownership policies (Session 3B).
--
-- WHY THIS FILE EXISTS
-- --------------------
-- Both private buckets (`medication-sources`, `visual-references`) already
-- exist in the development project, but `storage.objects` carried NO policies.
-- With RLS enabled and no policy, every non-owner role is denied — safe by
-- accident, but with no declared ownership model and no way to grant the
-- patient access to their own object. This migration states the model
-- explicitly.
--
-- OWNERSHIP MODEL
-- ---------------
-- An object's owner is the first path segment of its name, which must be the
-- owning patient's uuid:
--
--     <patient_id>/<opaque-filename>
--
-- A patient may read, write and delete only objects under their own prefix, and
-- only inside the two application buckets. Objects are never public: both
-- buckets stay `public = false`.
--
-- WHAT THIS MIGRATION DOES NOT DO
-- -------------------------------
-- It stores no object and uploads no data. The P0 slice has no photo path at
-- all (`dose_events_no_photo_ck` pins `visual_status = 'not_checked'`), so no
-- application code writes to these buckets yet. Live storage verification is
-- therefore IN_PROGRESS, not verified — see status/BLOCKERS.md.
--
-- Rollback: supabase/rollback/202610130003_storage_ownership_down.sql
BEGIN;
SET LOCAL TIME ZONE 'UTC';
SET LOCAL search_path = pg_catalog, public;

-- Idempotently ensure both buckets exist and are private. A bucket that is
-- already public is a hard error rather than a silent fix.
DO $$
DECLARE
    bucket_id text;
    is_public boolean;
BEGIN
    FOREACH bucket_id IN ARRAY ARRAY['medication-sources', 'visual-references'] LOOP
        SELECT public INTO is_public FROM storage.buckets WHERE id = bucket_id;
        IF FOUND AND is_public THEN
            RAISE EXCEPTION 'Bucket % is public; refuse to continue', bucket_id;
        END IF;
        INSERT INTO storage.buckets (id, name, public, file_size_limit)
        VALUES (bucket_id, bucket_id, false, 10485760)
        ON CONFLICT (id) DO NOTHING;
    END LOOP;
END;
$$;

-- One policy per verb; a single FOR ALL policy cannot express the INSERT
-- WITH CHECK independently of the USING clause on older servers.
DROP POLICY IF EXISTS pharmascan_objects_select_owner ON storage.objects;
CREATE POLICY pharmascan_objects_select_owner ON storage.objects
    FOR SELECT TO authenticated
    USING (
        bucket_id IN ('medication-sources', 'visual-references')
        AND (storage.foldername(name))[1] = (SELECT auth.uid())::text
    );

DROP POLICY IF EXISTS pharmascan_objects_insert_owner ON storage.objects;
CREATE POLICY pharmascan_objects_insert_owner ON storage.objects
    FOR INSERT TO authenticated
    WITH CHECK (
        bucket_id IN ('medication-sources', 'visual-references')
        AND (storage.foldername(name))[1] = (SELECT auth.uid())::text
    );

DROP POLICY IF EXISTS pharmascan_objects_update_owner ON storage.objects;
CREATE POLICY pharmascan_objects_update_owner ON storage.objects
    FOR UPDATE TO authenticated
    USING (
        bucket_id IN ('medication-sources', 'visual-references')
        AND (storage.foldername(name))[1] = (SELECT auth.uid())::text
    )
    WITH CHECK (
        bucket_id IN ('medication-sources', 'visual-references')
        AND (storage.foldername(name))[1] = (SELECT auth.uid())::text
    );

DROP POLICY IF EXISTS pharmascan_objects_delete_owner ON storage.objects;
CREATE POLICY pharmascan_objects_delete_owner ON storage.objects
    FOR DELETE TO authenticated
    USING (
        bucket_id IN ('medication-sources', 'visual-references')
        AND (storage.foldername(name))[1] = (SELECT auth.uid())::text
    );

-- Belt and braces: the storage role must not reach these buckets through the
-- application's own connection either.
REVOKE ALL ON TABLE storage.objects FROM anon;
GRANT SELECT ON TABLE storage.buckets TO authenticated;

COMMIT;
