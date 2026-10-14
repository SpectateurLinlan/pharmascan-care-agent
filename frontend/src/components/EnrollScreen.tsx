import { useLanguage } from '../language';
/**
 * Medication enrollment: draft -> review -> explicit confirmation -> active.
 *
 * The UI enforces nothing on its own: every gate (required inputs, source
 * review, single-use confirmation) is enforced by the backend and the UI only
 * reflects what the backend returns. A refusal is always displayed, never
 * swallowed.
 */

import { useEffect, useState } from 'react';
import {
  api,
  ApiError,
  type ConfirmChallengeResponse,
  type DraftCreateResponse,
  type MedicationListResponse,
  type SourcePreview,
} from '../api/client';
import { Card, ErrorNotice, Tag } from './primitives';

type Phase =
  | { kind: 'idle' }
  | { kind: 'drafted'; draft: DraftCreateResponse }
  | { kind: 'reviewed'; draft: DraftCreateResponse }
  | { kind: 'confirming'; draft: DraftCreateResponse; challenge: ConfirmChallengeResponse }
  | { kind: 'activated'; regimenId: string };

export function EnrollScreen({
  sessionId,
  medications,
  onChanged, sourceSelection, resumeRegimenId,
}: {
  sessionId: string | null;
  medications: MedicationListResponse | null;
  onChanged: () => void; resumeRegimenId?: string | null; sourceSelection?: { preview: SourcePreview; name: string } | null;
}) {
  const {t}=useLanguage();
  const [name, setName] = useState('');
  const [doseAmount, setDoseAmount] = useState('');
  const [doseUnit, setDoseUnit] = useState('mg');
  //: One entry per daily dose time. A twice-daily medicine has two entries and
  //: the backend materialises one schedule rule per time.
  const [times, setTimes] = useState<string[]>(['08:00']);
  const [isPrn, setIsPrn] = useState(false);
  const [courseStart, setCourseStart] = useState('');
  const [courseEnd, setCourseEnd] = useState('');
  const [courseDays,setCourseDays]=useState('');
  const [foodInstruction,setFoodInstruction]=useState('');
  const [frequency, setFrequency] = useState<'daily' | 'weekly'>('daily');
  const [weekdays, setWeekdays] = useState<number[]>([]);
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (sourceSelection) { setName(sourceSelection.name); setDoseAmount('');setTimes(['']);setCourseStart('');setCourseEnd('');setCourseDays('');setFoodInstruction('');setIsPrn(false); setPhase({kind:'idle'}); } }, [sourceSelection]);

  useEffect(() => {
    if (!resumeRegimenId) return;
    let active = true;
    void api.resumeDraft(resumeRegimenId).then(draft => { if(active) setPhase({kind:'drafted',draft}); })
      .catch(caught => { if(active) setError(caught); });
    return () => { active = false; };
  }, [resumeRegimenId]);

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

  const setTimeAt = (index: number, value: string) =>
    setTimes((current) => current.map((existing, i) => (i === index ? value : existing)));

  const addTime = () => setTimes((current) => [...current, '20:00']);

  const removeTimeAt = (index: number) =>
    setTimes((current) => (current.length <= 1 ? current : current.filter((_, i) => i !== index)));

  /** Distinct, non-empty, sorted times — mirrors the backend's normalisation. */
  const normalisedTimes = () =>
    Array.from(
      new Set(times.map((value) => normaliseTime(value)).filter((value) => value !== '')),
    ).sort();

  const submitDraft = () =>
    run(async () => {
      const parsedAmount = doseAmount.trim() === '' ? null : Number(doseAmount);
      const selectedTimes = normalisedTimes();
      if (!isPrn && selectedTimes.length === 0) {
        throw new Error('Add at least one time of day, or tick "only when needed".');
      }
      const draft = await api.createDraft({
        course_start_date: courseStart || null,
        course_end_date: courseEnd || null,
        ...(sourceSelection && sourceSelection.name.trim() === name.trim() ? { extraction_evidence: sourceSelection.preview } : {}),
        medication_name: name.trim(),
        dose_amount: parsedAmount,
        dose_unit: parsedAmount === null ? null : doseUnit.trim() || null,
        frequency_kind: isPrn ? null : frequency,
        frequency_days_of_week: frequency === 'weekly' ? weekdays : [],
        frequency_local_times: isPrn ? [] : selectedTimes,
        is_prn: isPrn,
        food_instruction: [isPrn?'as needed':'',foodInstruction].filter(Boolean).join('; ')||null,
      });
      setPhase({ kind: 'drafted', draft }); onChanged();
    });

  const submitReview = (draft: DraftCreateResponse) =>
    run(async () => {
      await api.reviewDraft(draft.source_id);
      setPhase({ kind: 'reviewed', draft });
    });

  const requestConfirmation = (draft: DraftCreateResponse) =>
    run(async () => {
      if (!sessionId) {
        throw new Error('No agent session yet — start the demo session first.');
      }
      const challenge = await api.requestChallenge(draft.regimen_id, sessionId);
      setPhase({ kind: 'confirming', draft, challenge });
    });

  const confirmActivation = (draft: DraftCreateResponse, challenge: ConfirmChallengeResponse) =>
    run(async () => {
      const activated = await api.activate({
        regimen_id: draft.regimen_id,
        challenge_id: challenge.challenge_id,
        session_id: challenge.session_id,
        session_state: challenge.session_state,
        session_state_version: challenge.session_state_version,
      });
      setPhase({ kind: 'activated', regimenId: activated.regimen_id });
      setName('');
      setDoseAmount('');
      onChanged();
    });

  const reset = () => {
    setPhase({ kind: 'idle' });
    setError(null);
  };

  return (
    <Card
      title="Add a medication"
      hint="A draft is never active on its own. You review the details, then explicitly confirm."
    >
      {phase.kind === 'idle' || phase.kind === 'activated' ? (
        <>
          {phase.kind === 'activated' ? (
            <div className="status status--ok" role="status">
              {t('Regimen activated. It now appears in your medication list.')}
            </div>
          ) : null}

          <div className="field">
            <label htmlFor="med-name">{t('Medication name')}</label>
            <input
              id="med-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="e.g. Amlodipine"
              autoComplete="off"
            />
          </div>

          <div className="grid-2">
            <div className="field">
              <label htmlFor="med-dose">{t('Dose amount')}</label>
              <input
                id="med-dose"
                value={doseAmount}
                onChange={(event) => setDoseAmount(event.target.value)}
                inputMode="decimal"
                placeholder="e.g. 5"
              />
            </div>
            <div className="field">
              <label htmlFor="med-unit">{t('Unit')}</label>
              <input
                id="med-unit"
                value={doseUnit}
                onChange={(event) => setDoseUnit(event.target.value)}
                placeholder="mg"
              />
            </div>
          </div>

          <div className="grid-2">
            <div className="field"><label htmlFor="course-start">{t('Course start date')}</label><input id="course-start" type="date" value={courseStart} onChange={event => {setCourseStart(event.target.value);if(courseDays)setCourseEnd(courseEndForDuration(event.target.value,Number(courseDays))??'');}} /></div>
            <div className="field"><label htmlFor="course-end">{t('Last day (inclusive)')}</label><input id="course-end" type="date" min={courseStart || undefined} value={courseEnd} onChange={event => {setCourseEnd(event.target.value);setCourseDays('');}} /></div>
          </div>
          <div className="field"><label htmlFor="course-days">{t('Number of days')}</label><input id="course-days" type="number" min="1" max="3660" value={courseDays} onChange={event=>{setCourseDays(event.target.value);setCourseEnd(courseEndForDuration(courseStart,Number(event.target.value))??'');}}/><p className="notice">{t('Enter a start date and the duration in your reviewed instructions. The last day is calculated inclusively.')}</p></div>
          <div className="field"><label htmlFor="food-instruction">{t('Food instructions')}</label><select id="food-instruction" value={foodInstruction} onChange={event=>setFoodInstruction(event.target.value)}><option value="">{t('Not specified')}</option>{['before food','after food','with food','without regard to food'].map(value=><option key={value} value={value}>{t(value)}</option>)}</select></div>
          <p className="notice">{t('Use the dates in your reviewed instructions. Leave the end date blank if not specified; the app will not infer it.')}</p>
          <div className="field"><label htmlFor="med-frequency">{t('Schedule')}</label><select id="med-frequency" disabled={isPrn} value={frequency} onChange={event => setFrequency(event.target.value as 'daily' | 'weekly')}><option value="daily">{t('Every day')}</option><option value="weekly">{t('Selected weekdays')}</option></select></div>
          {!isPrn && frequency === 'weekly' ? <fieldset className="field"><legend>{t('Selected weekdays')}</legend>{['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'].map((day,index)=><label key={day}><input type="checkbox" checked={weekdays.includes(index+1)} onChange={event => setWeekdays(current => event.target.checked ? [...current,index+1] : current.filter(value=>value!==index+1))} />{t(day)}</label>)}</fieldset> : null}
          <fieldset className="field" disabled={isPrn}>
            <legend>{t('Times of day')}</legend>
            <p className="notice" style={{ marginTop: 0 }}>
              {t('Add one entry per dose. Two entries (e.g. 08:00 and 20:00) means the medication is taken twice daily.')}
            </p>
            {times.map((value, index) => (
              <div key={index} className="time-row">
                <label htmlFor={`med-time-${index}`} className="visually-hidden">
                  {t('Dose time')} {index + 1}
                </label>
                <input
                  id={`med-time-${index}`}
                  type="time"
                  value={value}
                  onChange={(event) => setTimeAt(index, event.target.value)}
                  disabled={isPrn}
                />
                <button
                  type="button"
                  onClick={() => removeTimeAt(index)}
                  disabled={isPrn || times.length <= 1}
                  aria-label={`Remove dose time ${index + 1}`}
                >
                  {t('Remove')}
                </button>
              </div>
            ))}
            <button type="button" onClick={addTime} disabled={isPrn}>
              {t('Add another time')}
            </button>
            {!isPrn && normalisedTimes().length < times.length ? (
              <span className="notice">
                {t('Duplicate times are treated as a single dose.')}
              </span>
            ) : null}
          </fieldset>

          <div className="field">
            <label htmlFor="med-prn">
              <input
                id="med-prn"
                type="checkbox"
                checked={isPrn}
                onChange={(event) => setIsPrn(event.target.checked)}
                style={{ width: 'auto', minHeight: 'auto', marginRight: '0.5rem' }}
              />
              {t('Take only when needed (no fixed schedule)')}
            </label>
          </div>

          <div className="actions">
            <button
              className="primary"
              onClick={submitDraft}
              disabled={busy || name.trim() === '' || (!!courseDays&&!courseEnd) || (frequency==='weekly'&&!isPrn&&!weekdays.length)}
            >
              {t('Create draft')}
            </button>
            {phase.kind === 'activated' ? (
              <button onClick={reset} disabled={busy}>
                Add another
              </button>
            ) : null}
          </div>
        </>
      ) : null}

      {phase.kind === 'drafted' ? (
        <>
          <p className="setup-progress">{t('Step 2 of 3: review, then activate. Drafts are not active medications.')}</p>
          <div className="status status--warn" role="status">
            {t('Draft saved — not active yet.')}
            {phase.draft.missing_instructions.length > 0 ? (
              <>
                {' '}
                {t('Still needed')}: <strong>{phase.draft.missing_instructions.map(value=>t(value)).join(', ')}</strong>.
                {t('Activating will be refused until these are provided.')}
              </>
            ) : null}
          </div>
          <p className="notice">
            {t('Next: confirm the extracted details are correct. This marks the medication-name evidence as reviewed by you.')}
          </p>
          <div className="actions">
            <button className="primary" onClick={() => submitReview(phase.draft)} disabled={busy}>
              {t('I have reviewed these details')}
            </button>
            <button onClick={reset} disabled={busy}>
              {t('Cancel')}
            </button>
          </div>
        </>
      ) : null}

      {phase.kind === 'reviewed' ? (
        <>
          <div className="status status--ok" role="status">
            {t('Details marked as reviewed by you. The regimen is still not active.')}
          </div>
          <div className="actions">
            <button
              className="primary"
              onClick={() => requestConfirmation(phase.draft)}
              disabled={busy}
            >
              {t('Show me the summary to confirm')}
            </button>
            <button onClick={reset} disabled={busy}>
              {t('Cancel')}
            </button>
          </div>
        </>
      ) : null}

      {phase.kind === 'confirming' ? (
        <>
          <div className="status status--warn" role="status">
            <strong>{t('Please check this before I save it.')}</strong>
            <ul style={{ margin: '0.4rem 0 0', paddingLeft: '1.2rem' }}>
              <li>{t('Medication')}: {phase.challenge.summary.medication_name}</li>
              <li>
                {t('Dose amount')}: {phase.challenge.summary.dose_amount ?? '—'}{' '}
                {t(phase.challenge.summary.dose_unit ?? '')}
              </li>
              <li>
                {t('Schedule')}:{' '}
                {phase.challenge.summary.is_prn
                  ? t('only when needed')
                  : (phase.challenge.summary.frequency?.local_times.join(', ') ??
                    'not specified')}
              </li>
              <li>{t('Course start date')}: {phase.challenge.summary.course_start_date ?? t('Not specified')}</li>
              <li>{t('Last day (inclusive)')}: {phase.challenge.summary.course_end_date ?? t('Not specified')}</li>
              <li>{t('Food instructions')}: {phase.challenge.summary.food_instruction?.split('; ').map(value=>t(value)).join('；')??t('Not specified')}</li>
              <li>{t('Time zone')}: {phase.challenge.summary.local_timezone}</li>
            </ul>
            <span className="status__code">
              {t('Confirmation expires')}{' '}
              {new Date(phase.challenge.expires_at).toLocaleTimeString()}
            </span>
          </div>
          <div className="actions">
            <button
              className="primary"
              onClick={() => confirmActivation(phase.draft, phase.challenge)}
              disabled={busy}
            >
              {t('Yes, save this medication')}
            </button>
            <button onClick={reset} disabled={busy}>
              {t('No, go back')}
            </button>
          </div>
        </>
      ) : null}

      {error ? <ErrorNotice error={error} /> : null}

      {medications && medications.item_count > 0 ? (
        <p className="notice">
          {medications.item_count} {t('active medications on your list')}
        </p>
      ) : (
        <p className="notice">
          {t('No active medication yet')} <Tag muted>{t('nothing activated')}</Tag>
        </p>
      )}
    </Card>
  );
}

export function isAlreadyRecordedError(error: unknown): boolean {
  return error instanceof ApiError && error.code === 'DUPLICATE_EVENT';
}

/** Calendar arithmetic only after the patient supplies both start and days. */
export function courseEndForDuration(start:string,days:number):string|null{
 if(!/^\d{4}-\d{2}-\d{2}$/.test(start)||!Number.isInteger(days)||days<1||days>3660)return null;
 const date=new Date(start+'T00:00:00Z');if(Number.isNaN(date.getTime())||date.toISOString().slice(0,10)!==start)return null;
 date.setUTCDate(date.getUTCDate()+days-1);return date.toISOString().slice(0,10);
}

/**
 * Canonicalise a `<input type="time">` value to `HH:MM`, dropping anything
 * malformed. Mirrors the backend's `_normalise_local_time` so the client and
 * the server agree on what counts as the same dose slot.
 */
export function normaliseTime(value: string): string {
  const match = /^(\d{1,2}):(\d{2})/.exec(value.trim());
  if (!match) {
    return '';
  }
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  if (!Number.isInteger(hour) || !Number.isInteger(minute)) {
    return '';
  }
  if (hour < 0 || hour > 23 || minute < 0 || minute > 59) {
    return '';
  }
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
}
