-- Additive durable threads. Never backfill or rewrite legacy messages.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';

CREATE TABLE public.conversations (
 id uuid PRIMARY KEY,
 patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id),
 title text NOT NULL CHECK(length(title) BETWEEN 1 AND 120),
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 has_messages boolean NOT NULL DEFAULT false,
 demo_only boolean NOT NULL DEFAULT true CHECK(demo_only),
 UNIQUE(patient_id,id)
);
CREATE INDEX conversations_owner_activity ON public.conversations(patient_id,updated_at DESC,id DESC);
ALTER TABLE public.conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversations FORCE ROW LEVEL SECURITY;
CREATE POLICY conversations_owner_read ON public.conversations FOR SELECT TO authenticated USING(patient_id=auth.uid());
REVOKE ALL ON public.conversations FROM PUBLIC,anon,authenticated;
GRANT SELECT ON public.conversations TO authenticated;

ALTER TABLE public.agent_sessions ADD COLUMN conversation_id uuid;
ALTER TABLE public.agent_sessions ADD CONSTRAINT agent_session_conversation_owner
 FOREIGN KEY(patient_id,conversation_id) REFERENCES public.conversations(patient_id,id) ON DELETE SET NULL(conversation_id);
ALTER TABLE public.conversation_turns ADD COLUMN conversation_id uuid;
ALTER TABLE public.conversation_turns ADD COLUMN photo_attached boolean NOT NULL DEFAULT false;
ALTER TABLE public.conversation_turns ADD COLUMN full_assistant_text text CHECK(length(full_assistant_text)<=32000);
ALTER TABLE public.conversation_turns ADD CONSTRAINT thread_full_message CHECK(conversation_id IS NULL OR full_assistant_text IS NOT NULL);
ALTER TABLE public.conversation_turns ADD CONSTRAINT conversation_turn_thread_owner
 FOREIGN KEY(patient_id,conversation_id) REFERENCES public.conversations(patient_id,id) ON DELETE CASCADE;
CREATE INDEX conversation_turn_thread_time ON public.conversation_turns(patient_id,conversation_id,created_at DESC,id DESC);
-- Legacy thirty-day policy remains unchanged. New threads retain owned text independently of model bounds.
CREATE POLICY thread_turns_owner_read ON public.conversation_turns FOR SELECT TO authenticated
 USING(patient_id=auth.uid() AND conversation_id IS NOT NULL);

CREATE TABLE public.conversation_requests (
 id uuid PRIMARY KEY,
 patient_id uuid NOT NULL,
 conversation_id uuid NOT NULL,
 digest text NOT NULL CHECK(digest ~ '^[0-9a-f]{64}$'),
 state text NOT NULL DEFAULT 'processing' CHECK(state IN ('processing','completed','failed')),
 created_at timestamptz NOT NULL DEFAULT now(),
 demo_only boolean NOT NULL DEFAULT true CHECK(demo_only),
 FOREIGN KEY(patient_id,conversation_id) REFERENCES public.conversations(patient_id,id) ON DELETE CASCADE,
 UNIQUE(patient_id,id,conversation_id)
);
CREATE INDEX conversation_requests_owner_thread ON public.conversation_requests(patient_id,conversation_id);
ALTER TABLE public.conversation_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversation_requests FORCE ROW LEVEL SECURITY;
CREATE POLICY conversation_requests_owner_read ON public.conversation_requests FOR SELECT TO authenticated USING(patient_id=auth.uid());
REVOKE ALL ON public.conversation_requests FROM PUBLIC,anon,authenticated;
GRANT SELECT ON public.conversation_requests TO authenticated;
ALTER TABLE public.conversation_turns ADD CONSTRAINT thread_message_request
 FOREIGN KEY(patient_id,id,conversation_id) REFERENCES public.conversation_requests(patient_id,id,conversation_id);

CREATE FUNCTION public.create_conversation(p_id uuid,p_title text) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE owner_id uuid:=auth.uid();
BEGIN
 IF owner_id IS NULL THEN RAISE EXCEPTION 'owner required'; END IF;
 PERFORM 1 FROM public.patient_profiles WHERE user_id=owner_id AND conversation_history_enabled FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'history consent required'; END IF;
 INSERT INTO public.conversations(id,patient_id,title) VALUES(p_id,owner_id,p_title);
END $$;

CREATE FUNCTION public.claim_conversation_turn(p_conversation uuid,p_id uuid,p_digest text) RETURNS text
 LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE owner_id uuid:=auth.uid(); previous public.conversation_requests%ROWTYPE;
BEGIN
 IF owner_id IS NULL THEN RAISE EXCEPTION 'owner required'; END IF;
 PERFORM 1 FROM public.patient_profiles WHERE user_id=owner_id AND conversation_history_enabled FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'history consent required'; END IF;
 PERFORM 1 FROM public.conversations WHERE patient_id=owner_id AND id=p_conversation FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'owned conversation required'; END IF;
 SELECT * INTO previous FROM public.conversation_requests WHERE id=p_id;
 IF FOUND THEN
  IF previous.patient_id<>owner_id OR previous.conversation_id<>p_conversation OR previous.digest<>p_digest THEN RAISE EXCEPTION 'message retry conflict'; END IF;
  RETURN CASE WHEN previous.state='completed' THEN 'completed' ELSE 'busy' END;
 END IF;
 INSERT INTO public.conversation_requests(id,patient_id,conversation_id,digest) VALUES(p_id,owner_id,p_conversation,p_digest);
 RETURN 'new';
END $$;

CREATE FUNCTION public.append_thread_turn(p_turn jsonb) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE owner_id uuid:=auth.uid(); request_row public.conversation_requests%ROWTYPE;
BEGIN
 IF owner_id IS NULL THEN RAISE EXCEPTION 'owner required'; END IF;
 PERFORM 1 FROM public.patient_profiles WHERE user_id=owner_id AND conversation_history_enabled FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'history consent required'; END IF;
 SELECT * INTO request_row FROM public.conversation_requests WHERE patient_id=owner_id AND id=(p_turn->>'id')::uuid FOR UPDATE;
 IF NOT FOUND OR request_row.conversation_id<>(p_turn->>'conversation_id')::uuid THEN RAISE EXCEPTION 'owned claim required'; END IF;
 IF request_row.state='completed' THEN RETURN; END IF;
 IF request_row.state<>'processing' THEN RAISE EXCEPTION 'request not processing'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.agent_sessions WHERE patient_id=owner_id AND id=(p_turn->>'session_id')::uuid AND conversation_id=request_row.conversation_id) THEN RAISE EXCEPTION 'bound session required'; END IF;
 INSERT INTO public.conversation_turns(id,patient_id,session_id,conversation_id,user_text,assistant_text,full_assistant_text,photo_attached)
 VALUES(request_row.id,owner_id,(p_turn->>'session_id')::uuid,request_row.conversation_id,p_turn->>'user_text',left(p_turn->>'assistant_text',4000),p_turn->>'assistant_text',COALESCE((p_turn->>'photo_attached')::boolean,false));
 UPDATE public.conversation_requests SET state='completed' WHERE id=request_row.id;
 UPDATE public.conversations SET has_messages=true,updated_at=now() WHERE patient_id=owner_id AND id=request_row.conversation_id;
END $$;

CREATE FUNCTION public.fail_conversation_turn(p_id uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF auth.uid() IS NULL THEN RAISE EXCEPTION 'owner required'; END IF;
 UPDATE public.conversation_requests SET state='failed' WHERE patient_id=auth.uid() AND id=p_id AND state='processing';
END $$;

-- Preserve the old API, but its old retention must never delete thread messages.
CREATE OR REPLACE FUNCTION public.append_conversation_turn(p_turn jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE owner_id uuid:=auth.uid(); previous public.conversation_turns%ROWTYPE;
BEGIN
 IF owner_id IS NULL OR (p_turn->>'patient_id')::uuid IS DISTINCT FROM owner_id THEN RAISE EXCEPTION 'owner required'; END IF;
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
 DELETE FROM public.conversation_turns WHERE patient_id=owner_id AND conversation_id IS NULL AND (created_at<now()-interval '30 days' OR id IN (
   SELECT id FROM public.conversation_turns WHERE patient_id=owner_id AND conversation_id IS NULL ORDER BY created_at DESC,id DESC OFFSET 200));
 UPDATE public.agent_sessions SET context=jsonb_set(jsonb_set(context,'{recent_turns}','[]'::jsonb),'{conversation_summary}','""'::jsonb) WHERE patient_id=owner_id AND expires_at<now();
END $$;

CREATE OR REPLACE FUNCTION public.clear_conversation_history() RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE owner_id uuid:=auth.uid();
BEGIN
 IF owner_id IS NULL THEN RAISE EXCEPTION 'owner required'; END IF;
 PERFORM 1 FROM public.patient_profiles WHERE user_id=owner_id FOR UPDATE;
 DELETE FROM public.conversation_turns WHERE patient_id=owner_id;
 DELETE FROM public.conversations WHERE patient_id=owner_id;
 UPDATE public.agent_sessions SET context=jsonb_set(jsonb_set(context,'{recent_turns}','[]'::jsonb),'{conversation_summary}','""'::jsonb) WHERE patient_id=owner_id;
END $$;

REVOKE ALL ON FUNCTION public.create_conversation(uuid,text),public.claim_conversation_turn(uuid,uuid,text),public.append_thread_turn(jsonb),public.fail_conversation_turn(uuid) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.create_conversation(uuid,text),public.claim_conversation_turn(uuid,uuid,text),public.append_thread_turn(jsonb),public.fail_conversation_turn(uuid) TO authenticated;
COMMIT;
