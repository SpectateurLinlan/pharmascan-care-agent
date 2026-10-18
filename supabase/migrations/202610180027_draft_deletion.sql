-- Owner-approved local draft hard-delete design. No clinical history deletion.
BEGIN;
ALTER TABLE public.regimen_versions ADD COLUMN patient_edited boolean NOT NULL DEFAULT false;

-- Keep insert/update clinical validation. SQL privileges + the atomic RPC below
-- control deletion, rather than DELETE triggers which also blocked pure drafts.
DROP TRIGGER regimen_versions_guard ON public.regimen_versions;
CREATE TRIGGER regimen_versions_guard BEFORE INSERT OR UPDATE ON public.regimen_versions
 FOR EACH ROW EXECUTE FUNCTION public.core_guard_regimen();
DROP TRIGGER confirmation_challenges_guard ON public.confirmation_challenges;
CREATE TRIGGER confirmation_challenges_guard BEFORE INSERT OR UPDATE ON public.confirmation_challenges
 FOR EACH ROW EXECUTE FUNCTION public.core_guard_challenge();
DROP TRIGGER patient_medications_history_guard ON public.patient_medications;
CREATE TRIGGER patient_medications_history_guard BEFORE UPDATE ON public.patient_medications
 FOR EACH ROW EXECUTE FUNCTION public.core_guard_medication_history();
DROP TRIGGER source_documents_history_guard ON public.source_documents;
CREATE TRIGGER source_documents_history_guard BEFORE UPDATE ON public.source_documents
 FOR EACH ROW EXECUTE FUNCTION public.core_freeze_reviewed_source();
DROP TRIGGER source_fields_history_guard ON public.source_fields;
CREATE TRIGGER source_fields_history_guard BEFORE INSERT OR UPDATE ON public.source_fields
 FOR EACH ROW EXECUTE FUNCTION public.core_freeze_reviewed_source();
REVOKE DELETE ON public.regimen_versions,public.confirmation_challenges,public.patient_medications,
 public.source_documents,public.source_fields,public.medication_evidence_tasks,public.medication_source_links,
 public.medication_images,public.visual_reference_sets,public.image_embeddings
 FROM authenticated,anon,service_role,pharmascan_patient;

-- Minimal owner-private receipt also makes an uncertain delete retryable and
-- durably retains object paths until the Storage API confirms their deletion.
CREATE TABLE public.draft_deletion_receipts (
 patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id),
 kind text NOT NULL CHECK(kind IN ('draft','source')), target_id uuid NOT NULL,
 medication_deleted boolean NOT NULL, storage_paths text[] NOT NULL DEFAULT '{}',
 created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(patient_id,kind,target_id)
);
ALTER TABLE public.draft_deletion_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.draft_deletion_receipts FORCE ROW LEVEL SECURITY;
CREATE POLICY draft_deletion_receipts_owner ON public.draft_deletion_receipts
 USING(patient_id=(SELECT auth.uid())) WITH CHECK(patient_id=(SELECT auth.uid()));
REVOKE ALL ON public.draft_deletion_receipts FROM PUBLIC,anon,authenticated,service_role;

CREATE FUNCTION public.delete_unconfirmed_medication(p_kind text,p_id uuid,p_confirmed boolean)
 RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE o uuid:=auth.uid(); m uuid; plans uuid[]; tasks uuid[]; srcs uuid[]; removable uuid[];
 whole boolean; paths text[]; receipt public.draft_deletion_receipts%ROWTYPE;
BEGIN
 IF o IS NULL OR p_confirmed IS DISTINCT FROM true OR p_kind NOT IN ('draft','source') THEN
  RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='Authenticated explicit confirmation required'; END IF;
 -- Same lock as migration025 activation guard: independent requests serialize.
 PERFORM 1 FROM public.patient_profiles WHERE user_id=o FOR UPDATE;
 SELECT * INTO receipt FROM public.draft_deletion_receipts WHERE patient_id=o AND kind=p_kind AND target_id=p_id;
 IF FOUND THEN RETURN jsonb_build_object('deleted',true,'medication_deleted',receipt.medication_deleted,'storage_paths',receipt.storage_paths); END IF;
 IF p_kind='draft' THEN
  SELECT patient_medication_id INTO m FROM public.regimen_versions WHERE patient_id=o AND id=p_id FOR UPDATE;
 ELSE
  SELECT medication_id INTO m FROM public.medication_evidence_tasks WHERE patient_id=o AND id=p_id FOR UPDATE;
 END IF;
 IF m IS NULL THEN RAISE EXCEPTION USING ERRCODE='P7504',MESSAGE='Draft not found'; END IF;
 PERFORM 1 FROM public.patient_medications WHERE patient_id=o AND id=m FOR UPDATE;
 PERFORM 1 FROM public.regimen_versions WHERE patient_id=o AND patient_medication_id=m FOR UPDATE;
 IF p_kind='draft' AND EXISTS(SELECT 1 FROM public.regimen_versions WHERE patient_id=o AND id=p_id AND state NOT IN ('draft','pending_clarification')) THEN
  RAISE EXCEPTION USING ERRCODE='P7502',MESSAGE='Confirmed plans cannot be deleted'; END IF;
 IF p_kind='source' AND EXISTS(SELECT 1 FROM public.medication_evidence_tasks t JOIN public.regimen_versions r
  ON r.patient_id=t.patient_id AND r.id=nullif(t.data->>'draft_regimen_id','')::uuid
  WHERE t.patient_id=o AND t.id=p_id AND r.state NOT IN ('draft','pending_clarification')) THEN
  RAISE EXCEPTION USING ERRCODE='P7502',MESSAGE='Confirmed source task cannot be deleted'; END IF;
 whole:=NOT EXISTS(SELECT 1 FROM public.regimen_versions WHERE patient_id=o AND patient_medication_id=m AND state IN ('active','ended','superseded'));
 SELECT coalesce(array_agg(id),'{}') INTO plans FROM public.regimen_versions
 WHERE patient_id=o AND patient_medication_id=m AND (whole OR (p_kind='draft' AND id=p_id)
  OR (p_kind='source' AND id=(SELECT nullif(data->>'draft_regimen_id','')::uuid FROM public.medication_evidence_tasks WHERE patient_id=o AND id=p_id)));
 SELECT coalesce(array_agg(id),'{}') INTO tasks FROM public.medication_evidence_tasks
 WHERE patient_id=o AND medication_id=m AND (whole OR (p_kind='source' AND id=p_id) OR nullif(data->>'draft_regimen_id','')::uuid=ANY(plans));
 IF EXISTS(SELECT 1 FROM public.audit_events WHERE patient_id=o AND regimen_id=ANY(plans))
 OR EXISTS(SELECT 1 FROM public.dose_events WHERE patient_id=o AND regimen_id=ANY(plans))
 OR EXISTS(SELECT 1 FROM public.dose_occurrences WHERE patient_id=o AND regimen_id=ANY(plans))
 OR EXISTS(SELECT 1 FROM public.dose_rules WHERE patient_id=o AND regimen_id=ANY(plans))
 OR EXISTS(SELECT 1 FROM public.confirmation_challenges WHERE patient_id=o AND regimen_id=ANY(plans) AND (confirmed_at IS NOT NULL OR consumed_at IS NOT NULL))
 OR EXISTS(SELECT 1 FROM public.recognition_runs WHERE patient_id=o AND (selected_regimen_id=ANY(plans) OR (whole AND EXISTS(SELECT 1 FROM public.visual_reference_sets v WHERE v.patient_id=o AND v.medication_id=m AND recognition_runs.data->'reference_ids' ? v.id::text)))) THEN
  RAISE EXCEPTION USING ERRCODE='P7502',MESSAGE='Draft has protected history'; END IF;
 SELECT coalesce(array_agg(DISTINCT x),'{}') INTO srcs FROM (
  SELECT source_id x FROM public.regimen_versions WHERE patient_id=o AND id=ANY(plans)
  UNION SELECT source_id FROM public.medication_source_links WHERE patient_id=o AND medication_id=m AND whole
  UNION SELECT source_id FROM public.patient_medications WHERE patient_id=o AND id=m AND whole
  UNION SELECT jsonb_array_elements_text(data->'source_ids')::uuid FROM public.medication_evidence_tasks WHERE patient_id=o AND id=ANY(tasks)
 ) q WHERE x IS NOT NULL;
 SELECT coalesce(array_agg(s),'{}') INTO removable FROM unnest(srcs) s WHERE
  NOT EXISTS(SELECT 1 FROM public.regimen_versions WHERE patient_id=o AND source_id=s AND NOT(id=ANY(plans)))
  AND NOT EXISTS(SELECT 1 FROM public.patient_medications WHERE patient_id=o AND source_id=s AND (id<>m OR NOT whole))
  AND NOT EXISTS(SELECT 1 FROM public.medication_source_links WHERE patient_id=o AND source_id=s AND medication_id<>m)
  AND NOT EXISTS(SELECT 1 FROM public.medication_evidence_tasks WHERE patient_id=o AND NOT(id=ANY(tasks)) AND data->'source_ids' ? s::text);
 SELECT coalesce(array_agg(DISTINCT data->>'storage_path'),'{}') INTO paths FROM public.medication_images i
 WHERE patient_id=o AND medication_id=m AND (whole OR source_id=ANY(removable))
 AND NOT EXISTS(SELECT 1 FROM public.medication_images other WHERE other.data->>'storage_path'=i.data->>'storage_path' AND other.id<>i.id AND other.medication_id<>m);
 IF cardinality(paths)>1000 OR EXISTS(SELECT 1 FROM unnest(paths) p WHERE p NOT LIKE o::text||'/%' OR p LIKE '%..%') THEN
  RAISE EXCEPTION USING ERRCODE='P7502',MESSAGE='Private image cleanup scope invalid'; END IF;
 -- Unknown/shared FK dependencies abort the entire transaction; never cascade.
 DELETE FROM public.image_embeddings WHERE patient_id=o AND medication_id=m AND whole;
 DELETE FROM public.visual_reference_sets WHERE patient_id=o AND medication_id=m AND whole;
 DELETE FROM public.medication_images WHERE patient_id=o AND medication_id=m AND (whole OR source_id=ANY(removable));
 DELETE FROM public.medication_source_links WHERE patient_id=o AND medication_id=m AND source_id=ANY(removable);
 DELETE FROM public.medication_evidence_tasks WHERE patient_id=o AND id=ANY(tasks);
 DELETE FROM public.confirmation_challenges WHERE patient_id=o AND regimen_id=ANY(plans);
 DELETE FROM public.regimen_versions WHERE patient_id=o AND id=ANY(plans);
 IF whole THEN DELETE FROM public.patient_medications WHERE patient_id=o AND id=m; END IF;
 DELETE FROM public.source_fields WHERE patient_id=o AND source_id=ANY(removable);
 DELETE FROM public.source_documents WHERE patient_id=o AND id=ANY(removable);
 INSERT INTO public.draft_deletion_receipts(patient_id,kind,target_id,medication_deleted,storage_paths) VALUES(o,p_kind,p_id,whole,paths);
 RETURN jsonb_build_object('deleted',true,'medication_deleted',whole,'storage_paths',paths);
END $$;
CREATE FUNCTION public.ack_draft_image_cleanup(p_kind text,p_id uuid,p_path text) RETURNS void
 LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
 UPDATE public.draft_deletion_receipts SET storage_paths=array_remove(storage_paths,p_path)
 WHERE patient_id=auth.uid() AND kind=p_kind AND target_id=p_id;
$$;
REVOKE ALL ON FUNCTION public.delete_unconfirmed_medication(text,uuid,boolean),public.ack_draft_image_cleanup(text,uuid,text) FROM PUBLIC,anon,service_role;
GRANT EXECUTE ON FUNCTION public.delete_unconfirmed_medication(text,uuid,boolean),public.ack_draft_image_cleanup(text,uuid,text) TO authenticated;
NOTIFY pgrst,'reload schema';
COMMIT;
