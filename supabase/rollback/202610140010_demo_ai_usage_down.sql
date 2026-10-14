-- Disposable database only. Never erase usage/history in shared DB for QA.
BEGIN;
DROP FUNCTION public.get_demo_ai_usage(),public.reserve_demo_ai_turn(text,text),public.record_demo_ai_request(date,text,text),public.finish_demo_ai_turn(date,text,text,boolean);
DROP FUNCTION pharmascan_private.demo_ai_snapshot(uuid,date);
DROP TABLE public.demo_ai_turns,public.demo_ai_usage,pharmascan_private.demo_ai_config;
COMMIT;
