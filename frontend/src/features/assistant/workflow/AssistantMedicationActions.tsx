import { useEffect, useRef, useState } from 'react';
import type {
  JsonValue,
  WorkflowView,
  WorkflowEventHandler,
} from '../../../api/assistantWorkflows';
import { api } from '../../../api/client';
import { useLanguage } from '../../../i18n/language';
import { StopPlanReview } from '../../medications/StopPlanReview';
import { DeleteDraftReview } from '../../enrollment/DeleteDraftReview';
import { ErrorNotice } from '../../../components/primitives';

function object(value: JsonValue | undefined): Record<string, JsonValue> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function rows(value: JsonValue | undefined) {
  return Array.isArray(value) ? value.map(object) : [];
}

function text(value: JsonValue | undefined) {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : '';
}

/** Display owned records and reuse independent patient confirmation for maintenance. */
export function AssistantMedicationActions({
  view,
  busy = false,
  onEvent,
  onClinicalChanged,
  onRefresh,
}: {
  view: WorkflowView;
  busy?: boolean;
  onEvent?: WorkflowEventHandler;
  onClinicalChanged?: (() => void) | undefined;
  onRefresh?: (() => void) | undefined;
}) {
  const { language, t } = useLanguage();
  const say = (en: string, zh: string) => (language === 'zh' ? zh : en);
  const [confirming, setConfirming] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const live = useRef(true);
  const latest = useRef(view);
  latest.current = view;
  const deleting = useRef(false);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);
  useEffect(() => {
    setConfirming(false);
    setError(null);
  }, [view.task_id, view.revision, view.save_mode, view.state]);
  const stopAction = view.actions.find(
    (action) =>
      action.kind === 'existing_review' &&
      action.component_key === 'existing_plan_end' &&
      action.owned_ref.kind === 'regimen' &&
      action.owned_ref.id === view.result_ref?.id &&
      action.expected_version === view.result_ref?.version,
  );
  const deleteAction = view.actions.find(
    (action) =>
      action.kind === 'existing_review' &&
      action.component_key === 'existing_draft_delete' &&
      action.owned_ref.id === view.result_ref?.id &&
      action.owned_ref.kind === view.result_ref?.kind &&
      action.expected_version === view.result_ref?.version,
  );
  const deleteImpact =
    typeof view.visible_fields.affected_plan_count === 'number' &&
    typeof view.visible_fields.affected_source_registration_count === 'number'
      ? {
          plans: view.visible_fields.affected_plan_count,
          sources: view.visible_fields.affected_source_registration_count,
          wholeMedication: view.visible_fields.medication_record_removed === true,
        }
      : undefined;

  async function confirmDelete() {
    if (
      !onEvent ||
      deleting.current ||
      working ||
      busy ||
      !deleteAction ||
      deleteAction.kind !== 'existing_review' ||
      view.capability_id !== 'medication.draft.delete' ||
      view.save_mode !== 'allowed' ||
      view.state !== 'awaiting_confirmation'
    )
      return;
    const ref = deleteAction.owned_ref;
    const kind =
      ref.kind === 'regimen' ? 'draft' : ref.kind === 'enrollment_task' ? 'source' : null;
    if (!kind || view.visible_fields.kind !== kind || view.visible_fields.target_id !== ref.id)
      return;
    const task = view.task_id;
    const revision = view.revision;
    deleting.current = true;
    setWorking(true);
    setError(null);
    const current = () =>
      live.current &&
      latest.current.task_id === task &&
      latest.current.revision === revision &&
      latest.current.state === view.state &&
      latest.current.save_mode === 'allowed';
    try {
      const result = await api.deleteDraft(kind, ref.id, {
        task_id: task,
        expected_revision: revision,
      });
      if (!current()) return;
      if (result.deleted !== true)
        throw new Error(
          say(
            'The deletion result is unconfirmed. Check task status.',
            '尚未确认删除结果，请核查办理状态。',
          ),
        );
      onClinicalChanged?.();
      await onEvent({
        event_id: crypto.randomUUID(),
        expected_revision: revision,
        kind: 'report_business_result',
        values: {},
      });
      if (current()) setConfirming(false);
    } catch (caught) {
      if (current()) setError(caught);
    } finally {
      deleting.current = false;
      if (live.current) setWorking(false);
    }
  }

  async function confirmStop() {
    if (
      !onEvent ||
      working ||
      busy ||
      !stopAction ||
      stopAction.kind !== 'existing_review' ||
      view.capability_id !== 'medication.plan.end' ||
      view.save_mode !== 'allowed'
    )
      return;
    const task = view.task_id;
    const revision = view.revision;
    setWorking(true);
    setError(null);
    const current = () =>
      live.current &&
      latest.current.task_id === task &&
      latest.current.revision === revision &&
      latest.current.save_mode === 'allowed';
    try {
      const result = await api.endPlan(stopAction.owned_ref.id, {
        task_id: task,
        expected_revision: revision,
      });
      if (!current()) return;
      if (result.regimen_id !== stopAction.owned_ref.id || result.state !== 'ended')
        throw new Error(
          say(
            'The stop result is unconfirmed. Check the current record.',
            '尚未确认停止结果，请核查当前记录。',
          ),
        );
      onClinicalChanged?.();
      await onEvent({
        event_id: crypto.randomUUID(),
        expected_revision: revision,
        kind: 'report_business_result',
        values: {},
      });
      if (current()) setConfirming(false);
    } catch (caught) {
      if (current()) setError(caught);
    } finally {
      if (live.current) setWorking(false);
    }
  }

  if (!Array.isArray(view.visible_fields.records)) return null;
  const records = rows(view.visible_fields.records);
  const sources = rows(view.visible_fields.source_tasks);
  const statuses: Record<string, string> = {
    draft: say('Draft', '草稿'),
    pending_clarification: say('Needs clarification', '待补充资料'),
    active: say('Active', '已启用'),
    ended: say('Ended', '已结束'),
  };

  function schedule(plan: Record<string, JsonValue>) {
    if (plan.is_prn === true) return say('As needed', '按需服用');
    const rule = object(plan.frequency_rule);
    const times = Array.isArray(rule.local_times) ? rule.local_times.map(text).join(', ') : '';
    if (rule.kind === 'interval')
      return `${say('Hours between doses', '每隔几小时')}: ${text(rule.every_hours)} · ${object(rule.interval_anchor).time_source === 'default_0800' ? say('Default 08:00', '默认08:00') : times}`;
    if (rule.kind === 'weekly')
      return `${say('Weekly', '每周')} ${Array.isArray(rule.days_of_week) ? rule.days_of_week.map(text).join(', ') : ''} · ${times}`;
    return `${rule.kind === 'daily' ? say('Daily', '每日') : say('Schedule not recorded', '未记录频率')} ${times}`;
  }

  return (
    <div className="assistant-medication-results">
      <h3>
        {view.capability_id === 'medication.draft.delete'
          ? t('Delete draft')
          : view.capability_id === 'medication.setup.list'
            ? say('Unfinished medication setup', '未完成的药物登记')
            : say('Saved medication plans', '已保存的用药计划')}
      </h3>
      {records.map((record) => (
        <article key={text(record.medication_id)}>
          <h4>{text(record.display_name)}</h4>
          {rows(record.plans).map((plan) => (
            <dl key={text(plan.regimen_id)}>
              <div>
                <dt>{say('Plan state', '计划状态')}</dt>
                <dd>
                  {statuses[text(plan.state)] ?? say('Check current record', '请核查当前记录')}
                </dd>
              </div>
              <div>
                <dt>{say('Version', '版本')}</dt>
                <dd>{text(plan.version_no)}</dd>
              </div>
              <div>
                <dt>{say('Amount per dose', '每次用量')}</dt>
                <dd>
                  {text(plan.dose_amount) || say('Not recorded', '未记录')}{' '}
                  {t(text(plan.dose_unit))}
                </dd>
              </div>
              <div>
                <dt>{say('Schedule', '服用频率')}</dt>
                <dd>{schedule(plan)}</dd>
              </div>
              {plan.course_start_date || plan.course_end_date ? (
                <div>
                  <dt>{say('Course', '疗程')}</dt>
                  <dd>
                    {text(plan.course_start_date)} → {text(plan.course_end_date)}
                  </dd>
                </div>
              ) : null}
              {plan.food_instruction ? (
                <div>
                  <dt>{say('Recorded instructions', '已记录的说明')}</dt>
                  <dd>{text(plan.food_instruction)}</dd>
                </div>
              ) : null}
            </dl>
          ))}
        </article>
      ))}
      {sources.map((source) => (
        <p key={text(source.task_id)}>
          {text(source.display_name)} {text(source.strength)} ·{' '}
          {source.conflicting === true
            ? say('Sources need clarification', '来源有待澄清')
            : say('Supplement medication information', '待补充药物资料')}
        </p>
      ))}
      {!records.length && !sources.length && view.capability_id !== 'medication.draft.delete' ? (
        <p>{say('No matching saved records.', '没有符合条件的已保存记录。')}</p>
      ) : null}
      {typeof view.visible_fields.page_count === 'number' && view.visible_fields.page_count > 1 ? (
        <p>
          {say('Page', '页码')} {Number(view.visible_fields.page) + 1} /{' '}
          {view.visible_fields.page_count}
        </p>
      ) : null}
      {view.capability_id === 'medication.plan.end' &&
      view.state === 'ready_for_review' &&
      view.save_mode === 'allowed' ? (
        <button
          disabled={busy || working || !onEvent}
          onClick={() =>
            onEvent?.({
              event_id: crypto.randomUUID(),
              expected_revision: view.revision,
              kind: 'prepare_confirmation',
              values: {},
            })
          }
        >
          {say('Review stopping this plan', '核对停止追踪此计划')}
        </button>
      ) : null}
      {view.capability_id === 'medication.plan.end' &&
      view.state === 'awaiting_confirmation' &&
      view.save_mode === 'allowed' &&
      stopAction ? (
        <button
          className="danger"
          disabled={busy || working || !onEvent}
          onClick={() => {
            setError(null);
            setConfirming(true);
          }}
        >
          {t('Stop tracking this regimen')}
        </button>
      ) : null}
      {confirming &&
      view.capability_id === 'medication.plan.end' &&
      view.save_mode === 'allowed' &&
      view.state === 'awaiting_confirmation' ? (
        <StopPlanReview
          busy={busy || working}
          error={error}
          onCancel={() => setConfirming(false)}
          onConfirm={() => void confirmStop()}
        />
      ) : null}
      {view.capability_id === 'medication.draft.delete' &&
      view.state === 'ready_for_review' &&
      view.save_mode === 'allowed' ? (
        <button
          disabled={busy || working || !onEvent}
          onClick={() =>
            onEvent?.({
              event_id: crypto.randomUUID(),
              expected_revision: view.revision,
              kind: 'prepare_confirmation',
              values: {},
            })
          }
        >
          {say('Review deleting this draft', '核对删除这份草稿')}
        </button>
      ) : null}
      {view.capability_id === 'medication.draft.delete' &&
      view.state === 'awaiting_confirmation' &&
      view.save_mode === 'allowed' &&
      deleteAction ? (
        view.visible_fields.deleted === true && view.visible_fields.cleanup_pending === true ? (
          <button disabled={busy || working || !onEvent} onClick={() => void confirmDelete()}>
            {t('Retry photo cleanup')}
          </button>
        ) : (
          <button
            className="danger"
            disabled={busy || working || !onEvent}
            onClick={() => {
              setError(null);
              setConfirming(true);
            }}
          >
            {t('Delete draft')}
          </button>
        )
      ) : null}
      {view.capability_id === 'medication.draft.delete' &&
      view.state === 'failed_recoverable' &&
      view.save_mode === 'allowed' ? (
        <button
          disabled={busy || working || !onEvent}
          onClick={() =>
            onEvent?.({
              event_id: crypto.randomUUID(),
              expected_revision: view.revision,
              kind: 'provide_fields',
              values: {},
            })
          }
        >
          {say('Recheck draft before deleting', '重新核对草稿后删除')}
        </button>
      ) : null}
      {confirming &&
      view.capability_id === 'medication.draft.delete' &&
      view.save_mode === 'allowed' &&
      view.state === 'awaiting_confirmation' ? (
        <DeleteDraftReview
          name={text(view.visible_fields.target_name)}
          busy={busy || working}
          error={error}
          impact={deleteImpact}
          onCancel={() => setConfirming(false)}
          onConfirm={() => void confirmDelete()}
          onCheckResult={onRefresh}
        />
      ) : null}
      {error && !confirming && view.capability_id === 'medication.draft.delete' ? (
        <ErrorNotice error={error} />
      ) : null}
    </div>
  );
}
