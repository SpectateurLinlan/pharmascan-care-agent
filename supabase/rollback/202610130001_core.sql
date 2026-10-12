-- 危险：仅供没有任何业务数据的空临时测试数据库；不要在生产执行。
-- 即便全是 demo_only 行也拒绝回滚，必须通过独立、已审批的测试库清理流程处理数据。
-- 此脚本不清理数据、不删除 auth.users、不删除 schema/extension，不使用 CASCADE。
-- 开发者必须在独立测试连接中显式确认：
-- SET pharmascan.rollback_target = 'empty-temporary-test-database';
-- 尚未实际执行此回滚；不能把静态测试当作真实数据库验证。
BEGIN;
SET LOCAL TIME ZONE 'UTC';
SET LOCAL search_path = pg_catalog, public;

DO $$
BEGIN
    IF current_setting('pharmascan.rollback_target', true)
        IS DISTINCT FROM 'empty-temporary-test-database' THEN
        RAISE EXCEPTION 'Rollback refused: explicit empty temporary test database acknowledgement required';
    END IF;
    -- FORCE RLS 下普通角色可能看不见他人的数据，不允许这种角色做空库判定。
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = current_user AND (rolsuper OR rolbypassrls)
    ) THEN
        RAISE EXCEPTION 'Rollback refused: an administrative role that can inspect all RLS rows is required';
    END IF;
END;
$$;

-- 在判空前锁定全部目标表，避免判空后其他连接写入；不存在的表也会安全中止整个事务。
LOCK TABLE public.patient_profiles, public.medication_products, public.source_documents,
    public.source_fields, public.patient_medications, public.regimen_versions, public.dose_rules,
    public.dose_occurrences, public.dose_events, public.agent_sessions, public.confirmation_challenges,
    public.agent_tool_calls, public.audit_events IN ACCESS EXCLUSIVE MODE;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.patient_profiles WHERE demo_only IS DISTINCT FROM true
        UNION ALL SELECT 1 FROM public.medication_products WHERE demo_only IS DISTINCT FROM true
        UNION ALL SELECT 1 FROM public.source_documents WHERE demo_only IS DISTINCT FROM true OR is_synthetic IS DISTINCT FROM true
        UNION ALL SELECT 1 FROM public.source_fields WHERE demo_only IS DISTINCT FROM true
        UNION ALL SELECT 1 FROM public.patient_medications WHERE demo_only IS DISTINCT FROM true
        UNION ALL SELECT 1 FROM public.regimen_versions WHERE demo_only IS DISTINCT FROM true
        UNION ALL SELECT 1 FROM public.dose_rules WHERE demo_only IS DISTINCT FROM true
        UNION ALL SELECT 1 FROM public.dose_occurrences WHERE demo_only IS DISTINCT FROM true
        UNION ALL SELECT 1 FROM public.dose_events WHERE demo_only IS DISTINCT FROM true
        UNION ALL SELECT 1 FROM public.agent_sessions WHERE demo_only IS DISTINCT FROM true
        UNION ALL SELECT 1 FROM public.confirmation_challenges WHERE demo_only IS DISTINCT FROM true
        UNION ALL SELECT 1 FROM public.agent_tool_calls WHERE demo_only IS DISTINCT FROM true
        UNION ALL SELECT 1 FROM public.audit_events WHERE demo_only IS DISTINCT FROM true
    ) THEN
        RAISE EXCEPTION 'Rollback refused: non-demo or non-synthetic data exists';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.patient_profiles
        UNION ALL SELECT 1 FROM public.medication_products
        UNION ALL SELECT 1 FROM public.source_documents
        UNION ALL SELECT 1 FROM public.source_fields
        UNION ALL SELECT 1 FROM public.patient_medications
        UNION ALL SELECT 1 FROM public.regimen_versions
        UNION ALL SELECT 1 FROM public.dose_rules
        UNION ALL SELECT 1 FROM public.dose_occurrences
        UNION ALL SELECT 1 FROM public.dose_events
        UNION ALL SELECT 1 FROM public.agent_sessions
        UNION ALL SELECT 1 FROM public.confirmation_challenges
        UNION ALL SELECT 1 FROM public.agent_tool_calls
        UNION ALL SELECT 1 FROM public.audit_events
    ) THEN
        RAISE EXCEPTION 'Rollback refused: data exists, including synthetic/demo rows';
    END IF;
END;
$$;

-- 只在所有保护通过后解除本迁移的循环 FK，再按依赖逆序删除空表。
-- RESTRICT 保留外部依赖保护：若后续迁移依赖本切片，事务整体失败，必须另行设计回滚。
ALTER TABLE public.regimen_versions DROP CONSTRAINT regimen_versions_confirmation_fk RESTRICT;
DROP TABLE public.audit_events RESTRICT;
DROP TABLE public.agent_tool_calls RESTRICT;
DROP TABLE public.dose_events RESTRICT;
DROP TABLE public.confirmation_challenges RESTRICT;
DROP TABLE public.agent_sessions RESTRICT;
DROP TABLE public.dose_occurrences RESTRICT;
DROP TABLE public.dose_rules RESTRICT;
DROP TABLE public.regimen_versions RESTRICT;
DROP TABLE public.patient_medications RESTRICT;
DROP TABLE public.source_fields RESTRICT;
DROP TABLE public.source_documents RESTRICT;
DROP TABLE public.medication_products RESTRICT;
DROP TABLE public.patient_profiles RESTRICT;

DROP FUNCTION public.core_guard_tool_call() RESTRICT;
DROP FUNCTION public.core_reject_mutation() RESTRICT;
DROP FUNCTION public.core_guard_dose_event() RESTRICT;
DROP FUNCTION public.core_guard_occurrence() RESTRICT;
DROP FUNCTION public.core_guard_rule() RESTRICT;
DROP FUNCTION public.core_guard_medication_history() RESTRICT;
DROP FUNCTION public.core_guard_regimen() RESTRICT;
DROP FUNCTION public.core_guard_challenge() RESTRICT;
DROP FUNCTION public.core_consume_confirmation(uuid, uuid, text, uuid, uuid, text, text) RESTRICT;
DROP FUNCTION public.core_freeze_reviewed_source() RESTRICT;
DROP FUNCTION public.core_validate_timezone() RESTRICT;
DROP FUNCTION public.core_trace_summary_is_safe(jsonb) RESTRICT;
COMMIT;
