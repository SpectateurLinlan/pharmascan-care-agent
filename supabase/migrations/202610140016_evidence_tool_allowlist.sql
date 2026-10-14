-- Add the read-only typed evidence tool; clinical write guards unchanged.
ALTER TABLE public.agent_tool_calls DROP CONSTRAINT agent_tool_calls_tool_name_check;
ALTER TABLE public.agent_tool_calls ADD CONSTRAINT agent_tool_calls_tool_name_check CHECK(tool_name IN
 ('list_active_medications','get_medication_history','get_dose_status','enroll_medication_draft',
 'confirm_regimen_draft','check_due_dose','record_self_report','create_reminder','reconcile_medication_sources'));
NOTIFY pgrst, 'reload schema';

-- Atomic eligible-reference commit: object upload is immutable and precedes
-- this transaction. A failed transaction leaves no eligible DB reference.
CREATE FUNCTION public.store_personal_reference(p_image jsonb,p_set jsonb,p_embedding jsonb)
RETURNS void LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,public AS $$
DECLARE owner_id uuid := (SELECT auth.uid());
BEGIN
 IF owner_id IS NULL OR p_image->>'patient_id' <> owner_id::text
  OR p_set->>'patient_id' <> owner_id::text OR p_embedding->>'patient_id' <> owner_id::text
  OR p_image->>'medication_id' <> p_set->>'medication_id'
  OR p_image->>'medication_id' <> p_embedding->>'medication_id'
  OR p_embedding->>'image_id' <> p_image->>'id'
  OR p_embedding->>'reference_set_id' <> p_set->>'id'
  OR p_image->>'image_kind' <> 'loose_pill' OR p_image->>'eligibility' <> 'eligible'
  OR p_image->>'reviewed' <> 'true' THEN
  RAISE EXCEPTION 'Invalid owned reference association';
 END IF;
 IF NOT EXISTS (SELECT 1 FROM public.patient_medications WHERE patient_id=owner_id
   AND id=(p_image->>'medication_id')::uuid AND identity_status='user_reviewed_document') THEN
  RAISE EXCEPTION 'Patient-reviewed product source required';
 END IF;
 INSERT INTO public.visual_reference_sets(id,patient_id,medication_id,data)
 VALUES ((p_set->>'id')::uuid,owner_id,(p_set->>'medication_id')::uuid,p_set)
 ON CONFLICT(patient_id,id) DO NOTHING;
 INSERT INTO public.medication_images(id,patient_id,medication_id,data)
 VALUES ((p_image->>'id')::uuid,owner_id,(p_image->>'medication_id')::uuid,p_image)
 ON CONFLICT(patient_id,id) DO NOTHING;
 INSERT INTO public.image_embeddings(id,patient_id,medication_id,image_id,reference_set_id,data)
 VALUES ((p_embedding->>'id')::uuid,owner_id,(p_embedding->>'medication_id')::uuid,
 (p_embedding->>'image_id')::uuid,(p_embedding->>'reference_set_id')::uuid,p_embedding)
 ON CONFLICT(patient_id,id) DO NOTHING;
END; $$;
REVOKE ALL ON FUNCTION public.store_personal_reference(jsonb,jsonb,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.store_personal_reference(jsonb,jsonb,jsonb) TO authenticated;
NOTIFY pgrst,'reload schema';
