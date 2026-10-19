-- Empty ledger only. Preserve every patient statement; forward repair after use.
BEGIN;
LOCK TABLE public.dose_report_entries IN ACCESS EXCLUSIVE MODE;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.dose_report_entries) THEN
  RAISE EXCEPTION 'Patient reports exist; retain ledger/view and apply a forward fix';
 END IF;
END $$;
DROP TRIGGER zz_original_after_late_report ON public.dose_events;
DROP FUNCTION public.guard_original_after_late_report();
DROP FUNCTION public.record_late_dose_report(uuid,jsonb,uuid);
DROP VIEW public.effective_dose_events;
DROP TABLE public.dose_report_entries;
NOTIFY pgrst,'reload schema';
COMMIT;
