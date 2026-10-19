-- Release reconciliation: hosted default ACLs granted non-business privileges
-- beyond migrations001-028. RLS does not restrict TRUNCATE/REFERENCES/TRIGGER.
-- Supabase anonymous *signed-in* users have authenticated JWTs; anon is not a
-- patient identity. Intended CRUD/column grants/RPC/service_role/worker rights
-- stay intact; accidental direct writes beyond the documented RPCs are revoked.
-- Production execution requires owner approval. Before applying, capture ACLs
-- and default ACLs. A reviewed rollback can restore that exact capture; never
-- restore blanket dangerous grants as an application rollback side effect.
BEGIN;
SET LOCAL search_path = pg_catalog, public;
DO $$
DECLARE target record;
BEGIN
 FOR target IN
  SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
  WHERE n.nspname='public' AND c.relkind IN ('r','p') AND EXISTS (
   SELECT 1 FROM pg_attribute a WHERE a.attrelid=c.oid AND NOT a.attisdropped
    AND a.attname IN ('patient_id','user_id'))
 LOOP
  EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE public.%I FROM anon',target.relname);
  EXECUTE format('REVOKE TRUNCATE, REFERENCES, TRIGGER ON TABLE public.%I FROM authenticated',target.relname);
  IF current_setting('server_version_num')::integer >= 170000 THEN
   EXECUTE format('REVOKE MAINTAIN ON TABLE public.%I FROM authenticated',target.relname);
  END IF;
 END LOOP;
END;
$$;
-- Restore the explicit contract from015/018/021/024/026. In particular the
-- column UPDATE(data) grant for guarded image retirement remains intact.
REVOKE UPDATE,DELETE ON public.image_embeddings,public.visual_reference_sets,
 public.medication_source_links,public.recognition_runs,public.medication_images FROM authenticated;
GRANT UPDATE(data) ON public.medication_images TO authenticated;
REVOKE INSERT,UPDATE ON public.conversation_turns FROM authenticated;
REVOKE INSERT,UPDATE,DELETE ON public.notification_deliveries FROM authenticated;
REVOKE DELETE ON public.dose_reminders,public.push_subscriptions FROM authenticated;
-- Apply to future tables created by the migration owner as well. Explicit
-- application CRUD grants remain the responsibility of each domain migration.
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL PRIVILEGES ON TABLES FROM anon;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL PRIVILEGES ON TABLES FROM authenticated;
COMMIT;
