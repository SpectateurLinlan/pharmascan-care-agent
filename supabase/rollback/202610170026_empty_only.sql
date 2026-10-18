-- MANUAL PRE-DEPLOYMENT ONLY. Refuses any durable or linked session data.
-- Never execute after the feature has accepted messages; use a forward fix instead.
BEGIN;
SET LOCAL lock_timeout='5s';
LOCK TABLE public.conversations,public.conversation_requests,public.conversation_turns,public.agent_sessions IN ACCESS EXCLUSIVE MODE;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.conversations) OR EXISTS(SELECT 1 FROM public.conversation_requests)
 OR EXISTS(SELECT 1 FROM public.conversation_turns WHERE conversation_id IS NOT NULL)
 OR EXISTS(SELECT 1 FROM public.agent_sessions WHERE conversation_id IS NOT NULL)
 THEN RAISE EXCEPTION 'Rollback refused: durable conversation data exists'; END IF;
END $$;
DROP FUNCTION public.create_conversation(uuid,text),public.claim_conversation_turn(uuid,uuid,text),public.append_thread_turn(jsonb),public.fail_conversation_turn(uuid);
ALTER TABLE public.conversation_turns DROP CONSTRAINT thread_message_request;
ALTER TABLE public.conversation_turns DROP CONSTRAINT conversation_turn_thread_owner;
ALTER TABLE public.conversation_turns DROP CONSTRAINT thread_full_message;
DROP POLICY thread_turns_owner_read ON public.conversation_turns;
ALTER TABLE public.conversation_turns DROP COLUMN conversation_id,DROP COLUMN photo_attached,DROP COLUMN full_assistant_text;
ALTER TABLE public.agent_sessions DROP CONSTRAINT agent_session_conversation_owner;
ALTER TABLE public.agent_sessions DROP COLUMN conversation_id;
DROP TABLE public.conversation_requests;
DROP TABLE public.conversations;
CREATE OR REPLACE FUNCTION public.append_conversation_turn(p_turn jsonb)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
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
END $function$;

CREATE OR REPLACE FUNCTION public.clear_conversation_history()
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
DECLARE owner_id uuid:=auth.uid();
BEGIN
 IF owner_id IS NULL THEN RAISE EXCEPTION 'owner required'; END IF;
 PERFORM 1 FROM public.patient_profiles WHERE user_id=owner_id FOR UPDATE;
 DELETE FROM public.conversation_turns WHERE patient_id=owner_id;
 -- Keep task IDs and challenge/session states; clear only retained message text.
 UPDATE public.agent_sessions SET context=jsonb_set(jsonb_set(context,'{recent_turns}','[]'::jsonb),'{conversation_summary}','""'::jsonb) WHERE patient_id=owner_id;
END $function$;

-- If applied via the schema ledger, remove ONLY version 202610170026 in this transaction.
COMMIT;
