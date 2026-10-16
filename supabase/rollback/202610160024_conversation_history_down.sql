-- Refuse loss of retained conversations. No rollback was executed in Session04.5.
DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.conversation_turns) THEN RAISE EXCEPTION 'retained history blocks rollback'; END IF; END $$;
DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.source_documents WHERE dose_basis IS NOT NULL) THEN RAISE EXCEPTION 'retained source details block rollback'; END IF; END $$;
DROP FUNCTION public.append_conversation_turn(jsonb);
DROP FUNCTION public.clear_conversation_history();
DROP TABLE public.conversation_turns;
ALTER TABLE public.patient_profiles DROP COLUMN conversation_history_enabled;
DROP TRIGGER source_dose_basis_immutable ON public.source_documents;
DROP FUNCTION public.guard_reviewed_dose_basis();
ALTER TABLE public.source_documents DROP COLUMN dose_basis;
