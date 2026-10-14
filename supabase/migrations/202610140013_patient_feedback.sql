BEGIN;
CREATE TABLE public.patient_feedback (
 patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id) ON DELETE RESTRICT,
 id uuid NOT NULL, category text NOT NULL CHECK(category IN ('issue','suggestion')),
 message text NOT NULL CHECK(length(trim(message)) BETWEEN 5 AND 2000),
 created_at timestamptz NOT NULL DEFAULT now(),demo_only boolean NOT NULL DEFAULT true CHECK(demo_only=true),
 PRIMARY KEY(patient_id,id)
);
ALTER TABLE public.patient_feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.patient_feedback FORCE ROW LEVEL SECURITY;
CREATE POLICY patient_feedback_owner ON public.patient_feedback FOR ALL TO authenticated
 USING(patient_id=auth.uid()) WITH CHECK(patient_id=auth.uid());
REVOKE ALL ON public.patient_feedback FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT ON public.patient_feedback TO authenticated;
NOTIFY pgrst,'reload schema';
COMMIT;
