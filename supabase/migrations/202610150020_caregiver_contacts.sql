-- Patient-owned contact notes only; independent verification/delivery remain unavailable.
BEGIN;
CREATE TABLE public.caregiver_contacts (
 patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id) ON DELETE RESTRICT,
 id uuid NOT NULL, name text NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 80),
 relationship text CHECK(length(relationship)<=80),
 contact_type text NOT NULL CHECK(contact_type IN ('email','phone')),
 contact_value text NOT NULL CHECK(length(contact_value) BETWEEN 3 AND 254),
 storage_consent boolean NOT NULL CHECK(storage_consent=true),
 verification_status text NOT NULL DEFAULT 'pending' CHECK(verification_status='pending'),
 notifications_enabled boolean NOT NULL DEFAULT false CHECK(notifications_enabled=false),
 sharing_enabled boolean NOT NULL DEFAULT false CHECK(sharing_enabled=false),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 demo_only boolean NOT NULL DEFAULT true CHECK(demo_only=true),
 PRIMARY KEY(patient_id,id), UNIQUE(patient_id,contact_type,contact_value),
 CHECK((contact_type='email' AND contact_value=lower(contact_value) AND contact_value ~ '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$')
    OR (contact_type='phone' AND contact_value ~ '^\+[1-9][0-9]{7,14}$'))
);
ALTER TABLE public.caregiver_contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.caregiver_contacts FORCE ROW LEVEL SECURITY;
CREATE POLICY caregiver_contacts_owner ON public.caregiver_contacts FOR ALL TO authenticated
 USING(patient_id=auth.uid()) WITH CHECK(patient_id=auth.uid());
REVOKE ALL ON public.caregiver_contacts FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.caregiver_contacts TO authenticated;
NOTIFY pgrst,'reload schema';
COMMIT;
