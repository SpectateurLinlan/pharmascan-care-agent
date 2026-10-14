-- Add a numeric UX preference; preserve owner RLS and legacy text-size clients.
BEGIN;
ALTER TABLE public.patient_profiles ADD COLUMN text_scale_percent integer NOT NULL DEFAULT 100
 CHECK (text_scale_percent BETWEEN 100 AND 150);
UPDATE public.patient_profiles SET text_scale_percent = 125 WHERE text_size = 'large';
CREATE FUNCTION public.core_text_scale_compatibility() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = public AS $$
BEGIN
 IF TG_OP = 'UPDATE' THEN
  IF NEW.text_scale_percent = OLD.text_scale_percent AND NEW.text_size IS DISTINCT FROM OLD.text_size THEN
   NEW.text_scale_percent := CASE NEW.text_size WHEN 'large' THEN 125 ELSE 100 END;
  END IF;
 END IF;
 NEW.text_size := CASE WHEN NEW.text_scale_percent >= 125 THEN 'large' ELSE 'standard' END;
 RETURN NEW;
END $$;
CREATE TRIGGER patient_text_scale_compatibility BEFORE INSERT OR UPDATE ON public.patient_profiles
 FOR EACH ROW EXECUTE FUNCTION public.core_text_scale_compatibility();
REVOKE ALL ON FUNCTION public.core_text_scale_compatibility() FROM PUBLIC;
COMMIT;
