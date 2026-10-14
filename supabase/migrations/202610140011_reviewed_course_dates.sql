-- Course calendar dates are separate from regimen-version effective timestamps.
BEGIN;
ALTER TABLE public.regimen_versions ADD COLUMN course_start_date date,ADD COLUMN course_end_date date,
 ADD CONSTRAINT regimen_course_dates CHECK(course_end_date IS NULL OR (course_start_date IS NOT NULL AND course_end_date>=course_start_date));
ALTER TABLE public.source_fields DROP CONSTRAINT source_fields_field_name_check;
ALTER TABLE public.source_fields ADD CONSTRAINT source_fields_field_name_check CHECK(field_name IN (
 'medication_name','dose_amount','dose_unit','frequency_rule','is_prn','route','food_instruction','strength','form','course_start_date','course_end_date'));
CREATE FUNCTION public.core_guard_course_evidence() RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER AS $$
DECLARE item record;
BEGIN
 IF TG_OP='UPDATE' AND OLD.state IN ('active','ended','superseded') AND
 (NEW.course_start_date,NEW.course_end_date) IS DISTINCT FROM (OLD.course_start_date,OLD.course_end_date)
 THEN RAISE EXCEPTION 'Reviewed course dates are immutable; create a new version';END IF;
 IF NEW.state='active' THEN
  FOR item IN SELECT * FROM (VALUES ('course_start_date',NEW.course_start_date),('course_end_date',NEW.course_end_date)) AS dates(name,value) LOOP
   IF item.value IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.source_fields
     WHERE patient_id=NEW.patient_id AND source_id=NEW.source_id AND field_name=item.name
     AND field_value=to_jsonb(item.value::text) AND review_status IN ('user_reviewed','professional_verified'))
     THEN RAISE EXCEPTION 'Reviewed course date evidence required';END IF;
   IF item.value IS NULL AND EXISTS(SELECT 1 FROM public.source_fields WHERE patient_id=NEW.patient_id AND source_id=NEW.source_id AND field_name=item.name)
     THEN RAISE EXCEPTION 'Course date must match source evidence';END IF;
  END LOOP;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER course_evidence_guard BEFORE INSERT OR UPDATE ON public.regimen_versions
 FOR EACH ROW EXECUTE FUNCTION public.core_guard_course_evidence();
CREATE FUNCTION public.core_guard_course_window() RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER AS $$
DECLARE r public.regimen_versions%ROWTYPE;moment timestamptz;zone text;local_day date;
BEGIN
 SELECT * INTO r FROM public.regimen_versions WHERE patient_id=NEW.patient_id AND id=NEW.regimen_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'Owned regimen required';END IF;
 IF TG_TABLE_NAME='dose_occurrences' THEN
  moment:=NEW.due_at;SELECT timezone INTO zone FROM public.dose_rules WHERE patient_id=NEW.patient_id AND id=NEW.rule_id;
 ELSIF NEW.occurrence_id IS NOT NULL THEN
  SELECT o.due_at,rule.timezone INTO moment,zone FROM public.dose_occurrences o
   JOIN public.dose_rules rule ON rule.patient_id=o.patient_id AND rule.id=o.rule_id
   WHERE o.patient_id=NEW.patient_id AND o.id=NEW.occurrence_id AND o.regimen_id=NEW.regimen_id;
 ELSE
  moment:=NEW.event_time;SELECT timezone INTO zone FROM public.patient_profiles WHERE user_id=NEW.patient_id;
 END IF;
 IF moment IS NULL OR zone IS NULL THEN RAISE EXCEPTION 'Owned schedule context required';END IF;
 local_day:=(moment AT TIME ZONE zone)::date;
 IF (r.course_start_date IS NOT NULL AND local_day<r.course_start_date) OR (r.course_end_date IS NOT NULL AND local_day>r.course_end_date)
  THEN RAISE EXCEPTION 'Dose is outside reviewed course dates';END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER course_occurrence_guard BEFORE INSERT ON public.dose_occurrences FOR EACH ROW EXECUTE FUNCTION public.core_guard_course_window();
CREATE TRIGGER course_event_guard BEFORE INSERT ON public.dose_events FOR EACH ROW EXECUTE FUNCTION public.core_guard_course_window();
REVOKE ALL ON FUNCTION public.core_guard_course_evidence(),public.core_guard_course_window() FROM PUBLIC,anon;
-- Existing owner RLS, immutable versions, and B14 guards are unchanged.
NOTIFY pgrst, 'reload schema';
COMMIT;
