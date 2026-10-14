-- Disposable database only. Never run on shared development data.
DROP FUNCTION public.retire_personal_reference(uuid);
REVOKE UPDATE(data) ON public.medication_images FROM authenticated;
DROP POLICY medication_images_retire_owner ON public.medication_images;
DROP TRIGGER reference_retirement_guard ON public.medication_images;
DROP FUNCTION public.guard_reference_retirement();
NOTIFY pgrst,'reload schema';
