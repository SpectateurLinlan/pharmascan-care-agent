import { useLanguage } from '../language';
/**
 * Today screen: the currently due dose and the four patient choices
 * [Taken] [Not now] [Unsure], with independent confirmation.
 * The primary visual CTA opens the read-only photo evidence flow separately.
 */

import { useEffect, useId, useState } from 'react';
import {
  api,
  type DoseHistoryResponse,
  type DueDoseResponse,
  type MedicationSummary,
  type ReportChallengeResponse,
} from '../api/client';
import {
  createBrowserReminderPort,
  REMINDER_LIMITATION,
  type ReminderPort,
  type ReminderSupport,
} from '../reminders';
import {CompactDoseCard} from './CompactDoseCard';
import {ConfirmReportSheet} from './ConfirmReportSheet';
import { Card, ErrorNotice, Tag } from './primitives';

const CHOICES: { label: string; value: string }[] = [
  { label: 'Taken', value: 'Taken' },
  { label: 'Not now', value: 'Not now' },
  { label: 'Unsure', value: 'Unsure' },
];

/** How long past its scheduled time a dose is described as overdue. */
const OVERDUE_GRACE_MS = 30 * 60 * 1000;

/**
 * Describe a due occurrence in plain language. A dose that is due but has no
 * report is never described as missed — only as "due" or "overdue in your
 * record", because absence of a report is not evidence of a missed dose.
 */
export function describeDueStatus(
  dueAt: string | null,
  now: Date = new Date(),
): { label: string; overdue: boolean } {
  if (!dueAt) {
    return { label: 'due now', overdue: false };
  }
  const moment = new Date(dueAt).getTime();
  if (Number.isNaN(moment)) {
    return { label: 'due now', overdue: false };
  }
  if (now.getTime() - moment > OVERDUE_GRACE_MS) {
    return { label: 'overdue in your record', overdue: true };
  }
  return { label: 'due now', overdue: false };
}

export function TodayScreen({
  medications,
  onChanged, onFeeling,
  reminderPort, compact = false, onMedicines, onReviewPlan, hasMedicationRecords=false, setupCount=0, onVisualCheck, focusRegimenId, showTitle = true, onInteractionChange,
}: {
  medications: MedicationSummary[];
  onChanged: () => void; onFeeling?:()=>void;
  focusRegimenId?: string|null;
  showTitle?:boolean;
  onInteractionChange?:(regimen:string,locked:boolean)=>void;
  onVisualCheck?: (regimenId:string|null) => void; reminderPort?: ReminderPort; compact?: boolean; onMedicines?: () => void; onReviewPlan?:()=>void; hasMedicationRecords?:boolean; setupCount?:number;
}) {
  const {language,t}=useLanguage();
  const selectorId=useId();
  const [reminderDue, setReminderDue] = useState(false);
  const [reminderAt, setReminderAt] = useState<string | null>(null);
  const [showSnooze, setShowSnooze] = useState(false);
  const [selected, setSelected] = useState<MedicationSummary | null>(null);
  const [due, setDue] = useState<DueDoseResponse | null>(null);
  const [history, setHistory] = useState<DoseHistoryResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [lastResult, setLastResult] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<{
    challenge: ReportChallengeResponse; occurrenceId: string | null; choice: string; key: string;
  } | null>(null);
  const [reminderPermission, setReminderPermission] = useState<ReminderSupport>('default');
  useEffect(()=>{if(!selected)return;onInteractionChange?.(selected.regimen_id,busy||confirmation!==null);return()=>onInteractionChange?.(selected.regimen_id,false);},[selected,busy,confirmation,onInteractionChange]);

  const reminders: ReminderPort =
    reminderPort ??
    (typeof window !== 'undefined' && 'Notification' in window
      ? createBrowserReminderPort()
      : { kind: 'noop', support: () => 'unsupported', requestPermission: async () => 'unsupported', notify: async () => false });

  useEffect(() => {
    setReminderPermission(reminders.support());
    // Only the initial permission read; never request here.
  }, [reminders]);

  useEffect(() => {
    if (medications.length > 0 && (!selected || !medications.some(row => row.regimen_id === selected.regimen_id))) {
      setSelected(medications[0] ?? null);
    }
  }, [medications, selected]);

  useEffect(()=>{const found=medications.find(row=>row.regimen_id===focusRegimenId);if(found){setSelected(found);setDue(null);}},[focusRegimenId,medications]);

  useEffect(() => {
    if (!compact || !selected) return;
    let live = true;

    const refresh = () => { if (document.visibilityState === 'hidden') return;
      void api.dueDose(selected.regimen_id,true).then(value => { if (live) {setDue(value);setError(null);} }).catch(caught => { if (live) setError(caught); });
    };
    refresh(); const poll=setInterval(refresh,15000); document.addEventListener('visibilitychange',refresh);
    return () => { live = false; clearInterval(poll); document.removeEventListener('visibilitychange',refresh); };
  }, [compact, selected, medications]);

  useEffect(() => {
    if (!compact || !due?.occurrence_id) { setReminderAt(null); return; }
    let live = true;
    const occurrenceId = due.occurrence_id;
    const refresh = () => { if(document.visibilityState === 'hidden') return;
      void api.reminders().then(rows => { if(live) { const row=rows.find(value => value.occurrence_id===occurrenceId); setReminderAt(row?.remind_at ?? null); setReminderDue(row?.is_due ?? false); } }).catch(() => { if(live) {setReminderAt(null);setReminderDue(false);} });
    };
    refresh(); const poll=setInterval(refresh,15000); document.addEventListener('visibilitychange',refresh);
    return () => { live = false; clearInterval(poll); document.removeEventListener('visibilitychange',refresh); };
  }, [compact, due?.occurrence_id]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(false);
    }
  }

  const loadFor = (medication: MedicationSummary) =>
    run(async () => {
      setSelected(medication);
      setLastResult(null);
      const [dueDose,history]=await Promise.all([api.dueDose(medication.regimen_id),api.doseHistory(medication.regimen_id)]);
      setDue(dueDose);setHistory(history);
    });

  const report = (choice: string) =>
    run(async () => {
      if (!due || (!due.occurrence_id && !due.is_prn)) {
        throw new Error('No dose is currently due for this medication.');
      }
      // Two-phase confirmation flow: the database requires every dose event to
      // cite a confirmed, unconsumed ``record_self_report`` challenge, so the
      // UI issues the challenge (showing the patient what will be recorded) and
      // then confirms it in a second request.
      const key = `report-${crypto.randomUUID()}`;
      const payload = {
        regimen_id: due.regimen_id,
        intake_status: choice,
        idempotency_key: key,
      };
      const challenge = due.occurrence_id ? await api.requestReportChallenge(due.occurrence_id, payload)
        : await api.requestPrnReportChallenge(payload);
      if (challenge.already_recorded) {
        setLastResult(
          'Your report was already saved. Nothing changed.',
        );
        onChanged();
        if (selected) {
          setHistory(await api.doseHistory(selected.regimen_id));
        }
        return;
      }
      if (!challenge.challenge_id) {
        throw new Error('The server did not issue a confirmation challenge.');
      }
      setConfirmation({ challenge, occurrenceId: due.occurrence_id, choice, key });
    });

  const confirmReport = () =>
    run(async () => {
      if (!confirmation?.challenge.challenge_id) return;
      const { challenge, occurrenceId, choice, key } = confirmation;
      const payload = {
        regimen_id: challenge.regimen_id,
        intake_status: choice,
        idempotency_key: key,
        challenge_id: challenge.challenge_id!,
      };
      const result = occurrenceId ? await api.submitReport(occurrenceId, payload) : await api.submitPrnReport(payload);
      setConfirmation(null);
      setLastResult(
        result.already_recorded
          ? 'Your report was already saved. Nothing changed.'
          : 'Your report was saved.',
      );
      onChanged();
      if (selected) {
        setHistory(await api.doseHistory(selected.regimen_id));
      }
    });

  const renderConfirmation=()=>confirmation?<ConfirmReportSheet summary={confirmation.challenge.summary} busy={busy} onConfirm={()=>void confirmReport()} onCancel={()=>setConfirmation(null)}/>:null;

  if (medications.length === 0) {
    return (
      <Card title={compact ? "Today's medication" : "Today"}>
        <p className="notice">{t(setupCount>0?'A medication plan needs review.':hasMedicationRecords?'No current medication plans.':'No medication plans have been added.')}</p>
        {compact ? <nav className="today-medication-shortcuts" aria-label={t('Medication management shortcuts')}>
          {setupCount>0?<button className="primary dominant" type="button" onClick={onReviewPlan}>{t('Review medication plan')}</button>:!hasMedicationRecords?<button className="primary dominant" type="button" onClick={onMedicines}>{t('Add your medication')}</button>:null}
          {onMedicines?<button className="text-button" type="button" onClick={onMedicines}>{t('My Medicines')}</button>:null}
          {onVisualCheck?<button className="text-button" type="button" onClick={()=>onVisualCheck(null)}>{t('Compare a pill photo')}</button>:null}
        </nav> : null}
      </Card>
    );
  }

  if(compact&&selected)return <><CompactDoseCard loadFailed={Boolean(error)} onRetry={()=>{setError(null);if(selected)void loadFor(selected);}} showTitle={showTitle} medication={selected} due={due} busy={busy||confirmation!==null||Boolean(error)} onReport={choice=>void report(choice)} onCheck={()=>onVisualCheck?.(selected.regimen_id)} onSnooze={minutes=>run(async()=>{if(!due?.occurrence_id)return;const row=await api.snoozeReminder(due.occurrence_id,minutes);setReminderAt(row.remind_at);setReminderDue(false);})} reminderAt={reminderAt} reminderDue={reminderDue}>
    {lastResult?<div className="status status--ok" role="status">{t(lastResult)}{onFeeling?<div className="actions"><button onClick={onFeeling}>{t('Record how I feel')}</button><button onClick={()=>setLastResult(null)}>{t('Skip for now')}</button></div>:null}</div>:null}
    {renderConfirmation()}{error?<ErrorNotice error={error}/>:null}
  </CompactDoseCard><nav className="today-medication-shortcuts" aria-label={t('Medication management shortcuts')}><button className="text-button" type="button" onClick={onMedicines}>{t('My Medicines')}</button>{onVisualCheck?<button className="text-button" type="button" onClick={()=>onVisualCheck(selected.regimen_id)}>{t('Compare a pill photo')}</button>:null}</nav></>;
  return (
    <Card
      title={compact ? "Today's medication" : "Today"}
    >
      <div className="field" hidden={compact && medications.length === 1}>
        <label htmlFor={selectorId}>{t('Medication')}</label>
        <select
          id={selectorId}
          value={selected?.medication_id ?? ''}
          onChange={(event) => {
            const found = medications.find(
              (m) => m.medication_id === event.target.value,
            );
            if (found) void loadFor(found);
          }}
        >
          {medications.map((medication) => (
            <option key={medication.medication_id} value={medication.medication_id}>
              {medication.display_name}
            </option>
          ))}
        </select>
      </div>

      {!compact && due === null && selected !== null ? (
        <div className="actions">
          <button className="primary" onClick={() => void loadFor(selected)} disabled={busy}>
            {t('Check what is due now')}
          </button>
        </div>
      ) : null}

      {compact ? <><p className="dose-name">{selected?.display_name}</p><nav className="today-medication-shortcuts" aria-label={t('Medication management shortcuts')}><button className="text-button" type="button" onClick={onMedicines}>{t('My Medicines')}</button>{onVisualCheck?<button className="text-button" type="button" onClick={()=>onVisualCheck(selected?.regimen_id ?? null)}>{t('Compare a pill photo')}</button>:null}</nav></> : null}
      {selected?<div className="dose-details"><p><strong>{selected.dose_amount??t('Not specified')} {t(selected.dose_unit??'')}</strong> · {selected.is_prn?t('As needed'):selected.frequency_rule?.local_times.join(', ')??t('Not specified')}</p><p>{selected.food_instruction?.split('; ').map(t).join(' · ')??t('Food instructions not specified')}</p>{selected.course_start_date||selected.course_end_date?<p>{t('Course')}: {selected.course_start_date??t('Not specified')} → {selected.course_end_date??t('Not specified')}</p>:null}</div>:null}
      {due ? (
        due.occurrence_id ? (
          (() => {
            const status = describeDueStatus(due.due_at);
            return (
              <>
                <div
                  className={status.overdue ? 'status status--warn' : 'status status--ok'}
                  role="status"
                >
                  {!compact?<strong>{due.medication_display_name}{language === "zh" ? "：" : " is "}</strong>:null}{t(status.label)}
                  {due.dose_description ? ` — ${due.dose_description}` : ''}.
                  {due.due_at ? (
                    <span className="status__code">
                      {language === 'zh' ? '' : 'due '}{new Date(due.due_at).toLocaleString(language === 'zh' ? 'zh-CN' : 'en-SG', {timeZone:'Asia/Singapore'})}
                    </span>
                  ) : null}
                  <span className="status__code">
                    {t("not reported")} <Tag muted>{t("not a missed dose")}</Tag>
                  </span>
                </div>

                {compact ? <div className="reminder-inline"><button onClick={() => setShowSnooze(value => !value)} disabled={busy}>{t('Remind me later')}</button>
                  {showSnooze ? <div className="actions">{[15,30].map(minutes => <button key={minutes} onClick={() => void run(async () => {
                    const row = await api.snoozeReminder(due.occurrence_id!, minutes); setReminderAt(row.remind_at); setReminderDue(false); setShowSnooze(false);
                  })}>{minutes} {t('min later')}</button>)}</div> : null}
                  {reminderDue ? <p role="alert">{t('Your reminder is due. Review your scheduled medication.')}</p> : null}
                  {reminderAt ? <p role="status">{t('Review reminder')}: {new Date(reminderAt).toLocaleTimeString('en-SG', {timeZone:'Asia/Singapore',hour:'2-digit',minute:'2-digit'})}. {t('Open the app to check it.')}</p> : null}
                </div> : null}
                <div className="actions" >
                  {CHOICES.map((choice) => (
                    <button
                      key={choice.value}
                      className="choice primary"
                      onClick={() => report(choice.value)}
                      disabled={busy || confirmation !== null}
                    >
                      {t(choice.label)}
                    </button>
                  ))}
                </div>

                <p className="notice" hidden={compact}>
                  {t('A photo check is separate evidence. It never proves identity or ingestion.')}
                </p>

                {!compact ? <ReminderOptIn
                  permission={reminderPermission}
                  onEnable={async () => {
                    const result = await reminders.requestPermission();
                    setReminderPermission(result);
                    if (result === 'granted') {
                      await reminders.notify(
                        'MediThread',
                        `${due.medication_display_name} is due.`,
                      );
                    }
                  }}
                  onRemind={async () => {
                    await reminders.notify(
                      'MediThread',
                      `${due.medication_display_name} is still ${t(status.label)}.`,
                    );
                  }}
                /> : null}
              </>
            );
          })()
        ) : (
          <div className="status status--ok" role="status">
            {due.next_due_at ? <p>{due.dose_description} · {language === 'zh' ? '下次安排' : 'Next scheduled'}: {new Date(due.next_due_at).toLocaleString(language === 'zh' ? 'zh-CN' : 'en-SG',{timeZone:'Asia/Singapore',hour12:false})}</p> : null}
            {due.is_prn
              ? t('This medication is taken only when needed, so nothing is scheduled.')
              : t('Nothing is due right now for this medication.')}
            {due.is_prn ? <div className="actions">{CHOICES.map(choice => <button key={choice.value}
              onClick={() => void report(choice.value)} disabled={busy || confirmation !== null}>{t(choice.label)}</button>)}</div> : null}
          </div>
        )
      ) : null}

      {lastResult ? (
        <div className="status status--ok" role="status">
          {t(lastResult)}
          {onFeeling?<div className="actions"><button onClick={onFeeling}>{t('Record how I feel')}</button><button onClick={()=>setLastResult(null)}>{t('Skip for now')}</button></div>:null}
        </div>
      ) : null}

      {confirmation ? (
        <ConfirmReportSheet summary={confirmation.challenge.summary} busy={busy} onConfirm={()=>void confirmReport()} onCancel={()=>setConfirmation(null)}/>
      ) : null}

      {error ? <ErrorNotice error={error} /> : null}

      {history && !compact ? (
        <details>
          <summary>{t("Recent history")} ({history.item_count})</summary>
          <p className="notice">{history.note}</p>
          <ul className="history">
            {history.entries.map((entry, index) => (
              <li key={`${entry.occurrence_id ?? 'x'}-${index}`}>
                <span>
                  {entry.due_at ? new Date(entry.due_at).toLocaleString() : 'no scheduled time'}
                </span>
                <span>
                  {entry.reported ? (
                    entry.intake_status
                  ) : (
                    <>
                      {t("not reported")} <Tag muted>{t("not a missed dose")}</Tag>
                    </>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </Card>
  );
}

/**
 * Opt-in local reminder control.
 *
 * Two rules this component exists to enforce:
 * 1. permission is requested only when the patient presses the button — never
 *    on render;
 * 2. the limitation is always stated, so a patient is never led to believe a
 *    reminder will arrive while the app is closed.
 */
function ReminderOptIn({
  permission,
  onEnable,
  onRemind,
}: {
  permission: ReminderSupport;
  onEnable: () => Promise<void>;
  onRemind: () => Promise<void>;
}) {
  const {t}=useLanguage();
  if (permission === 'unsupported') {
    return (
      <p className="notice">
        <Tag muted>{t("reminders unavailable")}</Tag> {t(REMINDER_LIMITATION)}
      </p>
    );
  }
  if (permission === 'denied') {
    return (
      <p className="notice">
        <Tag muted>{t("reminders blocked")}</Tag> {t("Your browser is blocking notifications. You can allow them in your browser settings.")} {t(REMINDER_LIMITATION)}
      </p>
    );
  }
  return (
    <div className="field">
      <p className="notice" style={{ marginBottom: '0.35rem' }}>
        {REMINDER_LIMITATION}
      </p>
      {permission === 'granted' ? (
        <button type="button" onClick={() => void onRemind()}>
          {t("Notify me about this dose")}
        </button>
      ) : (
        <button type="button" onClick={() => void onEnable()}>
          {t("Turn on local reminders")}
        </button>
      )}
    </div>
  );
}
