-- Destructive rollback: disposable test databases only, never run on patient data.
BEGIN;
DROP TABLE public.notification_deliveries;
DROP TABLE public.push_subscriptions;
DROP FUNCTION public.core_bound_push_devices();
ALTER TABLE public.patient_profiles DROP COLUMN reminders_enabled;
COMMIT;
