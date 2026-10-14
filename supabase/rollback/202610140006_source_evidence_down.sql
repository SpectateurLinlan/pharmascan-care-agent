-- Administrative rollback; only execute on an explicitly disposable test DB.
BEGIN;
DROP TRIGGER source_documents_extraction_evidence_immutable ON public.source_documents;
DROP FUNCTION public.core_guard_extraction_evidence();
ALTER TABLE public.source_documents DROP COLUMN extraction_evidence;
NOTIFY pgrst, 'reload schema';
COMMIT;
