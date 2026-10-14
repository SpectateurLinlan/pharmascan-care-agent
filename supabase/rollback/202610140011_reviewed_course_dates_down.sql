-- Disposable DB only. Fail closed if course evidence exists; never delete it.
BEGIN;
DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.source_fields WHERE field_name IN ('course_start_date','course_end_date'))
 THEN RAISE EXCEPTION 'Course evidence retained; rollback requires a disposable empty database';END IF;END $$;
DROP TRIGGER course_occurrence_guard ON public.dose_occurrences;
DROP TRIGGER course_event_guard ON public.dose_events;
DROP TRIGGER course_evidence_guard ON public.regimen_versions;
DROP FUNCTION public.core_guard_course_window(),public.core_guard_course_evidence();
ALTER TABLE public.regimen_versions DROP COLUMN course_start_date,DROP COLUMN course_end_date;
ALTER TABLE public.source_fields DROP CONSTRAINT source_fields_field_name_check;
ALTER TABLE public.source_fields ADD CONSTRAINT source_fields_field_name_check CHECK(field_name IN (
 'medication_name','dose_amount','dose_unit','frequency_rule','is_prn','route','food_instruction','strength','form'));
COMMIT;
