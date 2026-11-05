import { useEffect, useMemo, useRef, useState } from 'react';
import { api, type ObservationInput } from '../../../api/client';
import type { CareReview } from '../../../api/care';
import type {
  JsonValue,
  WorkflowEventHandler,
  WorkflowView,
} from '../../../api/assistantWorkflows';
import { useLanguage } from '../../../i18n/language';
import { CareReviewSheet, type CareReviewPatientPort } from '../../care/CareReviewSheet';
import { ObservationReviewSheet } from '../../care/ObservationReviewSheet';
import { AssistantCareFields } from './AssistantCareFields';
import { FollowUpError } from '../../care/FollowUpError';
import { careLabel } from '../../care/followUpCopy';

const reads = new Set(['observation.list', 'inventory.view', 'barrier.list', 'followup.list']);

function record(value: JsonValue | undefined): Record<string, JsonValue> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

export function AssistantCareActions({
  view,
  busy,
  onEvent,
  onDirtyChange,
  onClinicalChanged,
}: {
  view: WorkflowView;
  busy: boolean;
  onEvent: WorkflowEventHandler;
  onDirtyChange?: (value: boolean) => void;
  onClinicalChanged?: (() => void) | undefined;
}) {
  const { language, t } = useLanguage();
  const say = (en: string, zh: string) => (language === 'zh' ? zh : en);
  const [open, setOpen] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [uncertain, setUncertain] = useState(false);
  const callback = useRef(onDirtyChange);
  callback.current = onDirtyChange;
  const capability = view.capability_id;
  const review = record(view.visible_fields.care_review);
  const payload = record(review.payload);
  const target = typeof review.target_id === 'string' ? review.target_id : null;
  const input = payload as unknown as ObservationInput;
  const bound =
    view.save_mode === 'allowed' &&
    view.state === 'awaiting_confirmation' &&
    view.result_ref?.kind === 'care_review';
  const proposal = view.visible_fields.proposal as unknown as CareReview | undefined;
  const patient = useMemo<CareReviewPatientPort>(() => {
    const binding = { task_id: view.task_id, expected_revision: view.revision };
    return {
      save: async (proposed) => {
        if (capability === 'inventory.count' && proposed.stock && target)
          return api.recordStock(target, proposed.stock, binding);
        if (capability === 'barrier.add' && proposed.barrier)
          return api.recordBarrier(proposed.barrier, binding);
        if (capability === 'followup.add' && proposed.task)
          return api.createCareTask(proposed.task, binding);
        if (capability.startsWith('followup.') && proposed.task_update && target)
          return api.updateCareTask(target, proposed.task_update, binding);
        throw new Error('Reopen the selected patient care review.');
      },
    };
  }, [capability, target, view.task_id, view.revision]);
  useEffect(() => {
    callback.current?.(open || working);
    return () => callback.current?.(false);
  }, [open, working]);
  useEffect(() => {
    setOpen(false);
    setUncertain(false);
    setError(null);
  }, [view.revision]);

  async function readResult() {
    const result = await onEvent({
      event_id: crypto.randomUUID(),
      expected_revision: view.revision,
      kind: 'report_business_result',
      values: {},
    });
    if (!result || result.task_id !== view.task_id || result.revision <= view.revision)
      throw new Error('The actual care result is still unavailable.');
    setOpen(false);
    setUncertain(false);
    if (result.state === 'completed') onClinicalChanged?.();
  }

  async function confirmObservation() {
    if (working || uncertain || !bound) return;
    setWorking(true);
    setError(null);
    const binding = { task_id: view.task_id, expected_revision: view.revision };
    try {
      if (capability === 'observation.delete') {
        if (!target) throw new Error('Select the existing health note.');
        await api.deleteObservation(target, binding);
      } else await api.saveObservation({ ...input, confirmed: true }, binding);
      await readResult();
    } catch (caught) {
      setError(caught);
      setUncertain(true);
    } finally {
      setWorking(false);
    }
  }

  const when = (value: JsonValue | undefined) =>
    typeof value === 'string' && Number.isFinite(Date.parse(value))
      ? new Date(value).toLocaleString(language === 'zh' ? 'zh-CN' : 'en-SG', {
          timeZone:
            typeof view.visible_fields.timezone === 'string'
              ? view.visible_fields.timezone
              : 'Asia/Singapore',
        })
      : '';
  const rows = Array.isArray(view.visible_fields.records)
    ? view.visible_fields.records.map(record)
    : [];
  const stock = record(view.visible_fields.stock);
  const page = Number(view.visible_fields.page ?? 0);
  const pages = Number(view.visible_fields.page_count ?? 1);
  const pageTo = (number: number) =>
    onEvent({
      event_id: crypto.randomUUID(),
      expected_revision: view.revision,
      kind: 'provide_fields',
      values: { page: number },
    });
  if (reads.has(capability))
    return (
      <div>
        {capability === 'observation.list' ? (
          <p>
            {say(
              `Past ${String(view.visible_fields.days ?? 30)} days`,
              `过去 ${String(view.visible_fields.days ?? 30)} 天`,
            )}{' '}
            · {String(view.visible_fields.timezone ?? 'Asia/Singapore')}
          </p>
        ) : null}
        {capability === 'inventory.view' && Object.keys(stock).length ? (
          <>
            <h3>
              {String(
                view.visible_fields.medication_name ??
                  say('Medication inventory', '\u836f\u7269\u5e93\u5b58'),
              )}
            </h3>
            <p>
              {say('Last confirmed physical count', '上次确认的实物盘点')}:{' '}
              {String(stock.last_confirmed_stock ?? t('Unknown'))} {t(String(stock.unit ?? ''))}
            </p>
            <p>
              {say('Estimated remaining', '估算剩余')}:{' '}
              {String(stock.estimated_remaining ?? t('Unknown'))} {t(String(stock.unit ?? ''))}
            </p>
            <p>
              {say(
                'Estimates use confirmed counts and compatible patient reports. Unreported consumption is unknown.',
                '估算来自确认盘点及兼容的患者自述，未报告的消耗情况未知。',
              )}
            </p>
          </>
        ) : null}
        {rows.length ? (
          <ul>
            {rows.map((row, index) => (
              <li key={String(row.id ?? index)}>
                <strong>
                  {String(
                    row.title ?? row.description ?? t(String(row.category ?? row.kind ?? '')),
                  )}
                </strong>
                <p>
                  {when(row.occurred_at ?? row.due_at ?? row.recorded_at)}{' '}
                  {row.status ? careLabel(String(row.status), language, t) : ''}
                </p>
                {row.quantity !== undefined ? (
                  <p>
                    {String(row.quantity)} {t(String(row.unit ?? ''))}
                  </p>
                ) : null}
                {row.value !== undefined && row.value !== null ? (
                  <p>
                    {String(row.value)}
                    {row.secondary_value !== null && row.secondary_value !== undefined
                      ? ` / ${row.secondary_value}`
                      : ''}{' '}
                    {String(row.unit ?? '')}
                  </p>
                ) : null}
                {row.chosen_action ? <p>{String(row.chosen_action)}</p> : null}
                {row.notes ? <p>{String(row.notes)}</p> : null}
              </li>
            ))}
          </ul>
        ) : (
          <p>{say('No records in this view.', '本次查询没有记录。')}</p>
        )}
        {view.visible_fields.total !== undefined ? (
          <p>
            {say('Recorded entries', '已记录条目')}: {String(view.visible_fields.total)} ·{' '}
            {page + 1}/{pages}
          </p>
        ) : null}
        {page > 0 ? (
          <button disabled={busy} onClick={() => void pageTo(page - 1)}>
            {say('Previous page', '上一页')}
          </button>
        ) : null}
        {page + 1 < pages ? (
          <button disabled={busy} onClick={() => void pageTo(page + 1)}>
            {say('Next page', '下一页')}
          </button>
        ) : null}
      </div>
    );
  if (view.state === 'completed' && view.visible_fields.historical_result === true)
    return (
      <p>
        {say(
          'The earlier operation succeeded. The health note has since changed or is no longer available.',
          '此前操作已成功，健康观察记录后来已变更或当前不可用。',
        )}
      </p>
    );
  if (view.state === 'completed')
    return <p>{say('The actual patient record was checked.', '已核查实际保存的患者记录。')}</p>;
  if (view.state === 'suspended' || view.state === 'cancelled') return null;
  if (bound && view.prompt_key === 'assistant.care.check_result')
    return (
      <button disabled={busy} onClick={() => void readResult().catch(setError)}>
        {say('Check care result', '\u6838\u67e5\u5173\u6000\u8bb0\u5f55\u7ed3\u679c')}
      </button>
    );
  if (bound)
    return (
      <div>
        <button type="button" disabled={busy} onClick={() => setOpen(true)}>
          {say('Review care record', '核对关怀记录')}
        </button>
        {open && capability.startsWith('observation.') ? (
          <ObservationReviewSheet
            linkedLabel={
              typeof view.visible_fields.target_name === 'string'
                ? view.visible_fields.target_name
                : undefined
            }
            deleting={capability === 'observation.delete'}
            record={
              capability === 'observation.delete'
                ? { description: String(record(view.visible_fields.observation).description ?? '') }
                : input
            }
            busy={working || uncertain}
            onConfirm={() => void confirmObservation()}
            onCancel={() => setOpen(false)}
          >
            {error ? <FollowUpError error={error} /> : null}
            {uncertain ? (
              <button disabled={working} onClick={() => void readResult().catch(setError)}>
                {say('Check care result', '核查关怀记录结果')}
              </button>
            ) : null}
          </ObservationReviewSheet>
        ) : null}
        {open && proposal ? (
          <CareReviewSheet
            associationLabel={
              typeof view.visible_fields.association_label === 'string'
                ? view.visible_fields.association_label
                : undefined
            }
            associationState={
              typeof view.visible_fields.association_state === 'string'
                ? view.visible_fields.association_state
                : undefined
            }
            targetLabel={
              typeof view.visible_fields.target_name === 'string'
                ? view.visible_fields.target_name
                : undefined
            }
            proposal={proposal}
            patient={patient}
            readOnlyFields
            onCancel={() => setOpen(false)}
            onSaved={readResult}
            onCheckResult={readResult}
          />
        ) : null}
      </div>
    );
  return (
    <AssistantCareFields
      key={`${view.task_id}:${view.revision}`}
      view={view}
      busy={busy}
      onEvent={onEvent}
      onDirtyChange={onDirtyChange}
    />
  );
}
