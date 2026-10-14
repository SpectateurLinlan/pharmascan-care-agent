-- Patient-owned evidence artifacts. No change to existing clinical guards.
CREATE TABLE public.medication_evidence_tasks (
 id uuid PRIMARY KEY,
 patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id) ON DELETE RESTRICT,
 medication_id uuid NOT NULL,
 data jsonb NOT NULL CHECK (jsonb_typeof(data) = 'object' AND octet_length(data::text) <= 262144
   AND data->>'patient_id' = patient_id::text AND data->>'id' = id::text),
 version integer NOT NULL DEFAULT 1 CHECK (version > 0),
 created_at timestamptz NOT NULL DEFAULT now(),
 demo_only boolean NOT NULL DEFAULT true CHECK (demo_only = true),
 FOREIGN KEY (patient_id, medication_id) REFERENCES public.patient_medications(patient_id,id) ON DELETE RESTRICT,
 UNIQUE (patient_id,id), UNIQUE (patient_id,medication_id,id)
);
CREATE INDEX medication_evidence_tasks_owner_idx ON public.medication_evidence_tasks(patient_id,created_at);
ALTER TABLE public.medication_evidence_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.medication_evidence_tasks FORCE ROW LEVEL SECURITY;
CREATE POLICY medication_evidence_tasks_owner ON public.medication_evidence_tasks FOR ALL TO authenticated
 USING (patient_id=(SELECT auth.uid())) WITH CHECK (patient_id=(SELECT auth.uid()));
REVOKE ALL ON public.medication_evidence_tasks FROM anon;
GRANT SELECT,INSERT ON public.medication_evidence_tasks TO authenticated;
GRANT UPDATE ON public.medication_evidence_tasks TO authenticated;
CREATE TABLE public.medication_source_links (
 id uuid PRIMARY KEY,
 patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id) ON DELETE RESTRICT,
 medication_id uuid NOT NULL, source_id uuid NOT NULL,
 data jsonb NOT NULL CHECK (jsonb_typeof(data) = 'object' AND octet_length(data::text) <= 262144
   AND data->>'patient_id' = patient_id::text AND data->>'id' = id::text),
 version integer NOT NULL DEFAULT 1 CHECK (version > 0),
 created_at timestamptz NOT NULL DEFAULT now(),
 demo_only boolean NOT NULL DEFAULT true CHECK (demo_only = true),
 FOREIGN KEY (patient_id, medication_id) REFERENCES public.patient_medications(patient_id,id) ON DELETE RESTRICT, FOREIGN KEY (patient_id, source_id) REFERENCES public.source_documents(patient_id,id) ON DELETE RESTRICT,
 UNIQUE (patient_id,id), UNIQUE (patient_id,medication_id,id)
);
CREATE INDEX medication_source_links_owner_idx ON public.medication_source_links(patient_id,created_at);
ALTER TABLE public.medication_source_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.medication_source_links FORCE ROW LEVEL SECURITY;
CREATE POLICY medication_source_links_owner ON public.medication_source_links FOR ALL TO authenticated
 USING (patient_id=(SELECT auth.uid())) WITH CHECK (patient_id=(SELECT auth.uid()));
REVOKE ALL ON public.medication_source_links FROM anon;
GRANT SELECT,INSERT ON public.medication_source_links TO authenticated;
CREATE TABLE public.medication_images (
 id uuid PRIMARY KEY,
 patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id) ON DELETE RESTRICT,
 medication_id uuid NOT NULL,
 data jsonb NOT NULL CHECK (jsonb_typeof(data) = 'object' AND octet_length(data::text) <= 262144
   AND data->>'patient_id' = patient_id::text AND data->>'id' = id::text),
 version integer NOT NULL DEFAULT 1 CHECK (version > 0),
 created_at timestamptz NOT NULL DEFAULT now(),
 demo_only boolean NOT NULL DEFAULT true CHECK (demo_only = true),
 FOREIGN KEY (patient_id, medication_id) REFERENCES public.patient_medications(patient_id,id) ON DELETE RESTRICT,
 UNIQUE (patient_id,id), UNIQUE (patient_id,medication_id,id)
);
CREATE INDEX medication_images_owner_idx ON public.medication_images(patient_id,created_at);
ALTER TABLE public.medication_images ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.medication_images FORCE ROW LEVEL SECURITY;
CREATE POLICY medication_images_owner ON public.medication_images FOR ALL TO authenticated
 USING (patient_id=(SELECT auth.uid())) WITH CHECK (patient_id=(SELECT auth.uid()));
REVOKE ALL ON public.medication_images FROM anon;
GRANT SELECT,INSERT ON public.medication_images TO authenticated;
CREATE TABLE public.visual_reference_sets (
 id uuid PRIMARY KEY,
 patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id) ON DELETE RESTRICT,
 medication_id uuid NOT NULL,
 data jsonb NOT NULL CHECK (jsonb_typeof(data) = 'object' AND octet_length(data::text) <= 262144
   AND data->>'patient_id' = patient_id::text AND data->>'id' = id::text),
 version integer NOT NULL DEFAULT 1 CHECK (version > 0),
 created_at timestamptz NOT NULL DEFAULT now(),
 demo_only boolean NOT NULL DEFAULT true CHECK (demo_only = true),
 FOREIGN KEY (patient_id, medication_id) REFERENCES public.patient_medications(patient_id,id) ON DELETE RESTRICT,
 UNIQUE (patient_id,id), UNIQUE (patient_id,medication_id,id)
);
CREATE INDEX visual_reference_sets_owner_idx ON public.visual_reference_sets(patient_id,created_at);
ALTER TABLE public.visual_reference_sets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.visual_reference_sets FORCE ROW LEVEL SECURITY;
CREATE POLICY visual_reference_sets_owner ON public.visual_reference_sets FOR ALL TO authenticated
 USING (patient_id=(SELECT auth.uid())) WITH CHECK (patient_id=(SELECT auth.uid()));
REVOKE ALL ON public.visual_reference_sets FROM anon;
GRANT SELECT,INSERT ON public.visual_reference_sets TO authenticated;
CREATE TABLE public.image_embeddings (
 id uuid PRIMARY KEY,
 patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id) ON DELETE RESTRICT,
 medication_id uuid NOT NULL, image_id uuid NOT NULL, reference_set_id uuid NOT NULL,
 data jsonb NOT NULL CHECK (jsonb_typeof(data) = 'object' AND octet_length(data::text) <= 262144
   AND data->>'patient_id' = patient_id::text AND data->>'id' = id::text),
 version integer NOT NULL DEFAULT 1 CHECK (version > 0),
 created_at timestamptz NOT NULL DEFAULT now(),
 demo_only boolean NOT NULL DEFAULT true CHECK (demo_only = true),
 FOREIGN KEY (patient_id, medication_id) REFERENCES public.patient_medications(patient_id,id) ON DELETE RESTRICT, FOREIGN KEY (patient_id, medication_id, image_id) REFERENCES public.medication_images(patient_id,medication_id,id) ON DELETE RESTRICT, FOREIGN KEY (patient_id, medication_id, reference_set_id) REFERENCES public.visual_reference_sets(patient_id,medication_id,id) ON DELETE RESTRICT,
 UNIQUE (patient_id,id), UNIQUE (patient_id,medication_id,id)
);
CREATE INDEX image_embeddings_owner_idx ON public.image_embeddings(patient_id,created_at);
ALTER TABLE public.image_embeddings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.image_embeddings FORCE ROW LEVEL SECURITY;
CREATE POLICY image_embeddings_owner ON public.image_embeddings FOR ALL TO authenticated
 USING (patient_id=(SELECT auth.uid())) WITH CHECK (patient_id=(SELECT auth.uid()));
REVOKE ALL ON public.image_embeddings FROM anon;
GRANT SELECT,INSERT ON public.image_embeddings TO authenticated;
CREATE TABLE public.recognition_runs (
 id uuid PRIMARY KEY,
 patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id) ON DELETE RESTRICT,
 selected_regimen_id uuid,
 data jsonb NOT NULL CHECK (jsonb_typeof(data) = 'object' AND octet_length(data::text) <= 262144
   AND data->>'patient_id' = patient_id::text AND data->>'id' = id::text),
 version integer NOT NULL DEFAULT 1 CHECK (version > 0),
 created_at timestamptz NOT NULL DEFAULT now(),
 demo_only boolean NOT NULL DEFAULT true CHECK (demo_only = true),
 FOREIGN KEY (patient_id, selected_regimen_id) REFERENCES public.regimen_versions(patient_id,id) ON DELETE RESTRICT,
 UNIQUE (patient_id,id)
);
CREATE INDEX recognition_runs_owner_idx ON public.recognition_runs(patient_id,created_at);
ALTER TABLE public.recognition_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.recognition_runs FORCE ROW LEVEL SECURITY;
CREATE POLICY recognition_runs_owner ON public.recognition_runs FOR ALL TO authenticated
 USING (patient_id=(SELECT auth.uid())) WITH CHECK (patient_id=(SELECT auth.uid()));
REVOKE ALL ON public.recognition_runs FROM anon;
GRANT SELECT,INSERT ON public.recognition_runs TO authenticated;
ALTER TABLE public.image_embeddings ADD CONSTRAINT image_embedding_dimension_ck
 CHECK (jsonb_array_length(data->'result'->'embedding')=256 AND data->'result'->>'dimension'='256');
-- History/photo/evidence rows have no client UPDATE/DELETE grants. Task writes
-- use a compare-and-swap version filter; existing sources keep their guards.
ALTER TABLE public.source_documents DROP CONSTRAINT source_documents_source_kind_check;
ALTER TABLE public.source_documents ADD CONSTRAINT source_documents_source_kind_check
 CHECK (source_kind IN ('mock_import','user_manual','package','pharmacy_label','prescription'));
ALTER TABLE public.medication_images ADD COLUMN source_id uuid;
ALTER TABLE public.medication_images ADD CONSTRAINT medication_images_source_fk
 FOREIGN KEY (patient_id,source_id) REFERENCES public.source_documents(patient_id,id) ON DELETE RESTRICT;
NOTIFY pgrst, 'reload schema';

-- Keep redundant typed payload references aligned with their constrained columns.
ALTER TABLE public.medication_evidence_tasks ADD CONSTRAINT medication_evidence_tasks_medication_id_payload_ck CHECK (data->>'medication_id'=medication_id::text);
ALTER TABLE public.medication_source_links ADD CONSTRAINT medication_source_links_medication_id_payload_ck CHECK (data->>'medication_id'=medication_id::text);
ALTER TABLE public.medication_source_links ADD CONSTRAINT medication_source_links_source_id_payload_ck CHECK (data->>'source_id'=source_id::text);
ALTER TABLE public.medication_images ADD CONSTRAINT medication_images_medication_id_payload_ck CHECK (data->>'medication_id'=medication_id::text);
ALTER TABLE public.visual_reference_sets ADD CONSTRAINT visual_reference_sets_medication_id_payload_ck CHECK (data->>'medication_id'=medication_id::text);
ALTER TABLE public.image_embeddings ADD CONSTRAINT image_embeddings_medication_id_payload_ck CHECK (data->>'medication_id'=medication_id::text);
ALTER TABLE public.image_embeddings ADD CONSTRAINT image_embeddings_image_id_payload_ck CHECK (data->>'image_id'=image_id::text);
ALTER TABLE public.image_embeddings ADD CONSTRAINT image_embeddings_reference_set_id_payload_ck CHECK (data->>'reference_set_id'=reference_set_id::text);
