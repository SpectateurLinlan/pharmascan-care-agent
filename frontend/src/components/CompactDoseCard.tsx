import {useState,type ReactNode} from 'react';
import type {DueDoseResponse,MedicationSummary} from '../api/client';
import {useLanguage} from '../language';
import {Card} from './primitives';

/**
 * The dose card, which is the screen a patient opens most often.
 *
 * Presentation only. The parent owns the real challenge, confirmation and
 * reminder requests.
 *
 * Order is deliberate and safety-driven:
 *   1. which medicine this is, and the product strength it is not confused with;
 *   2. what you were told to take, on one line;
 *   3. whether anything is due, and that "not reported" is not "missed";
 *   4. the report choices, visible — reporting a dose is the reason this screen
 *      exists, so it is never hidden behind a disclosure;
 *   5. the secondary photo check, which is a plain visible action rather than a
 *      disclosure. It used to sit inside "More options", where it was both
 *      overlooked and taking a whole extra row.
 *
 * What is deliberately *not* here any more, and why:
 *   - the "Course" dates: they belong to the plan record, which shows them with
 *     the rest of the reviewed instructions;
 *   - the "My Medicines" / "My History" shortcuts: both are root destinations in
 *     the navigation, so repeating them inside the dose card was noise;
 *   - the "You will see exactly what will be recorded" promise: the confirmation
 *     sheet shows exactly that, at the moment it matters.
 *
 * A report still goes through the two-phase challenge and confirmation sheet in
 * the parent. Nothing here writes anything.
 */
export function CompactDoseCard({medication,due,busy,onReport,onCheck,onSnooze,reminderAt,reminderDue,children,showTitle=true,loadFailed=false,onRetry}:{
 medication:MedicationSummary;due:DueDoseResponse|null;busy:boolean;onReport:(choice:string)=>void;onCheck:()=>void;
 onSnooze:(minutes:number)=>Promise<void>;reminderAt:string|null;reminderDue:boolean;children:ReactNode;showTitle?:boolean;loadFailed?:boolean;onRetry?:()=>void;
}){
 const {t,language,preferences}=useLanguage();const [snooze,setSnooze]=useState(false);
 const doseDescription=language==='zh'?`${medication.dose_amount??t('Not specified')} ${t(medication.dose_unit??'')}`:due?.dose_description??`${medication.dose_amount??t('Not specified')} ${t(medication.dose_unit??'')}`;
 const time=(value:string)=>new Date(value).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:preferences.timezone,hour12:false});
 const canReport=Boolean(due&&(due.occurrence_id||due.is_prn));
 const strength=medication.dose_basis?.strength_text??null;
 const scheduleText=medication.is_prn?t('As needed'):medication.frequency_rule?.local_times.join(', ')??t('Not specified');
 const foodText=medication.food_instruction?medication.food_instruction.split('; ').map(t).join(' · '):null;
 return <Card {...(showTitle?{title:"Today's medication"}:{})}>
  <div className="dose-head">
   <p className="dose-name compact-name">{medication.display_name}</p>
   {/* What you were told to take, on one line: the units per dose, when, and
       whether it goes with food. The product strength stays separate and quiet
       underneath, because "1 tablet" and "500 mg" are different facts. */}
   <p className="dose-plan"><strong>{doseDescription}</strong>{scheduleText?<span className="dose-plan__sep">·</span>:null}{scheduleText?<span>{scheduleText}</span>:null}{foodText?<span className="dose-plan__sep">·</span>:null}{foodText?<span>{foodText}</span>:null}</p>
   {strength?<p className="dose-strength">{t('Product strength')}: {strength}</p>:null}
  </div>

  {loadFailed
   ? <div className="ui-callout ui-callout--danger" role="alert"><p>{t('Schedule unavailable. Try loading it again.')}</p><button onClick={onRetry}>{t('Retry loading schedule')}</button></div>
   : !due
    ? <p role="status">{t('Loading your reviewed schedule…')}</p>
    : due.occurrence_id
     ? <p className="compact-dose-status" role="status">{t('Awaiting your report')} · {due.due_at?time(due.due_at):t('due now')}<small>{t('not a missed dose')}</small></p>
     : <p className="notice" role="status">{due.next_due_at?`${doseDescription} · ${t('Next scheduled')}: ${time(due.next_due_at)}`:t(due.is_prn?'This medication is taken only when needed, so nothing is scheduled.':'Nothing is due right now for this medication.')}</p>}

  {canReport?<div className="dose-report" role="group" aria-label={t('Report this dose')}>
   <div className="dose-report__choices">
    <button className="primary choice" disabled={busy} onClick={()=>onReport('Taken')}>{t('Taken')}</button>
    <button className="choice" disabled={busy} onClick={()=>onReport('Not now')}>{t('Not now')}</button>
    <button className="choice" disabled={busy} onClick={()=>onReport('Unsure')}>{t('Unsure')}</button>
   </div>
   {due?.occurrence_id?<div className="reminder-inline"><button disabled={busy} onClick={()=>setSnooze(value=>!value)}>{t('Remind me later')}</button>
    {snooze?<div className="actions">{[15,30].map(minutes=><button disabled={busy} key={minutes} onClick={()=>void onSnooze(minutes).then(()=>setSnooze(false))}>{minutes} {t('min later')}</button>)}</div>:null}
   </div>:null}
  </div>:null}

  {reminderDue?<p role="alert">{t('Your reminder is due. Review your scheduled medication.')}</p>:null}
  {reminderAt?<p role="status">{t('Review reminder')}: {time(reminderAt)}. {t('Open the app to check it.')}</p>:null}

  {/* A visible, low-emphasis action rather than a disclosure: a patient looking
      for the photo check should not have to guess that it exists. The safety
      statement for the check is stated on the check itself. */}
  <button type="button" className="dose-secondary-action" disabled={busy} onClick={onCheck}>{t('Compare a pill photo')}</button>

  {children}
 </Card>;
}
