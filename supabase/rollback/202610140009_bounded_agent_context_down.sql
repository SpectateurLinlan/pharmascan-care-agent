-- Disposable DB only; session context is patient-owned data.
BEGIN;
ALTER TABLE public.agent_sessions DROP CONSTRAINT agent_context_bounds,
 DROP CONSTRAINT agent_context_medication_owner,DROP CONSTRAINT agent_context_regimen_owner,
 DROP CONSTRAINT agent_context_occurrence_owner,DROP COLUMN context_medication_id,
 DROP COLUMN context_regimen_id,DROP COLUMN context_occurrence_id,DROP COLUMN context;
COMMIT;
