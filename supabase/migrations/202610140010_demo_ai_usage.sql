-- Narrow owner-bound accounting RPCs; patients cannot edit counters directly.
BEGIN;
CREATE TABLE pharmascan_private.demo_ai_config (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 daily_turn_limit integer NOT NULL DEFAULT 20 CHECK(daily_turn_limit BETWEEN 1 AND 100)
);
INSERT INTO pharmascan_private.demo_ai_config VALUES(true,20);
REVOKE ALL ON pharmascan_private.demo_ai_config FROM PUBLIC,anon,authenticated;
CREATE TABLE public.demo_ai_usage (
 patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id) ON DELETE RESTRICT,
 usage_date date NOT NULL,llm_user_turns integer NOT NULL DEFAULT 0 CHECK(llm_user_turns>=0),
 model_requests integer NOT NULL DEFAULT 0 CHECK(model_requests>=0),updated_at timestamptz NOT NULL DEFAULT now(),
 demo_only boolean NOT NULL DEFAULT true CHECK(demo_only),PRIMARY KEY(patient_id,usage_date)
);
CREATE TABLE public.demo_ai_turns (
 patient_id uuid NOT NULL,usage_date date NOT NULL,turn_key text NOT NULL CHECK(length(turn_key) BETWEEN 1 AND 128),
 nonce_hash text NOT NULL CHECK(nonce_hash ~ '^[a-f0-9]{64}$'),
 status text NOT NULL CHECK(status IN ('pending','succeeded','failed')),
 updated_at timestamptz NOT NULL DEFAULT now(),demo_only boolean NOT NULL DEFAULT true CHECK(demo_only),
 PRIMARY KEY(patient_id,usage_date,turn_key),
 FOREIGN KEY(patient_id,usage_date) REFERENCES public.demo_ai_usage(patient_id,usage_date) ON DELETE RESTRICT
);
ALTER TABLE public.demo_ai_usage ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.demo_ai_usage FORCE ROW LEVEL SECURITY;
ALTER TABLE public.demo_ai_turns ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.demo_ai_turns FORCE ROW LEVEL SECURITY;
CREATE POLICY demo_ai_usage_owner ON public.demo_ai_usage FOR SELECT TO authenticated USING(patient_id=auth.uid());
CREATE POLICY demo_ai_turns_owner ON public.demo_ai_turns FOR SELECT TO authenticated USING(patient_id=auth.uid());
REVOKE ALL ON public.demo_ai_usage,public.demo_ai_turns FROM PUBLIC,anon,authenticated;
GRANT SELECT ON public.demo_ai_usage,public.demo_ai_turns TO authenticated;
CREATE FUNCTION pharmascan_private.demo_ai_snapshot(p_user uuid,p_day date) RETURNS jsonb
LANGUAGE sql STABLE SECURITY INVOKER SET search_path=pg_catalog AS $$
 SELECT jsonb_build_object('patient_id',p_user,'usage_date',p_day,
  'llm_user_turns',coalesce(u.llm_user_turns,0),'model_requests',coalesce(u.model_requests,0),
  'limit',c.daily_turn_limit,'next_reset_at',((p_day+1)::timestamp AT TIME ZONE 'Asia/Singapore'))
 FROM pharmascan_private.demo_ai_config c LEFT JOIN public.demo_ai_usage u ON u.patient_id=p_user AND u.usage_date=p_day;
$$;
REVOKE ALL ON FUNCTION pharmascan_private.demo_ai_snapshot(uuid,date) FROM PUBLIC,anon,authenticated;
CREATE FUNCTION public.get_demo_ai_usage() RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF auth.uid() IS NULL THEN RAISE EXCEPTION 'Authenticated owner required';END IF;
 RETURN pharmascan_private.demo_ai_snapshot(auth.uid(),(now() AT TIME ZONE 'Asia/Singapore')::date);
END $$;
CREATE FUNCTION public.reserve_demo_ai_turn(p_turn_key text,p_nonce text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE u uuid:=auth.uid();d date:=(now() AT TIME ZONE 'Asia/Singapore')::date;
 n integer;l integer;used integer;old_status text;
BEGIN
 IF u IS NULL OR length(p_turn_key) NOT BETWEEN 1 AND 128 OR p_nonce !~ '^[a-f0-9]{64}$' THEN RAISE EXCEPTION 'Invalid reservation';END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('demo-ai:'||u::text||d::text,0));
 INSERT INTO public.demo_ai_usage(patient_id,usage_date) VALUES(u,d) ON CONFLICT DO NOTHING;
 UPDATE public.demo_ai_turns SET status='failed',updated_at=now() WHERE patient_id=u AND usage_date=d AND status='pending' AND updated_at<now()-interval '10 minutes';
 SELECT status INTO old_status FROM public.demo_ai_turns WHERE patient_id=u AND usage_date=d AND turn_key=p_turn_key;
 IF old_status IN ('pending','succeeded') THEN
  RETURN jsonb_build_object('reservation',CASE old_status WHEN 'pending' THEN 'pending' ELSE 'completed' END,'usage',pharmascan_private.demo_ai_snapshot(u,d));
 END IF;
 SELECT llm_user_turns INTO used FROM public.demo_ai_usage WHERE patient_id=u AND usage_date=d;
 SELECT daily_turn_limit INTO l FROM pharmascan_private.demo_ai_config;
 SELECT count(*) INTO n FROM public.demo_ai_turns WHERE patient_id=u AND usage_date=d AND status='pending';
 IF used+n>=l THEN RETURN jsonb_build_object('reservation',CASE WHEN used>=l THEN 'exhausted' ELSE 'busy' END,'usage',pharmascan_private.demo_ai_snapshot(u,d));END IF;
 INSERT INTO public.demo_ai_turns(patient_id,usage_date,turn_key,nonce_hash,status)
 VALUES(u,d,p_turn_key,encode(sha256(convert_to(p_nonce,'UTF8')),'hex'),'pending')
 ON CONFLICT(patient_id,usage_date,turn_key) DO UPDATE SET nonce_hash=EXCLUDED.nonce_hash,status='pending',updated_at=now();
 RETURN jsonb_build_object('reservation','reserved','usage',pharmascan_private.demo_ai_snapshot(u,d));
END $$;
CREATE FUNCTION public.record_demo_ai_request(p_day date,p_turn_key text,p_nonce text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF auth.uid() IS NULL THEN RAISE EXCEPTION 'Authenticated owner required';END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('demo-ai:'||auth.uid()::text||p_day::text,0));
 UPDATE public.demo_ai_turns SET updated_at=now() WHERE patient_id=auth.uid() AND usage_date=p_day AND turn_key=p_turn_key AND status='pending' AND nonce_hash=encode(sha256(convert_to(p_nonce,'UTF8')),'hex');
 IF NOT FOUND THEN RAISE EXCEPTION 'Invalid reservation capability';END IF;
 UPDATE public.demo_ai_usage SET model_requests=model_requests+1,updated_at=now() WHERE patient_id=auth.uid() AND usage_date=p_day;
END $$;
CREATE FUNCTION public.finish_demo_ai_turn(p_day date,p_turn_key text,p_nonce text,p_success boolean) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF auth.uid() IS NULL THEN RAISE EXCEPTION 'Authenticated owner required';END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('demo-ai:'||auth.uid()::text||p_day::text,0));
 UPDATE public.demo_ai_turns SET status=CASE WHEN p_success THEN 'succeeded' ELSE 'failed' END,updated_at=now()
 WHERE patient_id=auth.uid() AND usage_date=p_day AND turn_key=p_turn_key AND status='pending'
 AND nonce_hash=encode(sha256(convert_to(p_nonce,'UTF8')),'hex');
 IF NOT FOUND THEN RAISE EXCEPTION 'Invalid or finished reservation';END IF;
 IF p_success THEN UPDATE public.demo_ai_usage SET llm_user_turns=llm_user_turns+1,updated_at=now() WHERE patient_id=auth.uid() AND usage_date=p_day;END IF;
 RETURN pharmascan_private.demo_ai_snapshot(auth.uid(),(now() AT TIME ZONE 'Asia/Singapore')::date);
END $$;
REVOKE ALL ON FUNCTION public.get_demo_ai_usage(),public.reserve_demo_ai_turn(text,text),public.record_demo_ai_request(date,text,text),public.finish_demo_ai_turn(date,text,text,boolean) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.get_demo_ai_usage(),public.reserve_demo_ai_turn(text,text),public.record_demo_ai_request(date,text,text),public.finish_demo_ai_turn(date,text,text,boolean) TO authenticated;
COMMIT;
