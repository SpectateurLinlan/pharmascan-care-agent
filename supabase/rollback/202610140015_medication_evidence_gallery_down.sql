-- Disposable database only; do not run on shared patient data.
DROP TABLE public.recognition_runs;
DROP TABLE public.image_embeddings;
DROP TABLE public.visual_reference_sets;
DROP TABLE public.medication_images;
DROP TABLE public.medication_source_links;
DROP TABLE public.medication_evidence_tasks;
-- Restore only after ensuring there are no retained extended source kinds.
ALTER TABLE public.source_documents DROP CONSTRAINT source_documents_source_kind_check;
ALTER TABLE public.source_documents ADD CONSTRAINT source_documents_source_kind_check
 CHECK (source_kind IN ('mock_import','user_manual'));
