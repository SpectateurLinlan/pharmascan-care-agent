-- Keep progressive task reconciliation on the clinical activation boundary.
ALTER TABLE public.regimen_versions ADD COLUMN evidence_task_id uuid;
ALTER TABLE public.regimen_versions ADD CONSTRAINT regimen_evidence_task_owner_fk
 FOREIGN KEY (patient_id,evidence_task_id) REFERENCES public.medication_evidence_tasks(patient_id,id) ON DELETE RESTRICT;
CREATE UNIQUE INDEX regimen_evidence_task_unique ON public.regimen_versions(patient_id,evidence_task_id)
 WHERE evidence_task_id IS NOT NULL;
CREATE FUNCTION public.guard_evidence_activation() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,public AS $$
DECLARE task_row public.medication_evidence_tasks%ROWTYPE;
BEGIN
 IF NEW.state='active' AND NEW.evidence_task_id IS NOT NULL THEN
  SELECT * INTO task_row FROM public.medication_evidence_tasks
   WHERE patient_id=NEW.patient_id AND id=NEW.evidence_task_id FOR SHARE;
  IF NOT FOUND OR task_row.medication_id<>NEW.patient_medication_id
    OR task_row.data->>'status'<>'draft_created'
    OR task_row.data->>'draft_regimen_id'<>NEW.id::text
    OR jsonb_array_length(task_row.data->'conflicts')>0 THEN
   RAISE EXCEPTION 'Unresolved evidence task cannot activate';
  END IF;
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER regimen_evidence_activation_guard BEFORE INSERT OR UPDATE ON public.regimen_versions
 FOR EACH ROW EXECUTE FUNCTION public.guard_evidence_activation();
REVOKE ALL ON FUNCTION public.guard_evidence_activation() FROM PUBLIC;
NOTIFY pgrst,'reload schema';
