BEGIN;
CREATE TABLE public.dose_reminders (
 patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id) ON DELETE RESTRICT,
 occurrence_id uuid NOT NULL,
 remind_at timestamptz NOT NULL,
 demo_only boolean NOT NULL DEFAULT true CHECK (demo_only = true),
 PRIMARY KEY(patient_id,occurrence_id),
 FOREIGN KEY(patient_id,occurrence_id) REFERENCES public.dose_occurrences(patient_id,id) ON DELETE RESTRICT
);
CREATE INDEX dose_reminders_due_idx ON public.dose_reminders(patient_id,remind_at);
ALTER TABLE public.dose_reminders ENABLE ROW LEVEL SECURITY;
CREATE POLICY dose_reminders_owner ON public.dose_reminders FOR ALL TO authenticated
 USING(patient_id = auth.uid()) WITH CHECK(patient_id = auth.uid());
GRANT SELECT,INSERT,UPDATE ON public.dose_reminders TO authenticated;
CREATE FUNCTION public.core_guard_dose_reminder() RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER AS $$
BEGIN
 IF TG_OP = 'UPDATE' AND (NEW.patient_id, NEW.occurrence_id) IS DISTINCT FROM (OLD.patient_id, OLD.occurrence_id) THEN
  RAISE EXCEPTION 'Reminder binding is immutable';
 END IF;
 IF NEW.remind_at <= now() OR NEW.remind_at > now() + interval '24 hours 1 minute' THEN
  RAISE EXCEPTION 'Reminder time must be bounded and future';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM public.dose_occurrences o JOIN public.regimen_versions r
 ON r.patient_id=o.patient_id AND r.id=o.regimen_id
 WHERE o.patient_id=NEW.patient_id AND o.id=NEW.occurrence_id AND o.status <> 'closed' AND r.state='active') THEN
  RAISE EXCEPTION 'Reminder needs an open occurrence of an active regimen';
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER dose_reminders_guard BEFORE INSERT OR UPDATE ON public.dose_reminders
 FOR EACH ROW EXECUTE FUNCTION public.core_guard_dose_reminder();
REVOKE ALL ON FUNCTION public.core_guard_dose_reminder() FROM PUBLIC;
ALTER TABLE public.agent_tool_calls DROP CONSTRAINT agent_tool_calls_tool_name_check;
ALTER TABLE public.agent_tool_calls ADD CONSTRAINT agent_tool_calls_tool_name_check CHECK(tool_name IN
 ('list_active_medications','get_medication_history','get_dose_status','enroll_medication_draft',
 'confirm_regimen_draft','check_due_dose','record_self_report','create_reminder'));
ALTER TABLE public.agent_sessions DROP CONSTRAINT agent_sessions_intent_check;
ALTER TABLE public.agent_sessions ADD CONSTRAINT agent_sessions_intent_check CHECK(intent IN
 ('medication_enrollment','dose_self_report','dose_status_query','medication_history','clarification','reminder'));
NOTIFY pgrst, 'reload schema';
COMMIT;
