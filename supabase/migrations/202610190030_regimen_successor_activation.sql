-- Atomically activate a patient-confirmed successor regimen without requiring
-- a separate stop request. Prior regimen instructions and dose events remain
-- immutable; only its active state, effective end, rules, and open future
-- occurrences are reconciled.
BEGIN;

-- Permit a draft to explicitly name the one active version it may succeed.
-- Every other overlapping active plan remains rejected by the established
-- patient-serialized guard.
CREATE OR REPLACE FUNCTION public.core_guard_regimen_overlap() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $$
DECLARE patient_zone text; local_today date;
BEGIN
 IF NEW.state NOT IN ('draft','pending_clarification','active') THEN RETURN NEW; END IF;
 IF TG_OP='UPDATE' AND OLD.state='active' THEN RETURN NEW; END IF;
 SELECT timezone INTO patient_zone FROM public.patient_profiles
 WHERE user_id=NEW.patient_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Owned patient profile required'; END IF;
 local_today := (now() AT TIME ZONE patient_zone)::date;
 IF EXISTS (
  SELECT 1 FROM public.regimen_versions r
  JOIN public.patient_medications existing_medicine
   ON existing_medicine.patient_id=r.patient_id AND existing_medicine.id=r.patient_medication_id
  JOIN public.patient_medications incoming_medicine
   ON incoming_medicine.patient_id=NEW.patient_id AND incoming_medicine.id=NEW.patient_medication_id
  WHERE r.patient_id=NEW.patient_id AND r.state='active' AND r.id<>NEW.id
   AND (NEW.supersedes_id IS DISTINCT FROM r.id
        OR NEW.patient_medication_id IS DISTINCT FROM r.patient_medication_id)
   AND (
    (existing_medicine.product_id IS NOT NULL AND existing_medicine.product_id=incoming_medicine.product_id)
    OR lower(btrim(regexp_replace(existing_medicine.display_name, '[[:space:]]+', ' ', 'g')))
       =lower(btrim(regexp_replace(incoming_medicine.display_name, '[[:space:]]+', ' ', 'g')))
   )
   AND (
    r.patient_medication_id=NEW.patient_medication_id
    OR (
     greatest(coalesce(NEW.course_start_date,local_today),local_today)
      <=coalesce(r.course_end_date,'infinity'::date)
     AND greatest(coalesce(r.course_start_date,'-infinity'::date),
                   coalesce((r.effective_from AT TIME ZONE patient_zone)::date,'-infinity'::date))
      <=coalesce(NEW.course_end_date,'infinity'::date)
    )
   )
 ) THEN
  RAISE EXCEPTION USING ERRCODE='P7501', MESSAGE='Overlapping active medication plan';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION public.activate_medication_regimen_version(
    p_regimen_id uuid,
    p_challenge_id uuid,
    p_timezone text
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    owner_id uuid := auth.uid();
    patient_timezone text;
    incoming public.regimen_versions%ROWTYPE;
    predecessor public.regimen_versions%ROWTYPE;
    source_row public.source_documents%ROWTYPE;
    medication public.patient_medications%ROWTYPE;
    activation_time timestamptz := clock_timestamp();
    field_ids jsonb;
    frequency_kind text;
    local_time_value text;
    days smallint[];
    superseded_ids uuid[] := ARRAY[]::uuid[];
    activation_session_id uuid;
BEGIN
    IF owner_id IS NULL THEN RAISE EXCEPTION 'Authentication required'; END IF;

    -- Match the same-patient serialization order used by the overlap guard.
    SELECT timezone INTO patient_timezone
      FROM public.patient_profiles WHERE user_id = owner_id FOR UPDATE;
    IF NOT FOUND OR p_timezone IS DISTINCT FROM patient_timezone THEN
        RAISE EXCEPTION 'Patient timezone changed; reload the plan before confirming';
    END IF;

    SELECT * INTO incoming FROM public.regimen_versions
      WHERE patient_id = owner_id AND id = p_regimen_id FOR UPDATE;
    IF NOT FOUND OR incoming.state NOT IN ('draft', 'pending_clarification') THEN
        RAISE EXCEPTION 'A current owned regimen draft is required';
    END IF;
    SELECT session_id INTO activation_session_id
      FROM public.confirmation_challenges
      WHERE patient_id = owner_id AND id = p_challenge_id
        AND regimen_id = incoming.id AND action = 'activate_regimen';
    IF NOT FOUND THEN RAISE EXCEPTION 'A matching patient confirmation is required'; END IF;
    IF incoming.supersedes_id IS NOT NULL THEN
        SELECT * INTO predecessor FROM public.regimen_versions
          WHERE patient_id = owner_id AND patient_medication_id = incoming.patient_medication_id
            AND id = incoming.supersedes_id FOR UPDATE;
        IF NOT FOUND OR predecessor.state <> 'active'
           OR predecessor.version_no >= incoming.version_no THEN
            RAISE EXCEPTION 'The active plan changed; review it again before confirming';
        END IF;
    ELSIF EXISTS (
        SELECT 1 FROM public.regimen_versions
        WHERE patient_id = owner_id AND patient_medication_id = incoming.patient_medication_id
          AND state = 'active'
    ) THEN
        RAISE EXCEPTION 'An active plan must be updated through its successor version';
    END IF;

    -- Lock in the established order: active regimen, medication, source,
    -- then B14 challenge (consumed by the regimen guard below). This lets
    -- an in-flight self-report finish before its future occurrence is closed.
    SELECT * INTO medication FROM public.patient_medications
      WHERE patient_id = owner_id AND id = incoming.patient_medication_id FOR UPDATE;
    IF NOT FOUND OR medication.archived_at IS NOT NULL THEN
        RAISE EXCEPTION 'Medication is unavailable';
    END IF;
    SELECT * INTO source_row FROM public.source_documents
      WHERE patient_id = owner_id AND id = incoming.source_id FOR SHARE;
    IF NOT FOUND OR source_row.review_status NOT IN ('user_reviewed', 'professional_verified')
       OR source_row.reviewed_at IS NULL THEN
        RAISE EXCEPTION 'A reviewed source document is required';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.source_fields
        WHERE patient_id = owner_id AND source_id = incoming.source_id
          AND review_status NOT IN ('user_reviewed', 'professional_verified')
    ) THEN RAISE EXCEPTION 'Every field in the cited source must be reviewed'; END IF;

    SELECT jsonb_object_agg(field_name, id) INTO field_ids
      FROM public.source_fields
      WHERE patient_id = owner_id AND source_id = incoming.source_id
        AND review_status IN ('user_reviewed', 'professional_verified');
    IF field_ids IS NULL THEN RAISE EXCEPTION 'Reviewed regimen evidence is missing'; END IF;

    IF predecessor.id IS NOT NULL THEN
        UPDATE public.regimen_versions
          SET state = 'superseded', effective_to = activation_time
          WHERE patient_id = owner_id AND id = predecessor.id AND state = 'active';
        IF NOT FOUND THEN RAISE EXCEPTION 'The active plan changed; reload before confirming'; END IF;

        -- Preserve occurrences tied to a dose event. Close only open future
        -- occurrences that have no corresponding patient report.
        UPDATE public.dose_occurrences occurrence
          SET status = 'closed'
          WHERE occurrence.patient_id = owner_id AND occurrence.regimen_id = predecessor.id
            AND occurrence.due_at >= activation_time AND occurrence.status <> 'closed'
            AND NOT EXISTS (
                SELECT 1 FROM public.dose_events event
                WHERE event.patient_id = occurrence.patient_id
                  AND event.occurrence_id = occurrence.id
            );
        UPDATE public.dose_rules SET enabled = false
          WHERE patient_id = owner_id AND regimen_id = predecessor.id AND enabled;
        INSERT INTO public.audit_events(
            patient_id, session_id, correlation_id, actor_type, action, regimen_id,
            before_redacted, after_redacted
        ) VALUES (
            owner_id, activation_session_id, gen_random_uuid(), 'patient', 'regimen_superseded', predecessor.id,
            jsonb_build_object('state', 'active'), jsonb_build_object('state', 'superseded')
        );
        superseded_ids := ARRAY[predecessor.id];
    END IF;

    UPDATE public.regimen_versions
      SET state = 'active',
          effective_from = activation_time,
          effective_to = NULL,
          confirmation_challenge_id = p_challenge_id,
          source_reviewed_at = source_row.reviewed_at,
          medication_name_field_id = (field_ids ->> 'medication_name')::uuid,
          quantity_field_id = (field_ids ->> 'dose_amount')::uuid,
          unit_field_id = (field_ids ->> 'dose_unit')::uuid,
          frequency_field_id = CASE WHEN incoming.is_prn THEN NULL ELSE (field_ids ->> 'frequency_rule')::uuid END,
          prn_field_id = CASE WHEN incoming.is_prn THEN (field_ids ->> 'is_prn')::uuid ELSE NULL END
      WHERE patient_id = owner_id AND id = incoming.id;

    -- Build the new version's schedule in the same transaction. The regimen
    -- guard has already consumed the explicitly confirmed B14 challenge.
    IF incoming.is_prn THEN
        INSERT INTO public.dose_rules(patient_id, regimen_id, rule_kind, local_time, days_of_week, timezone)
        VALUES (owner_id, incoming.id, 'prn', NULL, NULL, patient_timezone);
    ELSE
        frequency_kind := coalesce(incoming.frequency_rule ->> 'kind', 'daily');
        days := CASE WHEN frequency_kind = 'weekly'
            THEN coalesce(
                ARRAY(SELECT jsonb_array_elements_text(incoming.frequency_rule -> 'days_of_week')::smallint),
                ARRAY[]::smallint[]
            )
            ELSE ARRAY[1, 2, 3, 4, 5, 6, 7]::smallint[]
        END;
        IF coalesce(cardinality(days), 0) = 0 THEN days := ARRAY[1, 2, 3, 4, 5, 6, 7]::smallint[]; END IF;
        FOR local_time_value IN
            SELECT DISTINCT value
              FROM jsonb_array_elements_text(
                  CASE WHEN jsonb_typeof(incoming.frequency_rule -> 'local_times') = 'array'
                       AND jsonb_array_length(incoming.frequency_rule -> 'local_times') > 0
                      THEN incoming.frequency_rule -> 'local_times'
                      ELSE '["08:00"]'::jsonb END
              ) AS slots(value)
        LOOP
            INSERT INTO public.dose_rules(patient_id, regimen_id, rule_kind, local_time, days_of_week, timezone)
            VALUES (owner_id, incoming.id, 'scheduled', local_time_value::time, days, patient_timezone);
        END LOOP;
    END IF;

    INSERT INTO public.audit_events(
        patient_id, session_id, correlation_id, actor_type, action, regimen_id,
        before_redacted, after_redacted
    ) VALUES (
        owner_id, activation_session_id, gen_random_uuid(), 'patient', 'regimen_activated', incoming.id,
        jsonb_build_object('state', incoming.state), jsonb_build_object('state', 'active')
    );

    RETURN jsonb_build_object(
        'regimen', (SELECT to_jsonb(active_row) FROM public.regimen_versions active_row
                    WHERE active_row.patient_id = owner_id AND active_row.id = incoming.id),
        'superseded_regimen_ids', to_jsonb(superseded_ids)
    );
END;
$$;

REVOKE ALL ON FUNCTION public.activate_medication_regimen_version(uuid, uuid, text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.activate_medication_regimen_version(uuid, uuid, text) TO authenticated;

NOTIFY pgrst, 'reload schema';
COMMIT;
