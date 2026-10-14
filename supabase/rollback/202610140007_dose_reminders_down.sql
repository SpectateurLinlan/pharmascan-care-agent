-- Only for disposable DBs. Existing reminder traces prevent rollback unless safely handled separately.
BEGIN;
ALTER TABLE public.agent_sessions DROP CONSTRAINT agent_sessions_intent_check;
ALTER TABLE public.agent_sessions ADD CONSTRAINT agent_sessions_intent_check CHECK(intent IN
 ('medication_enrollment','dose_self_report','dose_status_query','medication_history','clarification'));
ALTER TABLE public.agent_tool_calls DROP CONSTRAINT agent_tool_calls_tool_name_check;
ALTER TABLE public.agent_tool_calls ADD CONSTRAINT agent_tool_calls_tool_name_check CHECK(tool_name IN
 ('list_active_medications','get_medication_history','get_dose_status','enroll_medication_draft',
 'confirm_regimen_draft','check_due_dose','record_self_report'));
DROP TABLE public.dose_reminders;
DROP FUNCTION public.core_guard_dose_reminder();
NOTIFY pgrst, 'reload schema';
COMMIT;
