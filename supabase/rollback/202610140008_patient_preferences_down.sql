-- Disposable databases only; never run shared development rollback for QA.
BEGIN;
DROP TRIGGER patient_preferences_timestamp ON public.patient_profiles;
DROP FUNCTION public.core_preferences_timestamp();
ALTER TABLE public.patient_profiles DROP COLUMN speech_locale,DROP COLUMN text_size,
 DROP COLUMN voice_enabled,DROP COLUMN tts_autoplay,DROP COLUMN reminder_lead_minutes,DROP COLUMN updated_at;
COMMIT;
