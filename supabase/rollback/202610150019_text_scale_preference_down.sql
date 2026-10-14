-- Disposable database only; removing the column discards numeric UX preferences.
BEGIN;
DROP TRIGGER patient_text_scale_compatibility ON public.patient_profiles;
DROP FUNCTION public.core_text_scale_compatibility();
ALTER TABLE public.patient_profiles DROP COLUMN text_scale_percent;
COMMIT;
