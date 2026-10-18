-- Operational rollback: stop new deletions, restore prior guards/permissions.
-- Physical deletions are irreversible; restore from backup only by a separate plan.
-- Keep patient_edited and receipts (including pending Storage cleanup) intact.
BEGIN;
REVOKE ALL ON FUNCTION public.delete_unconfirmed_medication(text,uuid,boolean) FROM authenticated;
DROP TRIGGER regimen_versions_guard ON public.regimen_versions;
CREATE TRIGGER regimen_versions_guard BEFORE INSERT OR UPDATE OR DELETE ON public.regimen_versions FOR EACH ROW EXECUTE FUNCTION public.core_guard_regimen();
DROP TRIGGER confirmation_challenges_guard ON public.confirmation_challenges;
CREATE TRIGGER confirmation_challenges_guard BEFORE INSERT OR UPDATE OR DELETE ON public.confirmation_challenges FOR EACH ROW EXECUTE FUNCTION public.core_guard_challenge();
DROP TRIGGER patient_medications_history_guard ON public.patient_medications;
CREATE TRIGGER patient_medications_history_guard BEFORE UPDATE OR DELETE ON public.patient_medications FOR EACH ROW EXECUTE FUNCTION public.core_guard_medication_history();
DROP TRIGGER source_documents_history_guard ON public.source_documents;
CREATE TRIGGER source_documents_history_guard BEFORE UPDATE OR DELETE ON public.source_documents FOR EACH ROW EXECUTE FUNCTION public.core_freeze_reviewed_source();
DROP TRIGGER source_fields_history_guard ON public.source_fields;
CREATE TRIGGER source_fields_history_guard BEFORE INSERT OR UPDATE OR DELETE ON public.source_fields FOR EACH ROW EXECUTE FUNCTION public.core_freeze_reviewed_source();
GRANT DELETE ON public.patient_medications TO authenticated;
GRANT DELETE ON public.patient_profiles,public.source_documents,public.source_fields,public.patient_medications,
 public.regimen_versions,public.dose_rules,public.dose_occurrences,public.agent_sessions,public.confirmation_challenges,
 public.agent_tool_calls TO pharmascan_patient;
NOTIFY pgrst,'reload schema';
COMMIT;
