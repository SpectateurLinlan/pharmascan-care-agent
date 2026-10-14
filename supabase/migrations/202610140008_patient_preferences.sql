-- Reuse the existing owner profile and language column; no duplicate profile.
BEGIN;
ALTER TABLE public.patient_profiles
 ADD COLUMN speech_locale text GENERATED ALWAYS AS (CASE language WHEN 'zh' THEN 'zh-CN' ELSE 'en-SG' END) STORED,
 ADD COLUMN text_size text NOT NULL DEFAULT 'standard' CHECK(text_size IN ('standard','large')),
 ADD COLUMN voice_enabled boolean NOT NULL DEFAULT true,
 ADD COLUMN tts_autoplay boolean NOT NULL DEFAULT false,
 ADD COLUMN reminder_lead_minutes integer NOT NULL DEFAULT 0 CHECK(reminder_lead_minutes BETWEEN 0 AND 120),
 ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();
CREATE FUNCTION public.core_preferences_timestamp() RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER AS $$
BEGIN
 NEW.updated_at := now();
 RETURN NEW;
END $$;
CREATE TRIGGER patient_preferences_timestamp BEFORE UPDATE ON public.patient_profiles
 FOR EACH ROW EXECUTE FUNCTION public.core_preferences_timestamp();
REVOKE ALL ON FUNCTION public.core_preferences_timestamp() FROM PUBLIC;
-- Existing owner RLS and authenticated grants apply unchanged.
COMMIT;
