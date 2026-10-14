import {useState,type ReactNode} from 'react';
import type {DueDoseResponse,MedicationSummary} from '../api/client';
import {useLanguage} from '../language';
import {Card} from './primitives';

/** Presentation only. The parent owns real challenge, confirmation and reminder requests. */
export function CompactDoseCard({medication,due,busy,onReport,onCheck,onSnooze,reminderAt,reminderDue,onMedicines,onHistory,children,showTitle=true}:{
 medication:MedicationSummary;due:DueDoseResponse|null;busy:boolean;onReport:(choice:string)=>void;onCheck:()=>void;
 onSnooze:(minutes:number)=>Promise<void>;reminderAt:string|null;reminderDue:boolean;onMedicines?:(()=>void)|undefined;onHistory?:(()=>void)|undefined;children:ReactNode;showTitle?:boolean;
}){
 const {t,language}=useLanguage();const [snooze,setSnooze]=useState(false);
 const doseDescription=language==='zh'?`${medication.dose_amount??t('Not specified')} ${t(medication.dose_unit??'')}`:due?.dose_description??`${medication.dose_amount??t('Not specified')} ${t(medication.dose_unit??'')}`;
 const time=(value:string)=>new Date(value).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:'Asia/Singapore',hour12:false});
 return <Card {...(showTitle?{title:"Today's medication"}:{})}><p className="dose-name compact-name">{medication.display_name}</p>
 <div className="compact-plan"><p><strong>{doseDescription}</strong> · {medication.is_prn?t('As needed'):medication.frequency_rule?.local_times.join(', ')??t('Not specified')}</p>
 <p>{medication.food_instruction?.split('; ').map(t).join(' · ')??t('Food instructions not specified')}</p>
 {medication.course_start_date||medication.course_end_date?<p>{t('Course')}: {medication.course_start_date??t('Not specified')} → {medication.course_end_date??t('Not specified')}</p>:null}</div>
 {!due?<p role="status">{t('Loading your reviewed schedule…')}</p>:due.occurrence_id?<p className="compact-dose-status" role="status">{t('Awaiting your report')} · {due.due_at?time(due.due_at):t('due now')}<small>{t('not a missed dose')}</small></p>:<p className="notice" role="status">{due.next_due_at?`${doseDescription} · ${t('Next scheduled')}: ${time(due.next_due_at)}`:t(due.is_prn?'This medication is taken only when needed, so nothing is scheduled.':'Nothing is due right now for this medication.')}</p>}
 <details className="dose-card-actions"><summary>{t('View medication actions')}</summary>
 <p className="visual-check-hint">{t('Compare a pill photo with your medication references. This does not establish that it is safe to take.')}</p>
 <button className="primary dominant" disabled={busy} onClick={onCheck}>{t('Compare a pill photo')}</button>
 {due&&(due.occurrence_id||due.is_prn)?<><div className="daily-actions"><button disabled={busy} onClick={()=>onReport('Taken')}>{t('Taken')}</button>{due.occurrence_id?<button disabled={busy} onClick={()=>setSnooze(value=>!value)}>{t('Remind me later')}</button>:null}<button disabled={busy} onClick={()=>onReport('Unsure')}>{t('Unsure')}</button></div>
 {snooze?<div className="actions">{[15,30].map(minutes=><button disabled={busy} key={minutes} onClick={()=>void onSnooze(minutes).then(()=>setSnooze(false))}>{minutes} {t('min later')}</button>)}</div>:null}
 <details className="report-options"><summary>{t('Other report options')}</summary><button disabled={busy} onClick={()=>onReport('Not now')}>{t('Patient reported not taken')}</button></details></>:null}
 {onMedicines||onHistory?<div className="quick-actions compact-shortcuts">{onMedicines?<button onClick={onMedicines}>{t('My Medicines')}</button>:null}{onHistory?<button onClick={onHistory}>{t('My History')}</button>:null}</div>:null}
 </details>
 {reminderDue?<p role="alert">{t('Your reminder is due. Review your scheduled medication.')}</p>:null}
 {reminderAt?<p role="status">{t('Review reminder')}: {time(reminderAt)}. {t('Open the app to check it.')}</p>:null}
 {children}</Card>;
}
