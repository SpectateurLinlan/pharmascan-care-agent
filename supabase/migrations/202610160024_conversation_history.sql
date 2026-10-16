-- Optional message history, separate from six-turn agent context and clinical records.
ALTER TABLE public.source_documents ADD COLUMN dose_basis jsonb CHECK(dose_basis IS NULL OR (jsonb_typeof(dose_basis)='object' AND octet_length(dose_basis::text)<=4096));
CREATE FUNCTION public.guard_reviewed_dose_basis() RETURNS trigger LANGUAGE plpgsql SET search_path='' AS $$
BEGIN
 IF OLD.review_status IN ('user_reviewed','professional_verified') AND NEW.dose_basis IS DISTINCT FROM OLD.dose_basis THEN RAISE EXCEPTION 'reviewed source details are immutable'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER source_dose_basis_immutable BEFORE UPDATE ON public.source_documents FOR EACH ROW EXECUTE FUNCTION public.guard_reviewed_dose_basis();
ALTER TABLE public.patient_profiles ADD COLUMN conversation_history_enabled boolean NOT NULL DEFAULT false;
CREATE TABLE public.conversation_turns (
 id uuid PRIMARY KEY,
 patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id),
 session_id uuid NOT NULL,
 user_text text NOT NULL CHECK(length(user_text)<=2000),
 assistant_text text NOT NULL CHECK(length(assistant_text)<=4000),
 created_at timestamptz NOT NULL DEFAULT now(),
 demo_only boolean NOT NULL DEFAULT true CHECK(demo_only),
 FOREIGN KEY(patient_id,session_id) REFERENCES public.agent_sessions(patient_id,id)
);
CREATE INDEX conversation_turns_owner_time ON public.conversation_turns(patient_id,created_at DESC,id DESC);
ALTER TABLE public.conversation_turns ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversation_turns FORCE ROW LEVEL SECURITY;
CREATE POLICY conversation_turns_read ON public.conversation_turns FOR SELECT TO authenticated
 USING(patient_id=auth.uid() AND created_at>=now()-interval '30 days');
CREATE POLICY conversation_turns_delete ON public.conversation_turns FOR DELETE TO authenticated USING(patient_id=auth.uid());
GRANT SELECT,DELETE ON public.conversation_turns TO authenticated;
CREATE FUNCTION public.append_conversation_turn(p_turn jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE owner_id uuid:=auth.uid(); previous public.conversation_turns%ROWTYPE;
BEGIN
 IF owner_id IS NULL OR (p_turn->>'patient_id')::uuid IS DISTINCT FROM owner_id THEN RAISE EXCEPTION 'owner required'; END IF;
 -- Owner lock serializes duplicate retries and the200-turn retention boundary.
 PERFORM 1 FROM public.patient_profiles WHERE user_id=owner_id AND conversation_history_enabled FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'history consent required'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.agent_sessions WHERE patient_id=owner_id AND id=(p_turn->>'session_id')::uuid) THEN RAISE EXCEPTION 'owned session required'; END IF;
 SELECT * INTO previous FROM public.conversation_turns WHERE id=(p_turn->>'id')::uuid;
 IF FOUND THEN
   IF previous.patient_id<>owner_id OR previous.session_id<>(p_turn->>'session_id')::uuid OR previous.user_text IS DISTINCT FROM p_turn->>'user_text' OR previous.assistant_text IS DISTINCT FROM p_turn->>'assistant_text' THEN RAISE EXCEPTION 'turn retry conflict'; END IF;
   RETURN;
 END IF;
 INSERT INTO public.conversation_turns(id,patient_id,session_id,user_text,assistant_text)
 VALUES((p_turn->>'id')::uuid,owner_id,(p_turn->>'session_id')::uuid,p_turn->>'user_text',p_turn->>'assistant_text');
 DELETE FROM public.conversation_turns WHERE patient_id=owner_id AND (created_at<now()-interval '30 days' OR id IN (
   SELECT id FROM public.conversation_turns WHERE patient_id=owner_id ORDER BY created_at DESC,id DESC OFFSET 200));
 UPDATE public.agent_sessions SET context=jsonb_set(jsonb_set(context,'{recent_turns}','[]'::jsonb),'{conversation_summary}','""'::jsonb) WHERE patient_id=owner_id AND expires_at<now();
END $$;
REVOKE ALL ON FUNCTION public.append_conversation_turn(jsonb) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.append_conversation_turn(jsonb) TO authenticated;
CREATE FUNCTION public.clear_conversation_history() RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE owner_id uuid:=auth.uid();
BEGIN
 IF owner_id IS NULL THEN RAISE EXCEPTION 'owner required'; END IF;
 PERFORM 1 FROM public.patient_profiles WHERE user_id=owner_id FOR UPDATE;
 DELETE FROM public.conversation_turns WHERE patient_id=owner_id;
 -- Keep task IDs and challenge/session states; clear only retained message text.
 UPDATE public.agent_sessions SET context=jsonb_set(jsonb_set(context,'{recent_turns}','[]'::jsonb),'{conversation_summary}','""'::jsonb) WHERE patient_id=owner_id;
END $$;
REVOKE ALL ON FUNCTION public.clear_conversation_history() FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.clear_conversation_history() TO authenticated;
