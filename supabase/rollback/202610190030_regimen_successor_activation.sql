-- Roll back only the successor-activation RPC introduced by migration 030.
-- This does not alter regimen, dose, challenge, or audit data already written.
BEGIN;
DROP FUNCTION IF EXISTS public.activate_medication_regimen_version(uuid, uuid, text);
CREATE OR REPLACE FUNCTION public.core_guard_regimen_overlap() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $$
DECLARE patient_zone text; local_today date;
BEGIN
 IF NEW.state NOT IN ('draft','pending_clarification','active') THEN RETURN NEW; END IF;
 IF TG_OP='UPDATE' AND OLD.state='active' THEN RETURN NEW; END IF;
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
NOTIFY pgrst, 'reload schema';
COMMIT;
