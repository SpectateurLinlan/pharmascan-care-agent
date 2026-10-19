import {useEffect,useRef,useState,type FormEvent} from 'react';
import {api} from '../api/client';
import type {DoseFollowUp,DoseFollowUps,LateReason,LateReportChallenge,DoseReportAudit,LateStatus} from '../api/doseFollowUps';
import {useLanguage} from '../language';
import {patientInstant} from '../patientDateTime';
import {careTaskLocalDate} from '../careTaskCalendar';
import {BottomSheet} from './BottomSheet';
import {FollowUpError} from './FollowUpError';
import {careCopy,careLabel} from './followUpCopy';
import '../ui/followups.css';

export function LateDoseFollowUps({enabled=true,todayOnly=false,showHeading=true,onHistory,onInteractionChange,onTodayItemsChange}:{enabled?:boolean;todayOnly?:boolean;showHeading?:boolean;onHistory?:()=>void;onInteractionChange?:(regimen:string,locked:boolean)=>void;onTodayItemsChange?:(items:DoseFollowUp[])=>void}){
 const {language,t,preferences}=useLanguage();
 const [data,setData]=useState<DoseFollowUps|null>(null),[error,setError]=useState<unknown>(null),[reported,setReported]=useState(false),[retry,setRetry]=useState(0),[selected,setSelected]=useState<DoseFollowUp|null>(null),[saved,setSaved]=useState(false);
 useEffect(()=>{if(!enabled)return;let live=true;void api.doseFollowUps(reported).then(value=>{if(live){setData(value);setError(null);}}).catch(caught=>{if(live)setError(caught);});return()=>{live=false;};},[enabled,reported,retry]);
 const zone=data?.timezone??preferences.timezone;
 const day=data?careTaskLocalDate(data.as_of,zone):null;
 const items=(data?.items??[]).filter(item=>!todayOnly||(!item.report_id&&item.can_report!==false&&day!==null&&careTaskLocalDate(item.due_at,zone)===day));
 useEffect(()=>{if(todayOnly&&data)onTodayItemsChange?.(items);},[data,onTodayItemsChange,todayOnly,zone,reported]);
 const when=(value:string)=>Number.isFinite(Date.parse(value))?new Date(value).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:zone}):t('Date unavailable');
 const clock=(value:string)=>Number.isFinite(Date.parse(value))?new Date(value).toLocaleTimeString(language==='zh'?'zh-CN':'en-SG',{timeZone:zone,hour:'numeric',minute:'2-digit'}):t('Date unavailable');
 function choose(value:DoseFollowUp|null){if(selected)onInteractionChange?.(selected.regimen_id,false);if(value)onInteractionChange?.(value.regimen_id,true);setSelected(value);setSaved(false);}
 if(!enabled)return <section className={`today-unrecorded${todayOnly?' today-unrecorded--compact':''}`} aria-label={showHeading?t(todayOnly?"Today's confirmation":'Medication reports to confirm'):undefined}>{showHeading?<h3>{t(todayOnly?"Today's confirmation":'Medication reports to confirm')}</h3>:null}<p role="status">{t('Late reporting is not enabled yet. Your existing medication records remain available in Records.')}</p></section>;
 return <section className={`today-unrecorded${todayOnly?' today-unrecorded--compact':''}`} aria-label={showHeading?t(todayOnly?"Today's confirmation":'Recent dose reports'):undefined}>
  {showHeading?<header className="today-unrecorded__header"><h3>{t(todayOnly?"Today's confirmation":'Medication reports to confirm')}</h3>{todayOnly&&data?<span className="today-unrecorded__count">{language==='zh'?String(items.length)+' \u9879':String(items.length)+' '+(items.length===1?'item':'items')}</span>:null}</header>:null}
  {todayOnly?<p className="today-unrecorded__note">{t('Not recorded does not mean not taken.')}</p>:<div className="late-report-help"><p>{t('Late reporting is available for recent scheduled doses only. The time limit follows your schedule, next dose, and midnight in your time zone.')}</p><p>{t('Not recorded does not mean not taken.')}</p></div>}
  {error?<><FollowUpError error={error} kind="read"/><button onClick={()=>setRetry(value=>value+1)}>{t('Retry')}</button></>:null}
  {saved?<p role="status">{t('Patient report saved.')}</p>:null}
  {!data&&!error?<p role="status">{t('Loading dose reports\u2026')}</p>:data?todayOnly?<>
   {items.length?<ul className="today-dose-list">{items.map(item=><li key={item.occurrence_id}><div><strong>{item.medication_name}</strong><span>{clock(item.due_at)}{' \u00b7 '}{t('Not recorded')}</span></div><button type="button" className="today-dose-list__action" onClick={()=>choose(item)}>{t('Record status')}<span aria-hidden="true">›</span></button></li>)}</ul>:<p className="care-calendar__empty">{t('No eligible doses to report today.')}</p>}
   {onHistory?<button type="button" className="today-records-link" onClick={onHistory}>{t('View all medication records')}<span aria-hidden="true">→</span></button>:null}
  </>:<>
   <ul className="late-dose-list">{items.map(item=><li key={item.occurrence_id}><h4>{item.medication_name}{item.strength_text&&!item.medication_name.toLowerCase().includes(item.strength_text.toLowerCase())?` \u00b7 ${item.strength_text}`:''}</h4><p>{item.can_report===true?t('Reviewed plan'):t('Saved plan needs review')}{' \u00b7 '}{t('Version')} {item.version_no??1}{item.can_report===true&&item.dose_amount!==null&&item.dose_unit?` \u00b7 ${t('Per dose')} ${item.dose_amount} ${t(item.dose_unit)}`:''}</p><p>{t('Scheduled')}: {when(item.due_at)}{' \u00b7 '}{item.intake_status?careLabel(item.intake_status,language,t):t('Not recorded')}</p>{item.can_report===true?<button className="primary" onClick={()=>choose(item)}>{item.report_id?t('Review or correct report'):t('Report dose status')}</button>:<p>{t('Review the saved medication and plan before reporting this occurrence.')} <a href="#medicines">{t('View medicines')}</a></p>}</li>)}</ul>
   {!items.length?<p>{t('No eligible dose occurrences in this view.')}</p>:null}
   {data.has_more?<p>{t('Showing the 50 most recent occurrences. Earlier records remain in Records.')}</p>:null}
   <label><input type="checkbox" checked={reported} onChange={event=>setReported(event.target.checked)}/>{t('Include reported occurrences to review or correct')}</label>
  </>:null}
  {selected?<LateDoseSheet item={selected} zone={zone} onCancel={()=>choose(null)} onSaved={()=>{choose(null);setSaved(true);setRetry(value=>value+1);window.dispatchEvent(new Event('pharmascan:reminder-refresh'));}}/>:null}
 </section>;
}
function LateDoseSheet({item,zone,onCancel,onSaved}:{item:DoseFollowUp;zone:string;onCancel:()=>void;onSaved:()=>void}){
 const {language,t}=useLanguage(),c=careCopy(language);const [status,setStatus]=useState<LateStatus|null>(item.intake_status),[date,setDate]=useState(''),[time,setTime]=useState(''),[reason,setReason]=useState<LateReason|''>(''),[notes,setNotes]=useState('');
 const [challenge,setChallenge]=useState<LateReportChallenge|null>(null),[history,setHistory]=useState<DoseReportAudit>({original:null,corrections:[]}),[historyError,setHistoryError]=useState<unknown>(null),[error,setError]=useState<unknown>(null),[issues,setIssues]=useState<Record<string,string>>({}),[busy,setBusy]=useState(false);
 const key=useRef(crypto.randomUUID()),form=useRef<HTMLFormElement>(null);
 useEffect(()=>{let live=true;void api.lateReportHistory(item.occurrence_id).then(value=>{if(live)setHistory(value);}).catch(caught=>{if(live)setHistoryError(caught);});return()=>{live=false;};},[item.occurrence_id]);
 const when=(value:string)=>new Date(value).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:zone});
 const reasons:Record<LateReason,string>={forgot_to_record:c('Forgot to record','忘记记录'),app_unavailable:c('Could not use the app','当时无法使用应用'),unsure_time:c('Do not remember the time','不记得具体时间'),correcting_record:c('Correcting a previous report','更正之前的自述'),other:c('Other','其他')};
 async function review(event:FormEvent){event.preventDefault();const errors:Record<string,string>={};const actual=status==='reported_taken'&&(date||time)?patientInstant(date,time,zone):null;
  if(!status)errors.status=c('Choose what happened.','请选择本次实际情况。');
  if(!reason)errors.reason=c('Choose a reason.','请选择补记或更正原因。');
  if(status==='reported_taken'&&(date||time)&&(!actual||Date.parse(actual)>Date.now()))errors.date=c('Enter a valid past date and time, or leave both empty if unknown.','请填写有效的过去日期和时间；不记得时可同时留空。');
  if(notes.length>1000)errors.notes=c('Use at most 1000 characters.','备注最多1000字。');
  setIssues(errors);if(Object.keys(errors).length){form.current?.querySelector<HTMLElement>(`[name="${Object.keys(errors)[0]}"]`)?.focus();return;}
  setBusy(true);setError(null);try{setChallenge(await api.prepareLateReport(item.occurrence_id,{id:key.current,intake_status:status!,actual_administration_at:actual,reason:reason as LateReason,notes,expected_report_id:item.report_id}));}catch(caught){setError(caught);}finally{setBusy(false);}
 }
 async function confirm(){if(!challenge||busy)return;setBusy(true);setError(null);try{await api.confirmLateReport(item.occurrence_id,challenge);onSaved();}catch(caught){setError(caught);}finally{setBusy(false);}}
 const fieldError=(name:string)=>issues[name]?<span role="alert" id={`late-${name}`} className="followup-error">{issues[name]}</span>:null;
 return <BottomSheet className="care-flow" title={`${c('Report dose status','补记服药情况')} · ${item.medication_name}`} onCancel={onCancel} busy={busy}>
  <p>{c('Scheduled','计划服用')}: {when(item.due_at)} ({zone})</p><p>{item.strength_text} · {c('Plan version','计划版本')} {item.version_no??1}{item.dose_amount!==null&&item.dose_unit?` · ${item.dose_amount} ${t(item.dose_unit)}`:''}</p>
  {error?<FollowUpError error={error}/>:null}
  {challenge?<><h3>{c('Review your report','请核对您的自述')}</h3><p>{careLabel(challenge.proposed.intake_status,language,t)}</p><p>{c('Actual administration time','实际服用时间')}: {challenge.proposed.actual_administration_at?when(challenge.proposed.actual_administration_at):c('Not provided','未提供')}</p><p>{reasons[challenge.proposed.reason]}</p>{challenge.proposed.notes?<p>{challenge.proposed.notes}</p>:null}<p>{c('The recording time is saved on submission. Your original report is preserved. This is a patient report, not proof of ingestion.','提交时将保存记录时间，并保留原有自述。这是患者自述，不代表已证实吞服。')}</p><p>{c('No additional dose is recommended by this workflow.','此流程不会建议您额外服药。')}</p><div className="followup-actions"><button disabled={busy} onClick={()=>{key.current=crypto.randomUUID();setChallenge(null);}}>{c('Back to edit','返回编辑')}</button><button className="primary" disabled={busy||Date.parse(challenge.expires_at)<=Date.now()} onClick={()=>void confirm()}>{c('Confirm report','确认记录')}</button></div></>:<form ref={form} noValidate onSubmit={event=>void review(event)}>
   <fieldset aria-describedby={issues.status?'late-status':undefined}><legend>{c('What happened?','本次实际情况')}</legend>{(['reported_taken','reported_not_taken','unsure'] as const).map(value=><label key={value}><input type="radio" name="status" checked={status===value} onChange={()=>setStatus(value)}/>{t(value)}</label>)}</fieldset>{fieldError('status')}
   {status==='reported_taken'?<><p>{c('Actual administration time, if remembered (optional)','实际服用时间（如记得，可选）')}</p><div className="followup-grid"><label className="field">{c('Administration date','实际服用日期')}<input type="date" name="date" value={date} onChange={e=>setDate(e.target.value)} aria-invalid={!!issues.date} aria-describedby={issues.date?'late-date':undefined}/></label><label className="field">{c('Administration time','实际服用时刻')}<input type="time" value={time} onChange={e=>setTime(e.target.value)}/></label></div>{fieldError('date')}</>:null}
   <label className="field">{c('Reason (required)','补记或更正原因（必填）')}<select name="reason" value={reason} onChange={e=>setReason(e.target.value as LateReason|'')} aria-invalid={!!issues.reason} aria-describedby={issues.reason?'late-reason':undefined}><option value="">{c('Choose a reason','请选择原因')}</option>{Object.entries(reasons).map(([value,label])=><option value={value} key={value}>{label}</option>)}</select>{fieldError('reason')}</label>
   <label className="field">{c('Notes (optional)','备注（可选）')}<textarea name="notes" value={notes} onChange={e=>setNotes(e.target.value)}/>{fieldError('notes')}</label>
   <div className="followup-actions"><button type="button" onClick={onCancel}>{t('Cancel')}</button><button className="primary" disabled={busy} type="submit">{c('Review report','核对自述')}</button></div>
  </form>}
  {item.report_id?<details><summary>{c('Report history','自述历史')}</summary>{historyError?<FollowUpError error={historyError} kind="read"/>:null}{history.original?<p>{c('Original patient report','原始患者自述')}: {careLabel(history.original.intake_status,language,t)} · {when(history.original.created_at)}</p>:null}<ol className="care-timeline">{history.corrections.map(entry=><li key={entry.id}><p>{careLabel(entry.intake_status,language,t)} · {when(entry.recorded_at)}</p><p>{reasons[entry.reason]}{entry.actual_administration_at?` · ${when(entry.actual_administration_at)}`:''}</p>{entry.notes?<p>{entry.notes}</p>:null}</li>)}</ol></details>:null}
 </BottomSheet>;
}
