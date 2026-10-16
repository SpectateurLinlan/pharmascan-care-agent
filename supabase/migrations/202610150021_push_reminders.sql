-- Additive: reviewed rules/occurrences remain the only schedule truth.
BEGIN;
ALTER TABLE public.patient_profiles ADD COLUMN reminders_enabled boolean NOT NULL DEFAULT true;
CREATE TABLE public.push_subscriptions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id) ON DELETE RESTRICT,
 endpoint text NOT NULL CHECK(length(endpoint) BETWEEN 12 AND 2048 AND endpoint LIKE 'https://%'),
 keys jsonb NOT NULL CHECK(jsonb_typeof(keys)='object' AND keys ? 'p256dh' AND keys ? 'auth'),
 enabled boolean NOT NULL DEFAULT true,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(patient_id,id), UNIQUE(patient_id,endpoint)
);
CREATE INDEX push_subscriptions_owner_idx ON public.push_subscriptions(patient_id) WHERE enabled;
ALTER TABLE public.push_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.push_subscriptions FORCE ROW LEVEL SECURITY;
CREATE POLICY push_subscriptions_owner ON public.push_subscriptions FOR ALL TO authenticated
 USING(patient_id=auth.uid()) WITH CHECK(patient_id=auth.uid());
GRANT SELECT,INSERT,UPDATE ON public.push_subscriptions TO authenticated;
CREATE FUNCTION public.core_bound_push_devices() RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER AS $$
BEGIN
 IF TG_OP='UPDATE' AND (NEW.patient_id,NEW.id,NEW.endpoint) IS DISTINCT FROM (OLD.patient_id,OLD.id,OLD.endpoint) THEN
  RAISE EXCEPTION 'Push subscription binding is immutable';
 END IF;
 PERFORM 1 FROM public.patient_profiles WHERE user_id=NEW.patient_id FOR UPDATE;
 IF NEW.enabled AND NOT EXISTS(SELECT 1 FROM public.push_subscriptions WHERE patient_id=NEW.patient_id AND endpoint=NEW.endpoint AND enabled)
 AND (SELECT count(*) FROM public.push_subscriptions WHERE patient_id=NEW.patient_id AND enabled)>=8 THEN
  RAISE EXCEPTION 'At most eight enabled push devices';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER bound_push_devices BEFORE INSERT OR UPDATE ON public.push_subscriptions
 FOR EACH ROW EXECUTE FUNCTION public.core_bound_push_devices();
REVOKE ALL ON FUNCTION public.core_bound_push_devices() FROM PUBLIC;

CREATE TABLE public.notification_deliveries (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id) ON DELETE RESTRICT,
 occurrence_id uuid NOT NULL,
 regimen_id uuid NOT NULL,
 rule_id uuid NOT NULL,
 subscription_id uuid NOT NULL,
 slot text NOT NULL CHECK(length(slot)<=80),
 remind_at timestamptz NOT NULL,
 status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','sending','sent','cancelled','failed')),
 attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 3),
 next_attempt_at timestamptz NOT NULL,
 claimed_at timestamptz,
 sent_at timestamptz,
 error_category text CHECK(error_category IN ('expired_subscription','temporary','provider_rejected','invalid_subscription','uncertain_delivery')),
 UNIQUE(occurrence_id,subscription_id,slot),
 FOREIGN KEY(patient_id,occurrence_id) REFERENCES public.dose_occurrences(patient_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(patient_id,regimen_id) REFERENCES public.regimen_versions(patient_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(patient_id,rule_id) REFERENCES public.dose_rules(patient_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(patient_id,subscription_id) REFERENCES public.push_subscriptions(patient_id,id) ON DELETE RESTRICT
);
CREATE INDEX notification_deliveries_due_idx ON public.notification_deliveries(next_attempt_at) WHERE status='pending';
ALTER TABLE public.notification_deliveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notification_deliveries FORCE ROW LEVEL SECURITY;
CREATE POLICY notification_deliveries_owner_read ON public.notification_deliveries FOR SELECT TO authenticated USING(patient_id=auth.uid());
GRANT SELECT ON public.notification_deliveries TO authenticated;
-- Only the explicit administrative worker can create/claim delivery jobs.
NOTIFY pgrst,'reload schema';
COMMIT;
