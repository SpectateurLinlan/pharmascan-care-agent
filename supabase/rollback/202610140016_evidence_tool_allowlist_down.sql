DROP FUNCTION public.store_personal_reference(jsonb,jsonb,jsonb);
-- Disposable DB only; preserve shared history.
ALTER TABLE public.agent_tool_calls DROP CONSTRAINT agent_tool_calls_tool_name_check;
ALTER TABLE public.agent_tool_calls ADD CONSTRAINT agent_tool_calls_tool_name_check CHECK(tool_name IN
 ('list_active_medications','get_medication_history','get_dose_status','enroll_medication_draft',
 'confirm_regimen_draft','check_due_dose','record_self_report','create_reminder'));
