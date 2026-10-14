-- Disposable DB only. No shared rollback.
DROP TRIGGER regimen_evidence_activation_guard ON public.regimen_versions;
DROP FUNCTION public.guard_evidence_activation();
DROP INDEX public.regimen_evidence_task_unique;
ALTER TABLE public.regimen_versions DROP COLUMN evidence_task_id;
