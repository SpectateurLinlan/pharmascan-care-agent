import {useEffect,useMemo,useRef,useState} from 'react';
import {api} from '../api/client';
import type {WorkflowEventHandler,WorkflowView} from '../api/assistantWorkflows';
import type {DoseFollowUp} from '../api/doseFollowUps';
import {useLanguage} from '../language';
import {LateDoseSheet,type LateReportPatientPort,type LateReportDraft} from './LateDoseFollowUps';

function selected(value:unknown):DoseFollowUp|null{
 if(!value||typeof value!=='object'||Array.isArray(value))return null;
 const row=value as Record<string,unknown>;
 if(['occurrence_id','regimen_id','medication_id','medication_name','due_at','notes'].some(key=>typeof row[key]!=='string')||row.can_report!==true||!Number.isFinite(Date.parse(String(row.due_at))))return null;
 if(row.report_id!==null&&typeof row.report_id!=='string'||row.dose_amount!==null&&typeof row.dose_amount!=='number'||row.dose_unit!==null&&typeof row.dose_unit!=='string')return null;
 if(row.intake_status!==null&&!['reported_taken','reported_not_taken','unsure'].includes(String(row.intake_status)))return null;
 return row as unknown as DoseFollowUp;
}

/** One selected existing patient form, with no model access to its contents. */
export function AssistantLateReportActions({view,busy,onEvent,onDirtyChange,onClinicalChanged}:{view:WorkflowView;busy:boolean;onEvent:WorkflowEventHandler;onDirtyChange?:(dirty:boolean)=>void;onClinicalChanged?:(()=>void)|undefined}){
 const {language}=useLanguage(),say=(en:string,zh:string)=>language==='zh'?zh:en;
 const [open,setOpen]=useState(false);
 const draft=useRef<LateReportDraft|null>(null);
 const callbacks=useRef(onDirtyChange);callbacks.current=onDirtyChange;
 const item=selected(view.visible_fields.late_target),ref=view.result_ref;
 const eligible=view.save_mode==='allowed'&&view.state==='awaiting_confirmation'&&ref?.kind==='dose_occurrence'&&item?.occurrence_id===ref.id;
 const patient=useMemo<LateReportPatientPort>(()=>{
  const binding={task_id:view.task_id,expected_revision:view.revision};
  return {history:api.lateReportHistory,prepare:async(id,values)=>{
   const summary=await api.prepareLateReport(id,values,binding);
   if(summary.occurrence.occurrence_id!==id||summary.occurrence.report_id!==values.expected_report_id||!summary.challenge_id||!Number.isFinite(Date.parse(summary.expires_at))||Date.parse(summary.expires_at)<=Date.now()||Object.entries(values).some(([key,value])=>summary.proposed[key as keyof typeof values]!==value))throw new Error('The historical patient summary changed. Reopen this review.');
   return summary;
  },confirm:async(id,summary)=>{
   const result=await api.confirmLateReport(id,summary,binding);
   if(result.id!==summary.proposed.id||result.occurrence_id!==id||result.ingestion_proven!==false)throw new Error('The historical report result needs checking.');
   return result;
  }};
 },[view.task_id,view.revision]);
 useEffect(()=>{callbacks.current?.(open);return()=>callbacks.current?.(false);},[open]);
 if(!eligible||!item)return null;
 async function readResult(){
  const latest=await onEvent({event_id:crypto.randomUUID(),expected_revision:view.revision,kind:'report_business_result',values:{}});
  if(!latest||latest.task_id!==view.task_id||latest.revision<=view.revision)throw new Error('The actual report result is not available yet.');
  if(latest.state==='completed'){draft.current=null;setOpen(false);onClinicalChanged?.();}
 }
 return <div>
  <p>{item.medication_name} · {new Date(item.due_at).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:typeof view.visible_fields.timezone==='string'?view.visible_fields.timezone:'Asia/Singapore'})}</p>
  <button type="button" disabled={busy} onClick={()=>setOpen(true)}>{say('Review historical report','核对历史自述')}</button>
  {open?<LateDoseSheet key={`${view.task_id}:${view.revision}`} item={item} zone={typeof view.visible_fields.timezone==='string'?view.visible_fields.timezone:'Asia/Singapore'} patient={patient} draft={draft.current} onDraftChange={value=>{draft.current=value;}} onCancel={()=>{draft.current=null;setOpen(false);}} onSaved={readResult} onCheckResult={readResult}/>:null}
 </div>;
}
