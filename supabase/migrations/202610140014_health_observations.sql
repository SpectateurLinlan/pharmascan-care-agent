BEGIN;
CREATE TABLE public.health_observations (
    patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id) ON DELETE RESTRICT,
    id uuid NOT NULL,
    occurred_at timestamptz NOT NULL,
    description text NOT NULL CHECK (length(btrim(description)) BETWEEN 1 AND 1000),
    severity text CHECK (severity IN ('mild', 'moderate', 'severe')),
    notes text CHECK (notes IS NULL OR length(notes) <= 1000),
    medication_id uuid,
    source text NOT NULL DEFAULT 'patient_reported' CHECK (source = 'patient_reported'),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    demo_only boolean NOT NULL DEFAULT true CHECK (demo_only),
    PRIMARY KEY (patient_id, id),
    FOREIGN KEY (patient_id, medication_id) REFERENCES public.patient_medications(patient_id, id)
);
CREATE INDEX health_observations_patient_time_idx ON public.health_observations(patient_id, occurred_at);
ALTER TABLE public.health_observations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.health_observations FORCE ROW LEVEL SECURITY;
CREATE POLICY health_observations_owner ON public.health_observations TO authenticated
    USING (patient_id = (SELECT auth.uid())) WITH CHECK (patient_id = (SELECT auth.uid()));
REVOKE ALL ON public.health_observations FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.health_observations TO authenticated;
COMMIT;
