-- REVIEW DRAFT, NOT APPLIED. Disable composition first; preserve any data.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.assistant_enrollment_operations)
 OR EXISTS(SELECT 1 FROM public.assistant_enrollment_generations) THEN
  RAISE EXCEPTION 'Enrollment receipts/revisions remain; use feature rollback and preserve records';
 END IF;
END $$;
DROP TRIGGER assistant_enrollment_guard_activation ON public.regimen_versions;
DROP TRIGGER assistant_enrollment_guard_challenge ON public.confirmation_challenges;
DROP TRIGGER assistant_enrollment_guard_field ON public.source_fields;
DROP TRIGGER assistant_enrollment_guard_source ON public.source_documents;
DROP TRIGGER assistant_enrollment_generation_regimens ON public.regimen_versions;
DROP TRIGGER assistant_enrollment_generation_medications ON public.patient_medications;
DROP TRIGGER assistant_enrollment_generation_fields ON public.source_fields;
DROP TRIGGER assistant_enrollment_generation_sources ON public.source_documents;
DROP FUNCTION public.assistant_enrollment_prepare_once(uuid,uuid,int,bigint,text,text,jsonb);
DROP FUNCTION public.assistant_enrollment_review_guard();
DROP FUNCTION public.assistant_enrollment_assert_current(uuid,uuid);
DROP FUNCTION public.assistant_enrollment_generation();
DROP TABLE public.assistant_enrollment_operations;
DROP TABLE public.assistant_enrollment_generations;
COMMIT;
