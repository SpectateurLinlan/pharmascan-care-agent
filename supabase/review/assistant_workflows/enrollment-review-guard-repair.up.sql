-- REVIEW ONLY. Apply only after the exact hosted guard definition is checked.
-- Preserve existing function ownership, ACLs, policies and all review fences.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';

CREATE OR REPLACE FUNCTION public.assistant_enrollment_review_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE rid uuid; sid uuid;
BEGIN
 IF TG_TABLE_NAME='source_fields' THEN
 IF NEW.field_name='medication_name' AND TG_OP='UPDATE'
 AND NEW.patient_id=OLD.patient_id AND NEW.source_id=OLD.source_id AND NEW.id=OLD.id
 AND NEW.field_value=OLD.field_value AND OLD.review_status='extracted' AND NEW.review_status='user_reviewed'
 AND EXISTS(SELECT 1 FROM public.assistant_medication_commands cmd
 JOIN public.assistant_workflow_tasks t ON t.owner=cmd.owner AND t.id=cmd.task_id
 JOIN public.assistant_workflow_operations ctl ON ctl.owner=cmd.owner AND ctl.task_id=cmd.task_id AND ctl.record_type='control'
 JOIN public.regimen_versions r ON r.patient_id=cmd.owner AND r.id=cmd.native_result_id
 JOIN public.patient_medications m ON m.patient_id=r.patient_id AND m.id=r.patient_medication_id
 WHERE cmd.owner=NEW.patient_id AND cmd.kind='review_identity' AND cmd.state='pending'
 AND cmd.binding_revision=(t.data->>'revision')::int AND t.data->>'state'='awaiting_confirmation'
 AND ctl.data->>'mode'='allowed' AND ctl.data->>'revoked'='false' AND ctl.data->>'status'='idle'
 AND t.data->'business_refs' @> jsonb_build_array(jsonb_build_object('kind','regimen','id',r.id,'version',r.version_no))
 AND m.source_id=NEW.source_id AND NEW.field_value=to_jsonb(m.display_name)) THEN RETURN NEW; END IF;
 END IF;
 IF TG_TABLE_NAME='confirmation_challenges' THEN
  IF NEW.action='activate_regimen' THEN PERFORM public.assistant_enrollment_assert_current(NEW.patient_id,NEW.regimen_id); END IF;
 ELSIF TG_TABLE_NAME='regimen_versions' THEN
  IF NEW.state='active' THEN PERFORM public.assistant_enrollment_assert_current(NEW.patient_id,NEW.id); END IF;
 ELSE
  IF TG_TABLE_NAME='source_documents' THEN sid:=NEW.id; ELSE sid:=NEW.source_id; END IF;
  FOR rid IN SELECT regimen_id FROM public.assistant_enrollment_operations WHERE owner=NEW.patient_id AND source_id=sid LOOP
   PERFORM public.assistant_enrollment_assert_current(NEW.patient_id,rid);
  END LOOP;
 END IF;
 RETURN NEW;
END $$;

COMMIT;
