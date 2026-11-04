-- REVIEW ONLY / NOT APPLIED. Preserve every existing session/history/task row.
-- Keep the compatible native clear owner-fence/FK detachment while035 tables
-- remain. Reverting it would strand retained tasks/threads, not recover data.
-- Reverting that compatibility definition needs separate target-specific review.
BEGIN;
SET LOCAL lock_timeout='5s';
DROP FUNCTION public.assistant_notification_transition(jsonb);
DROP POLICY assistant_message_subscriptions ON public.push_subscriptions;
REVOKE ALL ON public.push_subscriptions FROM assistant_message_owner;
DROP FUNCTION public.assistant_conversation_transition(jsonb);
DROP FUNCTION public.assistant_message_command(jsonb);
DROP POLICY assistant_message_profile ON public.patient_profiles;
DROP POLICY assistant_message_sessions ON public.agent_sessions;
DROP POLICY assistant_message_threads ON public.conversations;
DROP POLICY assistant_message_turns ON public.conversation_turns;
DROP POLICY assistant_message_traces ON public.agent_tool_calls;
DROP POLICY assistant_message_tasks ON public.assistant_workflow_tasks;
DROP POLICY assistant_message_controls ON public.assistant_workflow_operations;
REVOKE ALL ON public.agent_sessions,public.conversations,public.conversation_turns,public.agent_tool_calls,
 public.assistant_workflow_tasks,public.assistant_workflow_operations FROM assistant_message_owner;
REVOKE SELECT(user_id,conversation_history_enabled) ON public.patient_profiles FROM assistant_message_owner;
REVOKE EXECUTE ON FUNCTION public.create_conversation(uuid,text),public.claim_conversation_turn(uuid,uuid,text),
 public.append_thread_turn(jsonb),public.fail_conversation_turn(uuid),public.append_conversation_turn(jsonb),
 public.clear_conversation_history() FROM assistant_message_owner;
COMMIT;
