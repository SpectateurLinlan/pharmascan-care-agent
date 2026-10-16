-- Removes only the new guard; never removes patient data or prior safety rules.
BEGIN;
DROP TRIGGER regimen_overlap_guard ON public.regimen_versions;
DROP FUNCTION public.core_guard_regimen_overlap();
COMMIT;
