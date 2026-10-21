import {Icon} from './Icon';
import {MedicationDate} from './MedicationInputs';
import {DoseDetails,emptyDoseBasis} from './DoseDetails';
import type {DoseBasis,DoseDisplay} from '../api/dose';
import { useLanguage } from '../language';
/**
 * Medication enrollment: two perceived steps over the same backend states.
 *
 * Perceived flow
 * --------------
 *   1. Add a medication  — identity, strength, units per dose, schedule, course.
 *   2. Review and add    — one consolidated, editable summary; an explicit
 *                          patient review acknowledgement; then the existing
 *                          B14 confirmation; then activation.
 *
 * The four screens this replaces (form -> "step 2 of 3" -> "show me the
 * summary" -> B14 sheet) made the patient walk the *backend's* state machine.
 * The states are unchanged and still enforced server-side:
 *   draft -> validation -> patient review -> single-use challenge ->
 *   explicit confirmation -> activation.
 * Nothing here can activate an unreviewed plan, invent a missing dose, or clear
 * a conflict; a refusal is always displayed, never swallowed.
 *
 * Field meanings are deliberately kept apart and never conflated:
 *   Strength       per unit of product   e.g. "500 mg" per tablet
 *   Units per dose a count               e.g. "1" tablet
 *   Total dose     derived by the server from both, or honestly "not calculated"
 */

import { useEffect, useRef, useState } from 'react';
import {
  api,
  ApiError,
  type ConfirmChallengeResponse,
  type DraftCreateResponse,
  type MedicationListResponse,
  type SourcePreview,
  type RegimenHistoryItem,
} from '../api/client';
import { BottomSheet } from './BottomSheet';
import { Card, ErrorNotice, Tag, AutoDismissNotice } from './primitives';

const WEEKDAYS = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];

export function EnrollScreen({
  sessionId,
  medications,
  onChanged, onDirtyChange, sourceSelection, resumeRegimenId, resumeRow, editFrom, onActivated,
}: {
  editFrom?: RegimenHistoryItem | null; onActivated?:(id:string)=>void;
  sessionId: string | null;
  medications: MedicationListResponse | null;
  onDirtyChange?:(dirty:boolean)=>void;
  onChanged: () => void; resumeRegimenId?: string | null; resumeRow?: RegimenHistoryItem | null;
  sourceSelection?: { preview: SourcePreview; name: string } | null;
}) {
  const {t}=useLanguage();
  const fieldId=(value:string)=>editFrom?`edit-${value}`:value;
  const [step,setStep]=useState<'form'|'review'>('form');
  const [name, setName] = useState('');
  const [doseAmount, setDoseAmount] = useState('');
  const [doseBasis,setDoseBasis]=useState<DoseBasis>(emptyDoseBasis);
  const [doseUnit, setDoseUnit] = useState('tablet');
  //: One entry per daily dose time. A twice-daily medicine has two entries and
  //: the backend materialises one schedule rule per time.
  const [times, setTimes] = useState<string[]>(['08:00']);
  const [isPrn, setIsPrn] = useState(false);
  const [courseStart, setCourseStart] = useState('');
  const [courseEnd, setCourseEnd] = useState('');
  const [courseDays,setCourseDays]=useState('');
  const [courseMode,setCourseMode]=useState<'days'|'end'>(editFrom?.course_end_date?'end':'days');
  const [foodInstruction,setFoodInstruction]=useState('');
  const [frequency, setFrequency] = useState<'daily' | 'weekly' | 'interval'>('daily');
  const [everyHours,setEveryHours]=useState('');
  const [firstTime,setFirstTime]=useState('');
  const [weekdays, setWeekdays] = useState<number[]>([]);
  //: The medication a re-commit belongs to. Set after the first successful
  //: draft so editing re-uses the product instead of registering a second one.
  const [medicationId,setMedicationId]=useState<string|null>(editFrom?.medication_id??null);
  const [draft,setDraft]=useState<DraftCreateResponse|null>(null);
  const [challenge,setChallenge]=useState<ConfirmChallengeResponse|null>(null);
  //: The patient's own statement that the details match their instructions.
  //: This is the source-review gate and is never set on the patient's behalf.
  const [reviewed,setReviewed]=useState(false);
  const [activated,setActivated]=useState(false);
  const [total,setTotal]=useState<DoseDisplay|null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  // A checked source and a course belong to one enrollment, never the next drug.
  function clearEntryFields() {
    setName('');setDoseAmount('');setDoseUnit('tablet');setDoseBasis(emptyDoseBasis);
    setTimes(['08:00']);setIsPrn(false);setCourseStart('');setCourseEnd('');setCourseDays('');setCourseMode('days');
    setFoodInstruction('');setFrequency('daily');setWeekdays([]);setEveryHours('');setFirstTime('');
  }

  useEffect(()=>{onDirtyChange?.(!activated&&Boolean(name||doseAmount||courseStart||courseEnd||courseDays||draft||foodInstruction||doseBasis.strength_text||doseBasis.instructions_text||isPrn||frequency!=='daily'||everyHours||firstTime||times.join(',')!=='08:00'));},[activated,name,doseAmount,courseStart,courseEnd,courseDays,draft,foodInstruction,doseBasis,isPrn,times,frequency,everyHours,firstTime,onDirtyChange]);
  const prefilled=useRef<string|null>(null);
  useEffect(()=>{if(!editFrom||prefilled.current===editFrom.regimen_id)return;prefilled.current=editFrom.regimen_id;
    setDoseBasis(emptyDoseBasis);setCourseDays('');setCourseMode(editFrom?.course_end_date?'end':'days');
    setFrequency(editFrom.frequency_rule?.kind==='interval'?'interval':editFrom.frequency_rule?.kind==='weekly'?'weekly':'daily');setEveryHours(String(editFrom.frequency_rule?.every_hours??''));setFirstTime(editFrom.frequency_rule?.interval_anchor?.time_source==='default_0800'?'':editFrom.local_times[0]??'');setWeekdays(editFrom.frequency_rule?.days_of_week??[]);setName(editFrom.display_name);setDoseAmount(String(editFrom.dose_amount??''));setDoseUnit(editFrom.dose_unit??'');setTimes(editFrom.local_times.length?editFrom.local_times:['']);setIsPrn(editFrom.is_prn);setCourseStart(editFrom.course_start_date??'');setCourseEnd(editFrom.course_end_date??'');setFoodInstruction(editFrom.food_instruction??'');setStep('form');
  },[editFrom]);
  useEffect(() => { if (sourceSelection) { clearEntryFields();setName(sourceSelection.name);setTimes(['']);setStep('form'); } }, [sourceSelection]);

  /**
   * Resume an unfinished registration. The form is prefilled from the known
   * regimen row so the patient can complete it, and the medication is reused
   * rather than registered a second time.
   */
  const resumed=useRef<string|null>(null);
  useEffect(() => {
    if (!resumeRegimenId||resumed.current===resumeRegimenId) return;
    let active = true;
    setBusy(true);setStep('form');setReviewed(false);setChallenge(null);
    void api.resumeDraft(resumeRegimenId).then(saved => {
      if(!active)return;
      resumed.current=resumeRegimenId;
      setMedicationId(saved.medication_id);
      setDraft(saved);
      if(resumeRow){
        setCourseMode(resumeRow.course_end_date?'end':'days');
        setDoseBasis(emptyDoseBasis);setCourseDays('');
        setFrequency(resumeRow.frequency_rule?.kind==='interval'?'interval':resumeRow.frequency_rule?.kind==='weekly'?'weekly':'daily');setEveryHours(String(resumeRow.frequency_rule?.every_hours??''));setFirstTime(resumeRow.frequency_rule?.interval_anchor?.time_source==='default_0800'?'':resumeRow.local_times[0]??'');setWeekdays(resumeRow.frequency_rule?.days_of_week??[]);
        setName(resumeRow.display_name);setDoseAmount(String(resumeRow.dose_amount??''));setDoseUnit(resumeRow.dose_unit??'tablet');
        setTimes(resumeRow.local_times.length?resumeRow.local_times:['08:00']);setIsPrn(resumeRow.is_prn);
        setCourseStart(resumeRow.course_start_date??'');setCourseEnd(resumeRow.course_end_date??'');setFoodInstruction(resumeRow.food_instruction??'');
      }
      setStep('form');
    }).catch(caught => { if(active) setError(caught); }).finally(()=>{if(active)setBusy(false);});
    return () => { active = false; };
  }, [resumeRegimenId, resumeRow]);

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

  const draftInput = () => {
    const parsedAmount = doseAmount.trim() === '' ? null : Number(doseAmount);
    const selectedTimes = normalisedTimes();
    return {
      patient_edited:Boolean(editFrom),
      supersedes_regimen_id:editFrom?.state==='active'?editFrom.regimen_id:null,
      course_start_date: courseStart || null,
      course_end_date: courseEnd || null,
      ...(sourceSelection && sourceSelection.name.trim() === name.trim() ? { extraction_evidence: sourceSelection.preview } : {}),
      medication_name: name.trim(),
      dose_basis: doseBasis.strength_text||doseBasis.instructions_text?doseBasis:null,
      dose_amount: parsedAmount,
      dose_unit: parsedAmount === null ? null : doseUnit.trim() || null,
      frequency_kind: isPrn ? null : frequency,
      frequency_days_of_week: frequency === 'weekly' ? weekdays : [],
      frequency_local_times: isPrn ? [] : frequency==='interval'?(firstTime?[firstTime]:[]):selectedTimes,
      frequency_every_hours: !isPrn&&frequency==='interval'?Number(everyHours):null,
      is_prn: isPrn,
      food_instruction: [isPrn?'as needed':'',foodInstruction].filter(Boolean).join('; ')||null,
    };
  };

  const formBlocked = () =>
    name.trim() === '' || (!!courseDays&&!courseEnd) || (frequency==='weekly'&&!isPrn&&!weekdays.length) || (!isPrn&&frequency==='interval'&&(!courseStart||!Number.isInteger(Number(everyHours))||Number(everyHours)<1||Number(everyHours)>720));

  /**
   * Commit: the single action that walks the real state machine.
   *
   * draft -> review -> challenge. The B14 sheet is then shown for the explicit
   * confirmation; activation only ever happens from that sheet.
   */
  const commit = () =>
    run(async () => {
      const selectedTimes = normalisedTimes();
      if (!isPrn && frequency!=='interval' && selectedTimes.length === 0) {
        throw new Error('Add at least one time of day, or tick "only when needed".');
      }
      const created = await api.createDraft(draftInput(), medicationId ?? undefined);
      setDraft(created); setMedicationId(created.medication_id);
      // A saved draft belongs in pending setup immediately, even if confirmation is cancelled.
      await onChanged();
      if (created.missing_instructions.length > 0) {
        // The draft is stored but is NOT active. Nothing is inferred to fill the
        // gap; the patient supplies it and commits again.
        return;
      }
      await api.reviewDraft(created.source_id);
      if (!sessionId) {
        throw new Error('No agent session yet — start the demo session first.');
      }
      setChallenge(await api.requestChallenge(created.regimen_id, sessionId));
    });

  const confirmActivation = () =>
    run(async () => {
      if(!challenge) return;
      const activatedRow = await api.activate({
        regimen_id: challenge.regimen_id,
        challenge_id: challenge.challenge_id,
        session_id: challenge.session_id,
        session_state: challenge.session_state,
        session_state_version: challenge.session_state_version,
      });
      setChallenge(null);
      setActivated(true);
      window.dispatchEvent(new Event('pharmascan:plan-activated'));
      clearEntryFields();setDraft(null);setMedicationId(null);setReviewed(false);
      await onChanged();onActivated?.(activatedRow.regimen_id);
    });

  const reset = () => {
    setStep('form');setDraft(null);setReviewed(false);setError(null);setChallenge(null);setActivated(false);
  };

  /** The server's own arithmetic. Never a locally derived pill count. */
  useEffect(()=>{
    let live=true;
    if(step!=='review'||!doseBasis.strength_text||!doseAmount||!Number.isFinite(Number(doseAmount))||Number(doseAmount)<=0){setTotal(null);return;}
    void api.doseDisplay(doseBasis,Number(doseAmount),doseUnit).then(value=>{if(live)setTotal(value);}).catch(()=>{if(live)setTotal(null);});
    return ()=>{live=false;};
  },[step,doseBasis,doseAmount,doseUnit]);

  const scheduleText=()=>{
    if(isPrn)return t('Only when needed');
    if(frequency==='interval')return `${t('Every N hours')}: ${everyHours}; ${t('First dose time')}: ${firstTime||t('Default 08:00')}`;
    if(frequency==='weekly')return `${t('Selected weekdays')}: ${weekdays.map(day=>t(WEEKDAYS[day-1]??'')).join(', ')}`;
    return normalisedTimes().join(', ');
  };
  const courseText=()=>`${courseStart||t('Not specified')} → ${courseEnd||t('Not specified')}`;

  const fields=()=><>
    <div className="field">
      <label htmlFor={fieldId('med-name')}>{t('Medication name')}</label>
      <input
        id={fieldId('med-name')}
        readOnly={Boolean(editFrom)} value={name}
        onChange={(event) => {setName(event.target.value);setDoseBasis(emptyDoseBasis);}}
        placeholder="e.g. Amlodipine"
        autoComplete="off"
      />
    </div>

    <div className="grid-2 enrollment-fields">
      <div className="field">
        <label htmlFor={fieldId('med-dose')}>{t('Units per dose')}</label>
        <input
          id={fieldId('med-dose')} aria-label={t('Dose amount')}
          value={doseAmount}
          onChange={(event) => setDoseAmount(event.target.value)}
          inputMode="decimal"
          placeholder="1"
        />
      </div>
      <div className="field">
        <label htmlFor={fieldId('med-unit')}>{t('Dose unit')}</label>
        <input
          id={fieldId('med-unit')} aria-label={t('Unit')}
          value={doseUnit === 'tablet' || doseUnit === 'capsule' ? t(doseUnit) : doseUnit}
          onChange={(event) => {
            const value = event.target.value;
            setDoseUnit(value === t('tablet') ? 'tablet' : value === t('capsule') ? 'capsule' : value);
          }}
          placeholder={t('tablet')}
        />
      </div>
    </div>
    <p className="notice">{t('Units per dose is how many you take each time — for example 1 tablet. It is not the strength printed on the pack.')}</p>

    <DoseDetails id={fieldId('dose-basis')} basis={doseBasis} onChange={setDoseBasis} amount={doseAmount} unit={doseUnit}/>
    <fieldset className="course-fields">
      <legend>{t('Course duration')}</legend>
      <div className="course-mode"><label><input type="radio" name={fieldId('course-mode')} checked={courseMode==='days'} onChange={()=>{setCourseMode('days');setCourseDays(courseDuration(courseStart,courseEnd));}}/>{t('Enter number of days')}</label><label><input type="radio" name={fieldId('course-mode')} checked={courseMode==='end'} onChange={()=>setCourseMode('end')}/>{t('Enter last day')}</label></div>
      <div className="grid-2 enrollment-fields">
        <MedicationDate label="Course start date" value={courseStart} onChange={value=>{setCourseStart(value);if(courseMode==='days'){setCourseEnd(courseEndForDuration(value,Number(courseDays))??'');}else{setCourseDays(courseDuration(value,courseEnd));}}}/>
        {courseMode==='end'?<MedicationDate label="Last day (inclusive)" min={courseStart} value={courseEnd} onChange={value=>{setCourseEnd(value);setCourseDays(courseDuration(courseStart,value));}}/>:<div className="field"><label htmlFor={fieldId('course-days')}>{t('Number of days')}</label><input id={fieldId('course-days')} type="number" min="1" max="3660" value={courseDays} onChange={event=>{setCourseDays(event.target.value);setCourseEnd(courseEndForDuration(courseStart,Number(event.target.value))??'');}}/></div>}
      </div>
      <p className="notice" role="status">{courseMode==='days'&&courseEnd?`${t('Last day (inclusive)')}: ${courseEnd}`:courseMode==='end'&&courseDays?`${t('Number of days')}: ${courseDays}`:t('Enter a start date and either the number of days or the last day. The other value is calculated, including the last day.')}</p>
    </fieldset>
    <div className="field"><label htmlFor="food-instruction">{t('Food instructions')}</label><select id="food-instruction" value={foodInstruction} onChange={event=>setFoodInstruction(event.target.value)}><option value="">{t('Not specified')}</option>{['before food','after food','with food','without regard to food'].map(value=><option key={value} value={value}>{t(value)}</option>)}</select></div>
    <div className="field"><label htmlFor={fieldId('med-frequency')}>{t('Schedule')}</label><select id={fieldId('med-frequency')} disabled={isPrn} value={frequency} onChange={event => setFrequency(event.target.value as 'daily' | 'weekly' | 'interval')}><option value="daily">{t('Every day')}</option><option value="weekly">{t('Selected weekdays')}</option><option value="interval">{t('Every N hours')}</option></select></div>
    {!isPrn&&frequency==='interval'?<fieldset className="field"><legend>{t('First dose time')}</legend><div className="grid-2 enrollment-fields"><div className="field"><label htmlFor={fieldId('interval-hours')}>{t('Interval in hours')}</label><input id={fieldId('interval-hours')} type="number" min="1" max="720" step="1" value={everyHours} onChange={event=>setEveryHours(event.target.value)}/></div><MedicationDate id={fieldId('first-time')} type="time" label={t('First dose time (optional)')} value={firstTime} onChange={setFirstTime}/></div><p className="notice">{t('When is the first dose? If left blank, 08:00 is used by default. The course start date is the first-dose date. Check both before confirming; this is not a report that you took it.')}</p></fieldset>:null}
    {!isPrn && frequency === 'weekly' ? <fieldset className="field"><legend>{t('Selected weekdays')}</legend>{WEEKDAYS.map((day,index)=><label key={day}><input type="checkbox" checked={weekdays.includes(index+1)} onChange={event => setWeekdays(current => event.target.checked ? [...current,index+1] : current.filter(value=>value!==index+1))} />{t(day)}</label>)}</fieldset> : null}
    <fieldset className="field" disabled={isPrn} hidden={frequency==='interval'}>
      <legend>{t('Times of day')}</legend>
      <p className="notice" style={{ marginTop: 0 }}>
        {t('Add one entry per dose. Two entries (e.g. 08:00 and 20:00) means the medication is taken twice daily.')}
      </p>
      {times.map((value, index) => (
        <div key={index} className="time-row">
          <MedicationDate id={`${editFrom?'edit-':''}med-time-${index}`} type="time" label={`${t('Dose time')} ${index+1}`} value={value} onChange={value=>setTimeAt(index,value)}/>
          {index===times.length-1?<button type="button" className="icon-button" aria-label={t('Add another time')} onClick={addTime} disabled={isPrn}><Icon name="plus"/></button>:null}
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
      {!isPrn && normalisedTimes().length < times.length ? (
        <span className="notice">
          {t('Duplicate times are treated as a single dose.')}
        </span>
      ) : null}
    </fieldset>

    <div className="field">
      <label htmlFor={fieldId('med-prn')}>
        <input
          id={fieldId('med-prn')}
          type="checkbox"
          checked={isPrn}
          onChange={(event) => setIsPrn(event.target.checked)}
          style={{ width: 'auto', minHeight: 'auto', marginRight: '0.5rem' }}
        />
        {t('Take only when needed (no fixed schedule)')}
      </label>
    </div>
  </>;

  // --- added ---------------------------------------------------------------
  if (activated) {
    return <Card title={editFrom?'Review a new plan version':'Add a medication'}>
      <AutoDismissNotice>{t('Medication added. It now appears in your medication list.')}</AutoDismissNotice>
      <div className="actions">
        <button onClick={reset} disabled={busy}>{t('Add another')}</button>
      </div>
      {medications && medications.item_count > 0 ? <p className="notice">{medications.item_count} {t('active medications on your list')}</p> : null}
    </Card>;
  }

  // --- step 2: review and add ----------------------------------------------
  if (step === 'review') {
    const missing = draft?.missing_instructions ?? [];
    return <>
      <Card
        title={t('Review and add')}
        hint={t('Check the details below. Nothing becomes an active plan until you confirm.')}
      >
        <dl className="review-summary">
          <div><dt>{t('Medication name')}</dt><dd>{name.trim()||t('Not specified')}</dd></div>
          <div><dt>{t('Strength')}</dt><dd>{doseBasis.strength_text||t('Not recorded')}</dd></div>
          <div><dt>{t('Units per dose')}</dt><dd>{doseAmount?`${doseAmount} ${doseUnit.trim()?t(doseUnit.trim()):''}`.trim():t('Not recorded')}</dd></div>
          <div><dt>{t('Total dose')}</dt><dd>{total?.status==='calculated'?`${total.total_amount} ${total.total_unit}`:t('Not calculated')}</dd></div>
          <div><dt>{t('Schedule')}</dt><dd>{scheduleText()||t('Not specified')}</dd></div>
          <div><dt>{t('Course')}</dt><dd>{courseText()}</dd></div>
          <div><dt>{t('Food instructions')}</dt><dd>{foodInstruction?t(foodInstruction):t('Not specified')}</dd></div>
        </dl>

        {missing.length ? <div className="status status--warn" role="alert">
          {t('Still needed')}: <strong>{missing.map(value=>t(value)).join(', ')}</strong>. {t('Activating will be refused until these are provided.')}
        </div> : null}

        <details className="review-edit">
          <summary>{t('Edit details')}</summary>
          {fields()}
        </details>

        <label className="consent">
          <input type="checkbox" checked={reviewed} onChange={event=>setReviewed(event.target.checked)}/>
          {t('I have checked these details against my original instructions.')}
        </label>

        <div className="actions">
          <button className="primary" onClick={()=>void commit()} disabled={busy||formBlocked()||missing.length>0||!reviewed}>
            {t(busy?'Saving...':'Add this medication')}
          </button>
          <button onClick={()=>setStep('form')} disabled={busy}>{t('Back to details')}</button>
        </div>
      </Card>

      {error ? <ErrorNotice error={error} /> : null}

      {challenge ? <BottomSheet title={t('Please check this before I save it')} busy={busy} onCancel={()=>setChallenge(null)}>
        <p className="confirm-what">{challenge.summary.medication_name}: {challenge.summary.dose_amount} {t(challenge.summary.dose_unit??'')}</p>
        <p>{challenge.summary.is_prn?t('only when needed'):challenge.summary.frequency?.kind==='interval'?`${t('Every N hours')}: ${challenge.summary.frequency.every_hours}; ${t('First dose time')}: ${challenge.summary.frequency.interval_anchor?.time_source==='default_0800'?t('Default 08:00'):challenge.summary.frequency.interval_anchor?.local_time}`:challenge.summary.frequency?.local_times.join(', ')}</p>
        <p>{challenge.summary.course_start_date??t('Not specified')} → {challenge.summary.course_end_date??t('Not specified')}</p>
        <p className="notice">{t('Confirmation expires')} {new Date(challenge.expires_at).toLocaleTimeString()}</p>
        <div className="actions">
          <button className="primary" disabled={busy} onClick={()=>void confirmActivation()}>{t('Yes, save this medication')}</button>
          <button disabled={busy} onClick={()=>setChallenge(null)}>{t('Cancel')}</button>
        </div>
      </BottomSheet> : null}
    </>;
  }

  // --- step 1: add a medication --------------------------------------------
  return (
    <Card
      title={editFrom?'Review a new plan version':'Add a medication'}
      hint="Enter the amount in your medication instructions, then review the plan."
    >
      {fields()}

      <div className="actions">
        <button
          className="primary"
          onClick={()=>{setError(null);setStep('review');}}
          disabled={busy || formBlocked()}
        >
          {t('Review and add')}
        </button>
      </div>

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

export function courseDuration(start:string,end:string):string{
 if(!/^\d{4}-\d{2}-\d{2}$/.test(start)||!/^\d{4}-\d{2}-\d{2}$/.test(end))return '';
 const first=Date.parse(start+'T00:00:00Z'),last=Date.parse(end+'T00:00:00Z');
 if(!Number.isFinite(first)||!Number.isFinite(last)||new Date(first).toISOString().slice(0,10)!==start||new Date(last).toISOString().slice(0,10)!==end)return '';
 const days=(last-first)/86400000+1;return days>=1&&days<=3660?String(days):'';
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
