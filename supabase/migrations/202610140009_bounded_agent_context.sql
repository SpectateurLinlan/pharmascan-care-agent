BEGIN;
ALTER TABLE public.agent_sessions
 ADD COLUMN context jsonb NOT NULL DEFAULT '{"version":1,"recent_turns":[],"conversation_summary":""}',
 ADD COLUMN context_medication_id uuid GENERATED ALWAYS AS ((context->>'referenced_medication_id')::uuid) STORED,
 ADD COLUMN context_regimen_id uuid GENERATED ALWAYS AS ((context->>'referenced_regimen_id')::uuid) STORED,
 ADD COLUMN context_occurrence_id uuid GENERATED ALWAYS AS ((context->>'referenced_occurrence_id')::uuid) STORED,
 ADD CONSTRAINT agent_context_bounds CHECK (
   jsonb_typeof(context)='object' AND context->>'version'='1' AND octet_length(context::text)<=20000
   AND jsonb_typeof(context->'recent_turns')='array' AND jsonb_array_length(context->'recent_turns')<=6
   AND length(context->>'conversation_summary')<=600),
 ADD CONSTRAINT agent_context_medication_owner FOREIGN KEY(patient_id,context_medication_id)
 REFERENCES public.patient_medications(patient_id,id) ON DELETE RESTRICT,
 ADD CONSTRAINT agent_context_regimen_owner FOREIGN KEY(patient_id,context_regimen_id)
 REFERENCES public.regimen_versions(patient_id,id) ON DELETE RESTRICT,
 ADD CONSTRAINT agent_context_occurrence_owner FOREIGN KEY(patient_id,context_occurrence_id)
 REFERENCES public.dose_occurrences(patient_id,id) ON DELETE RESTRICT;
-- Existing session owner RLS and confirmation version checks remain intact.
COMMIT;
