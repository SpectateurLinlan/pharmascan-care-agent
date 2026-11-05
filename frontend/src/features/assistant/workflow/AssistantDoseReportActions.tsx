import { useEffect, useRef, useState } from 'react';
import { api, type DueDoseResponse, type ReportChallengeResponse } from '../../../api/client';
import type { WorkflowEventHandler, WorkflowView } from '../../../api/assistantWorkflows';
import { useLanguage } from '../../../i18n/language';
import { ConfirmReportSheet } from '../../today/ConfirmReportSheet';

type Operation = { choice: string; key: string; occurrence: string | null };

/** Uses the normal patient protocol. The workflow never receives its token. */
export function AssistantDoseReportActions({
  view,
  busy,
  onEvent,
  onDirtyChange,
  onClinicalChanged,
}: {
  view: WorkflowView;
  busy: boolean;
  onEvent: WorkflowEventHandler;
  onDirtyChange?: (dirty: boolean) => void;
  onClinicalChanged?: (() => void) | undefined;
}) {
  const { language, t } = useLanguage();
  const say = (en: string, zh: string) => (language === 'zh' ? zh : en);
  const target = view.visible_fields.report_target;
  const ref = view.result_ref;
  const record = target && typeof target === 'object' && !Array.isArray(target) ? target : {};
  const id = typeof record.regimen_id === 'string' ? record.regimen_id : null;
  const prn = record.is_prn === true;
  const version = typeof record.version === 'number' ? record.version : 0;
  const [due, setDue] = useState<DueDoseResponse | null>(null);
  const [loading, setLoading] = useState(!prn);
  const [retry, setRetry] = useState(0);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [confirmation, setConfirmation] = useState<ReportChallengeResponse | null>(null);
  const [operation, setOperation] = useState<Operation | null>(null);
  const operationRef = useRef<Operation | null>(null);
  const sending = useRef(false);
  const live = useRef(true);
  const revision = useRef(view.revision);
  const callback = useRef(onDirtyChange);
  callback.current = onDirtyChange;
  const eligible =
    view.save_mode === 'allowed' &&
    view.state === 'awaiting_confirmation' &&
    id !== null &&
    ref?.kind === 'regimen' &&
    ref.id === id &&
    ref.version === version;
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
      callback.current?.(false);
    };
  }, []);
  useEffect(() => {
    onDirtyChange?.(working || confirmation !== null || uncertain);
  }, [working, confirmation, uncertain, onDirtyChange]);
  useEffect(() => {
    if (revision.current !== view.revision) {
      revision.current = view.revision;
      operationRef.current = null;
      setOperation(null);
      setConfirmation(null);
      setUncertain(false);
      setError(false);
    }
  }, [view.revision]);
  useEffect(() => {
    if (!eligible || prn || !id) return;
    let active = true;
    setLoading(true);
    void Promise.resolve().then(() => {
      if (!active) return;
      return api
        .dueDose(id, true)
        .then((row) => {
          if (!active) return;
          if (row.regimen_id !== id || row.is_prn) throw new Error('Report target changed');
          setDue(row);
          setError(false);
        })
        .catch(() => {
          if (active) setError(true);
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    });
    return () => {
      active = false;
    };
  }, [eligible, prn, id, retry]);
  if (!eligible) return null;
  const binding = { task_id: view.task_id, expected_revision: view.revision };
  const blocked = busy || working || loading;

  async function readResult() {
    if (sending.current || busy) return;
    sending.current = true;
    setWorking(true);
    try {
      const result = await onEvent({
        event_id: crypto.randomUUID(),
        expected_revision: view.revision,
        kind: 'report_business_result',
        values: {},
      });
      if (!live.current) return;
      if (result?.task_id === view.task_id && result.revision > view.revision) {
        operationRef.current = null;
        setOperation(null);
        setConfirmation(null);
        setUncertain(false);
        setError(false);
        if (result.state === 'completed') onClinicalChanged?.();
      } else setError(true);
    } catch {
      if (live.current) setError(true);
    } finally {
      sending.current = false;
      if (live.current) setWorking(false);
    }
  }

  async function choose(choice: string) {
    if (blocked || uncertain || sending.current || !id) return;
    const occurrence = prn ? null : (due?.occurrence_id ?? null);
    if (!prn && !occurrence) {
      setError(true);
      return;
    }
    const previous = operationRef.current;
    const input =
      previous && previous.choice === choice && previous.occurrence === occurrence
        ? previous
        : { choice, occurrence, key: `report-${crypto.randomUUID()}` };
    operationRef.current = input;
    setOperation(input);
    sending.current = true;
    setWorking(true);
    setError(false);
    try {
      const payload = { regimen_id: id, intake_status: choice, idempotency_key: input.key };
      const summary = prn
        ? await api.requestPrnReportChallenge(payload, binding)
        : await api.requestReportChallenge(occurrence!, payload, binding);
      if (!live.current) return;
      const expected =
        choice === 'Taken'
          ? 'reported_taken'
          : choice === 'Not now'
            ? 'reported_not_taken'
            : 'unsure';
      if (
        summary.regimen_id !== id ||
        summary.occurrence_id !== occurrence ||
        summary.summary.regimen_version_no !== version ||
        summary.summary.intake_status !== expected ||
        summary.summary.ingestion_proven !== false
      )
        throw new Error('Patient summary changed');
      if (summary.already_recorded) {
        setUncertain(true);
        setError(false);
        return;
      }
      if (
        !summary.challenge_id ||
        !summary.expires_at ||
        !Number.isFinite(Date.parse(summary.expires_at)) ||
        Date.parse(summary.expires_at) <= Date.now()
      )
        throw new Error('Patient summary expired');
      setConfirmation(summary);
    } catch {
      if (live.current) setError(true);
    } finally {
      sending.current = false;
      if (live.current) setWorking(false);
    }
  }

  async function confirm() {
    if (blocked || uncertain || sending.current || !confirmation?.challenge_id || !operation || !id)
      return;
    if (!confirmation.expires_at || Date.parse(confirmation.expires_at) <= Date.now()) {
      setError(true);
      setUncertain(true);
      return;
    }
    sending.current = true;
    setWorking(true);
    setError(false);
    try {
      const payload = {
        regimen_id: id,
        intake_status: operation.choice,
        idempotency_key: operation.key,
        challenge_id: confirmation.challenge_id,
      };
      const result = prn
        ? await api.submitPrnReport(payload, binding)
        : await api.submitReport(operation.occurrence!, payload, binding);
      if (!live.current) return;
      if (!result.event_id || result.ingestion_proven !== false)
        throw new Error('Report result requires checking');
      setConfirmation(null);
      setUncertain(true);
      const latest = await onEvent({
        event_id: crypto.randomUUID(),
        expected_revision: view.revision,
        kind: 'report_business_result',
        values: {},
      });
      if (live.current && latest?.state === 'completed' && latest.task_id === view.task_id) {
        setUncertain(false);
        onClinicalChanged?.();
      }
    } catch {
      if (live.current) {
        setUncertain(true);
        setError(true);
      }
    } finally {
      sending.current = false;
      if (live.current) setWorking(false);
    }
  }

  const statusCheck = (
    <button type="button" disabled={busy || working} onClick={() => void readResult()}>
      {say('Check report result', '核查自述结果')}
    </button>
  );
  return (
    <div role="region" aria-label={say('Patient dose report', '患者服药自述')}>
      <h3>
        {typeof record.medication_name === 'string'
          ? record.medication_name
          : say('Selected recorded medicine', '所选登记药物')}
      </h3>
      <p>
        {String(record.dose_amount ?? '')}{' '}
        {t(typeof record.dose_unit === 'string' ? record.dose_unit : '')} · v{version}
      </p>
      <p>
        {say(
          'Choose what you want to report. You will review a separate confirmation before it is saved.',
          '请选择您要自述的情况，保存前还需核对并单独确认。',
        )}
      </p>
      {loading ? (
        <p role="status">{say('Reading the current scheduled dose…', '正在读取当前登记剂次…')}</p>
      ) : null}
      {!prn && !loading && !due?.occurrence_id ? (
        <p>
          {say(
            'No current scheduled dose is available for this report.',
            '本次自述没有可用的当前登记剂次。',
          )}
        </p>
      ) : null}
      {error ? (
        <p role="status">
          {uncertain
            ? say(
                'The report result needs checking. Check its status before starting another report.',
                '自述结果仍需核查，请先确认结果，再发起新的自述。',
              )
            : say(
                'The summary could not be loaded. Your choice is retained; retry it or check the current task.',
                '暂时无法读取核对摘要，已保留您的选择，请重试或核查当前任务。',
              )}
        </p>
      ) : null}
      {!uncertain ? (
        <div className="actions">
          {[
            ['Taken', 'Taken'],
            ['Not now', 'Not now'],
            ['Unsure', 'Unsure'],
          ].map(([choice, label]) => (
            <button
              key={choice}
              type="button"
              disabled={blocked || (!prn && !due?.occurrence_id)}
              onClick={() => void choose(choice!)}
            >
              {t(label!)}
            </button>
          ))}
        </div>
      ) : !confirmation ? (
        statusCheck
      ) : null}
      {!prn && error && !uncertain ? (
        <button disabled={blocked} onClick={() => setRetry((value) => value + 1)}>
          {say('Retry dose lookup', '重新读取剂次')}
        </button>
      ) : null}
      {confirmation ? (
        <ConfirmReportSheet
          summary={confirmation.summary}
          busy={blocked || uncertain}
          onConfirm={() => void confirm()}
          onCancel={() => {
            setConfirmation(null);
            operationRef.current = null;
            setOperation(null);
            setError(false);
          }}
        >
          {uncertain ? statusCheck : null}
        </ConfirmReportSheet>
      ) : null}
    </div>
  );
}
