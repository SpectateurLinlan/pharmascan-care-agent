-- Rollback for 202610130003_storage_ownership.sql.
--
-- Removes the four ownership policies and restores the pre-existing state:
-- both buckets remain (they existed before this migration) and `storage.objects`
-- returns to "RLS enabled, no policy" — i.e. deny-by-default for every
-- non-owner role.
BEGIN;
SET LOCAL TIME ZONE 'UTC';
SET LOCAL search_path = pg_catalog, public;

DROP POLICY IF EXISTS pharmascan_objects_select_owner ON storage.objects;
DROP POLICY IF EXISTS pharmascan_objects_insert_owner ON storage.objects;
DROP POLICY IF EXISTS pharmascan_objects_update_owner ON storage.objects;
DROP POLICY IF EXISTS pharmascan_objects_delete_owner ON storage.objects;

COMMIT;
