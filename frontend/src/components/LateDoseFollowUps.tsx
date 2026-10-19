import {useEffect,useRef,useState,type FormEvent} from 'react';
import {api} from '../api/client';
import type {DoseFollowUp,DoseFollowUps,LateReason,LateReportChallenge,DoseReportAudit,LateStatus} from '../api/doseFollowUps';
import {useLanguage} from '../language';
import {patientInstant} from '../patientDateTime';
import {BottomSheet} from './BottomSheet';
import {FollowUpError} from './FollowUpError';
import {careCopy,careLabel} from './followUpCopy';
import '../ui/followups.css';

export function LateDoseFollowUps({enabled=true,onInteractionChange}:{enabled?:boolean;onInteractionChange?:(regimen:string,locked:boolean)=>void}){
 const {language,t,preferences}=useLanguage(),c=careCopy(language);
 const [expanded,setExpanded]=useState(false),[data,setData]=useState<DoseFollowUps|null>(null),[error,setError]=useState<unknown>(null),[reported,setReported]=useState(false),[retry,setRetry]=useState(0),[selected,setSelected]=useState<DoseFollowUp|null>(null),[saved,setSaved]=useState(false);
 useEffect(()=>{if(!enabled)return;let live=true;void api.doseFollowUps(reported).then(value=>{if(live){setData(value);setError(null);}}).catch(caught=>{if(live)setError(caught);});return()=>{live=false;};},[enabled,reported,retry]);
 const when=(value:string)=>new Date(value).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:data?.timezone??preferences.timezone});
 function choose(value:DoseFollowUp|null){if(selected)onInteractionChange?.(selected.regimen_id,false);if(value)onInteractionChange?.(value.regimen_id,true);setSelected(value);setSaved(false);}
 if(!enabled)return <section className="today-unrecorded"><h3>{c('Medication reports to confirm','需要确认服药情况')}</h3><p role="status">{c('Late reporting is not enabled yet. Your existing medication records remain available in Records.','补记功能尚未启用，已有服药记录仍可在记录页查看。')}</p></section>;
 return <section className="today-unrecorded" aria-label={c('Recent dose reports','近期服药情况')}><h3>{c('Medication reports to confirm','需要确认服药情况')}</h3>
  <p>{c('Unreported means there is no confirmed patient report. It does not mean a dose was missed.','尚未记录表示系统没有收到经您确认的服药自述，不等于未服用。')}</p>
  <p className="notice">{c('Past seven days. A scheduled dose leaves Today’s action window at the earliest of two hours after its planned time, the next scheduled dose, or local midnight. This does not change your medication instructions.','最近七天：计划时间后2小时、下一剂计划时间或患者当地午夜，以最早者结束今日操作窗口。这不会更改您的用药指示。')}</p>
  {error?<><FollowUpError error={error} kind="read"/><button onClick={()=>setRetry(value=>value+1)}>{t('Retry')}</button></>:null}
  {saved?<p role="status">{c('Patient report saved.','已保存您的服药自述。')}</p>:null}
  {!data&&!error?<p role="status">{c('Loading dose reports…','正在读取服药情况…')}</p>:data?<><ul className="late-dose-list">{(expanded?data.items:data.items.slice(0,3)).map(item=><li key={item.occurrence_id}><h4>{item.medication_name}{item.strength_text&&!item.medication_name.toLowerCase().includes(item.strength_text.toLowerCase())?` · ${item.strength_text}`:''}</h4><p>{item.can_report===false?c('Saved plan · review required','已保存计划 · 待核对'):c('Reviewed plan','已核对计划')} · {c('Version','版本')} {item.version_no??1}{item.can_report!==false&&item.dose_amount!==null&&item.dose_unit?` · ${c('Per dose','每次服用')} ${item.dose_amount} ${t(item.dose_unit)}`:''}</p><p>{c('Scheduled','计划时间')}: {when(item.due_at)} · {item.intake_status?careLabel(item.intake_status,language,t):c('Not recorded','尚未记录')}</p>{item.can_report===false?<p>{c('Review the saved medication and plan before reporting this occurrence.','请先核对已保存的药物及计划，再记录该剂次。')} <a href="#medicines">{c('View medicines','查看药物')}</a></p>:<button className="primary" onClick={()=>choose(item)}>{item.report_id?c('Review or correct report','查看或更正自述'):c('Report dose status','补记服药情况')}</button>}</li>)}</ul>{data.items.length>3?<button onClick={()=>setExpanded(value=>!value)}>{expanded?c('Show fewer','收起'):c(`View all ${data.items.length} reports`,`查看全部${data.items.length}个剂次`)}</button>:null}{!data.items.length?<p>{c('No eligible dose occurrences in this view.','该分类暂无可补记的计划剂次。')}</p>:null}{data.has_more?<p>{c('Showing the 50 most recent occurrences. Earlier records remain in Records.','显示最近50个剂次，更早的记录仍可在记录页查看。')}</p>:null}</>:null}
  <label><input type="checkbox" checked={reported} onChange={e=>setReported(e.target.checked)}/>{c('Include reported occurrences to review or correct','包含已记录剂次，以便查看或更正')}</label>
  {selected?<LateDoseSheet item={selected} zone={data?.timezone??preferences.timezone} onCancel={()=>choose(null)} onSaved={()=>{choose(null);setSaved(true);setRetry(value=>value+1);window.dispatchEvent(new Event('pharmascan:reminder-refresh'));}}/>:null}
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
