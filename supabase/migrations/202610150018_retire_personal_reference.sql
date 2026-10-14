-- Retire a reference without erasing source/history or allowing metadata forgery.
CREATE FUNCTION public.guard_reference_retirement() RETURNS trigger
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
CREATE TRIGGER reference_retirement_guard BEFORE UPDATE ON public.medication_images
FOR EACH ROW EXECUTE FUNCTION public.guard_reference_retirement();
CREATE POLICY medication_images_retire_owner ON public.medication_images FOR UPDATE TO authenticated
 USING (patient_id=(SELECT auth.uid())) WITH CHECK (patient_id=(SELECT auth.uid()));
GRANT UPDATE(data) ON public.medication_images TO authenticated;

CREATE FUNCTION public.retire_personal_reference(p_image_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,public AS $$
DECLARE result jsonb;
BEGIN
 UPDATE public.medication_images SET data=jsonb_set(jsonb_set(data,
  '{eligibility}','"ineligible"'),'{eligibility_reason}','"patient_retired_reference"')
 WHERE id=p_image_id AND patient_id=(SELECT auth.uid()) RETURNING data INTO result;
 IF result IS NULL THEN RAISE EXCEPTION 'Owned reference not found'; END IF;
 RETURN result;
END; $$;
REVOKE ALL ON FUNCTION public.retire_personal_reference(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.retire_personal_reference(uuid) TO authenticated;
NOTIFY pgrst,'reload schema';
