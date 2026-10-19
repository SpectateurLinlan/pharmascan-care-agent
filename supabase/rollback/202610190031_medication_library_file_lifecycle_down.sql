BEGIN;
SET LOCAL search_path=pg_catalog,public;

DO $$
BEGIN
 IF EXISTS (SELECT 1 FROM public.medication_library_files)
    OR EXISTS (SELECT 1 FROM public.medication_library_file_audit)
    OR EXISTS (SELECT 1 FROM public.medication_image_audit) THEN
  RAISE EXCEPTION 'Rollback refused: medication library files or lifecycle audit rows exist; preserve records and use a reviewed recovery plan';
 END IF;
END $$;

DROP TRIGGER IF EXISTS gallery_image_storage_reference_guard ON public.medication_images;
DROP FUNCTION IF EXISTS public.guard_gallery_image_storage_reference();
DROP INDEX IF EXISTS public.medication_images_storage_reference_idx;
DROP FUNCTION IF EXISTS public.register_medication_library_pdf(jsonb);
DROP FUNCTION IF EXISTS public.update_medication_library_pdf(uuid,integer,text,text,text);
DROP FUNCTION IF EXISTS public.tombstone_medication_library_pdf(uuid,boolean);
DROP FUNCTION IF EXISTS public.ack_medication_library_pdf_cleanup(uuid);
DROP FUNCTION IF EXISTS public.manage_personal_gallery_image(uuid,text,integer,text,text,boolean);
DROP FUNCTION IF EXISTS public.ack_personal_gallery_image_cleanup(uuid);
DROP TABLE IF EXISTS public.medication_image_audit;
DROP TABLE IF EXISTS public.medication_library_file_audit;
DROP TABLE IF EXISTS public.medication_library_files;

CREATE OR REPLACE FUNCTION public.guard_reference_retirement() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,public AS $$
BEGIN
 IF NEW.id IS DISTINCT FROM OLD.id OR NEW.patient_id IS DISTINCT FROM OLD.patient_id
  OR NEW.medication_id IS DISTINCT FROM OLD.medication_id OR NEW.source_id IS DISTINCT FROM OLD.source_id
  OR (NEW.data - 'eligibility' - 'eligibility_reason') IS DISTINCT FROM
     (OLD.data - 'eligibility' - 'eligibility_reason')
  OR (NEW.data->>'eligibility') IS DISTINCT FROM 'ineligible'
  OR (NEW.data->>'eligibility_reason') IS DISTINCT FROM 'patient_retired_reference' THEN
  RAISE EXCEPTION 'Only owned reference retirement is allowed';
 END IF;
 RETURN NEW;
END; $$;
GRANT UPDATE(data) ON public.medication_images TO authenticated;

CREATE OR REPLACE FUNCTION public.retire_personal_reference(p_image_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,public AS $$
DECLARE result jsonb;
BEGIN
 UPDATE public.medication_images SET data=jsonb_set(jsonb_set(data,
  '{eligibility}','"ineligible"'),'{eligibility_reason}','"patient_retired_reference"')
 WHERE id=p_image_id AND patient_id=(SELECT auth.uid()) RETURNING data INTO result;
 IF result IS NULL THEN RAISE EXCEPTION 'Owned reference not found'; END IF;
 RETURN result;
END; $$;
COMMIT;
