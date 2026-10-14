-- Preserve untrusted extraction evidence separately from patient-entered instructions.
BEGIN;
ALTER TABLE public.source_documents ADD COLUMN extraction_evidence jsonb;
ALTER TABLE public.source_documents ADD CONSTRAINT source_documents_extraction_evidence_ck
 CHECK (extraction_evidence IS NULL OR (jsonb_typeof(extraction_evidence) = 'object'
 AND octet_length(extraction_evidence::text) <= 65536));
CREATE FUNCTION public.core_guard_extraction_evidence() RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER AS $$
BEGIN
 IF NEW.extraction_evidence IS DISTINCT FROM OLD.extraction_evidence THEN
  RAISE EXCEPTION 'Extraction evidence is immutable';
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER source_documents_extraction_evidence_immutable BEFORE UPDATE ON public.source_documents
 FOR EACH ROW EXECUTE FUNCTION public.core_guard_extraction_evidence();
REVOKE ALL ON FUNCTION public.core_guard_extraction_evidence() FROM PUBLIC;
NOTIFY pgrst, 'reload schema';
COMMIT;
