-- Forward-only safety addition. Existing histories/duplicates are retained.
-- Serialize same-patient activations across independent API processes.
BEGIN;
CREATE FUNCTION public.core_guard_regimen_overlap() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $$
DECLARE patient_zone text; local_today date;
BEGIN
 IF NEW.state NOT IN ('draft','pending_clarification','active') THEN RETURN NEW; END IF;
 IF TG_OP='UPDATE' AND OLD.state='active' THEN RETURN NEW; END IF;

 -- Profile lock must precede the existing source/medication/challenge locks.
 SELECT timezone INTO patient_zone FROM public.patient_profiles
 WHERE user_id=NEW.patient_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Owned patient profile required'; END IF;
 local_today := (now() AT TIME ZONE patient_zone)::date;

 IF EXISTS (
  SELECT 1 FROM public.regimen_versions r
  JOIN public.patient_medications existing_medicine
   ON existing_medicine.patient_id=r.patient_id AND existing_medicine.id=r.patient_medication_id
  JOIN public.patient_medications incoming_medicine
   ON incoming_medicine.patient_id=NEW.patient_id AND incoming_medicine.id=NEW.patient_medication_id
  WHERE r.patient_id=NEW.patient_id AND r.state='active' AND r.id<>NEW.id
   AND (
    (existing_medicine.product_id IS NOT NULL AND existing_medicine.product_id=incoming_medicine.product_id)
    OR lower(btrim(regexp_replace(existing_medicine.display_name, '[[:space:]]+', ' ', 'g')))
       =lower(btrim(regexp_replace(incoming_medicine.display_name, '[[:space:]]+', ' ', 'g')))
   )
   AND (
    r.patient_medication_id=NEW.patient_medication_id
    OR (
     greatest(coalesce(NEW.course_start_date,local_today),local_today)
      <=coalesce(r.course_end_date,'infinity'::date)
     AND greatest(coalesce(r.course_start_date,'-infinity'::date),
                   coalesce((r.effective_from AT TIME ZONE patient_zone)::date,'-infinity'::date))
      <=coalesce(NEW.course_end_date,'infinity'::date)
    )
   )
 ) THEN
  RAISE EXCEPTION USING ERRCODE='P7501', MESSAGE='Overlapping active medication plan';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.core_guard_regimen_overlap() FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.core_guard_regimen_overlap() TO authenticated, pharmascan_patient, service_role;
-- Alphabetical trigger order puts this guard before regimen_versions_guard.
CREATE TRIGGER regimen_overlap_guard BEFORE INSERT OR UPDATE ON public.regimen_versions
 FOR EACH ROW EXECUTE FUNCTION public.core_guard_regimen_overlap();
COMMIT;
