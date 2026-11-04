import {useState} from 'react';
import {api} from '../api/client';
import type {CareReview} from '../api/care';
import {useLanguage} from '../language';
import {BottomSheet} from './BottomSheet';
import {ErrorNotice} from './primitives';

/** Shared human confirmation surface. No model tool can invoke this save. */
export interface CareReviewPatientPort {save:(proposal:CareReview)=>Promise<unknown>}
export function CareReviewSheet({proposal,onCancel,onSaved,patient,readOnlyFields=false,onCheckResult,targetLabel,associationLabel,associationState}:{proposal:CareReview;onCancel:()=>void;onSaved:()=>void|Promise<void>;patient?:CareReviewPatientPort;readOnlyFields?:boolean;targetLabel?:string|undefined;associationLabel?:string|undefined;associationState?:string|undefined;onCheckResult?:(()=>Promise<void>)|undefined}){
 const {t,language,preferences}=useLanguage();const [busy,setBusy]=useState(false),[error,setError]=useState<unknown>(null);
 const value=proposal.stock??proposal.barrier??proposal.task??proposal.task_update;
 const [note,setNote]=useState(proposal.stock?.note??proposal.barrier?.description??proposal.task?.notes??proposal.task_update?.notes??'');
 const [quantity,setQuantity]=useState(String(proposal.stock?.quantity??''));
 const [uncertain,setUncertain]=useState(false),[historical,setHistorical]=useState(false);
 const pastTask=!!proposal.task&&Date.parse(proposal.task.due_at)<Date.now()||!!patient&&!!proposal.task_update?.due_at&&!['completed','cancelled'].includes(proposal.task_update.status)&&Date.parse(proposal.task_update.due_at)<Date.now();
 const date=(value:string)=>new Date(value).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:preferences.timezone});
 async function save(){if(busy||uncertain)return;setBusy(true);setError(null);try{
  if(patient){await patient.save({...proposal,...(proposal.stock?{stock:{...proposal.stock,quantity:Number(quantity),note,confirmed:true}}:{}),...(proposal.barrier?{barrier:{...proposal.barrier,description:note,confirmed:true}}:{}),...(proposal.task?{task:{...proposal.task,notes:note,confirmed:true,historical_confirmed:pastTask&&historical}}:{}),...(proposal.task_update?{task_update:{...proposal.task_update,notes:note,confirmed:true,...(pastTask?{historical_confirmed:historical}:{})}}:{})});}
  else if(proposal.stock&&proposal.medication_id){await api.recordStock(proposal.medication_id,{...proposal.stock,quantity:Number(quantity),note,confirmed:true});}
  else if(proposal.barrier){await api.recordBarrier({...proposal.barrier,description:note,confirmed:true});}
  else if(proposal.task){if(pastTask)throw new Error(language==='zh'?'请在用药跟进中确认历史事项，并选择不提醒。':'Confirm historical entry with no reminder in Medication follow-ups.');await api.createCareTask({...proposal.task,...(proposal.task.historical_confirmed?{historical_confirmed:false}:{}),notes:note,confirmed:true});}
  else if(proposal.task_update&&proposal.task_id){await api.updateCareTask(proposal.task_id,{...proposal.task_update,...(proposal.task_update.historical_confirmed?{historical_confirmed:false}:{}),notes:note,confirmed:true});}
  else throw new Error('Incomplete care proposal');
  await onSaved();
 }catch(caught){setError(caught);if(onCheckResult)setUncertain(true);}finally{setBusy(false);}}
 return <BottomSheet title={t('Review medication-care record')} busy={busy} onCancel={onCancel}>
 {targetLabel?<h3>{targetLabel}</h3>:null}
 <p>{t('Patient-reported information. This does not change your prescription or record a dose.')}</p>
 {proposal.stock?<><p>{t(proposal.stock.kind)} · {t(proposal.stock.unit)}</p><label className="field">{t('Quantity')}<input type="number" step="any" readOnly={readOnlyFields} value={quantity} onChange={event=>setQuantity(event.target.value)}/></label><p>{t('Low-stock threshold')}: {proposal.stock.low_threshold} {t(proposal.stock.unit)}</p></>:null}
 {proposal.barrier?<><p>{t(proposal.barrier.category)}</p><p>{date(proposal.barrier.occurred_at)}</p><p>{t('Chosen support action')}: {proposal.barrier.chosen_action||t('Not specified')}</p></>:null}
 {proposal.task?<><p><strong>{proposal.task.title}</strong></p><p>{t(proposal.task.category)} · {date(proposal.task.due_at)}</p><p>{proposal.task.reminder_minutes===null?t('No reminder'):`${t('Advance reminder (minutes)')}: ${proposal.task.reminder_minutes??0}`}</p></>:null}
 {pastTask&&!patient?<p role="alert">{language==='zh'?'该事项时间已过去。请在用药跟进中新建事项，确认历史日期并选择不提醒。':'This task is in the past. Use New medication follow-up to confirm historical entry with no reminder.'}</p>:null}
 {proposal.task_update?.title!==undefined?<p><strong>{proposal.task_update.title}</strong></p>:null}
 {proposal.task_update?.category!==undefined?<p>{t(proposal.task_update.category)}</p>:null}
 {proposal.task||proposal.task_update?<p>{associationState==='removed'?(language==='zh'?'移除药物和计划关联':'Remove the medication and plan link'):associationLabel??(associationState==='none'?(language==='zh'?'不关联药物或计划':'No medication or plan link'):associationState==='unchanged'?(language==='zh'?'药物和计划关联保持不变':'Medication and plan link unchanged'):'')}</p>:null}
 {proposal.task_update&&'reminder_minutes' in proposal.task_update?<p>{proposal.task_update.reminder_minutes===null?t('No reminder'):`${t('Advance reminder (minutes)')}: ${proposal.task_update.reminder_minutes}`}</p>:null}
 {proposal.task_update?<p>{t(proposal.task_update.status)} {proposal.task_update.due_at?date(proposal.task_update.due_at):''}</p>:null}
 {patient&&pastTask?<label><input type="checkbox" checked={historical} onChange={event=>setHistorical(event.target.checked)}/>{language==='zh'?'我已核对过去的日期，确认作为历史事项保存，不安排过去的提醒。':'I checked the past date and confirm a historical task without a past reminder.'}</label>:null}
 <label className="field">{t('Your note')}<textarea readOnly={readOnlyFields} maxLength={proposal.stock?500:1000} value={note} onChange={event=>setNote(event.target.value)}/></label>
 {uncertain?<button type="button" disabled={busy} onClick={async()=>{setBusy(true);try{await onCheckResult?.();}catch(caught){setError(caught);}finally{setBusy(false);}}}>{language==='zh'?'核查关怀记录结果':'Check care result'}</button>:null}
 {error?<ErrorNotice error={error}/>:null}<div className="actions"><button className="primary" disabled={busy||uncertain||pastTask&&(!patient||!historical)||!value||(proposal.stock!==null&&proposal.stock!==undefined&&(!quantity.trim()||!Number.isFinite(Number(quantity))))} onClick={()=>void save()}>{t('Confirm record')}</button><button disabled={busy} onClick={onCancel}>{t('Cancel')}</button></div>
 </BottomSheet>;
}
