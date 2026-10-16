import {useState} from 'react';
import {api} from '../api/client';
import type {CareReview} from '../api/care';
import {useLanguage} from '../language';
import {BottomSheet} from './BottomSheet';
import {ErrorNotice} from './primitives';

/** Shared human confirmation surface. No model tool can invoke this save. */
export function CareReviewSheet({proposal,onCancel,onSaved}:{proposal:CareReview;onCancel:()=>void;onSaved:()=>void}){
 const {t,language,preferences}=useLanguage();const [busy,setBusy]=useState(false),[error,setError]=useState<unknown>(null);
 const value=proposal.stock??proposal.barrier??proposal.task??proposal.task_update;
 const [note,setNote]=useState(proposal.stock?.note??proposal.barrier?.description??proposal.task?.notes??proposal.task_update?.notes??'');
 const [quantity,setQuantity]=useState(String(proposal.stock?.quantity??''));
 const date=(value:string)=>new Date(value).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:preferences.timezone});
 async function save(){setBusy(true);setError(null);try{
  if(proposal.stock&&proposal.medication_id){await api.recordStock(proposal.medication_id,{...proposal.stock,quantity:Number(quantity),note,confirmed:true});}
  else if(proposal.barrier){await api.recordBarrier({...proposal.barrier,description:note,confirmed:true});}
  else if(proposal.task){await api.createCareTask({...proposal.task,notes:note,confirmed:true});}
  else if(proposal.task_update&&proposal.task_id){await api.updateCareTask(proposal.task_id,{...proposal.task_update,notes:note,confirmed:true});}
  else throw new Error('Incomplete care proposal');
  onSaved();
 }catch(caught){setError(caught);}finally{setBusy(false);}}
 return <BottomSheet title={t('Review medication-care record')} busy={busy} onCancel={onCancel}>
 <p>{t('Patient-reported information. This does not change your prescription or record a dose.')}</p>
 {proposal.stock?<><p>{t(proposal.stock.kind)} · {t(proposal.stock.unit)}</p><label className="field">{t('Quantity')}<input type="number" step="any" value={quantity} onChange={event=>setQuantity(event.target.value)}/></label><p>{t('Low-stock threshold')}: {proposal.stock.low_threshold} {t(proposal.stock.unit)}</p></>:null}
 {proposal.barrier?<><p>{t(proposal.barrier.category)}</p><p>{date(proposal.barrier.occurred_at)}</p><p>{t('Chosen support action')}: {proposal.barrier.chosen_action||t('Not specified')}</p></>:null}
 {proposal.task?<><p><strong>{proposal.task.title}</strong></p><p>{t(proposal.task.category)} · {date(proposal.task.due_at)}</p></>:null}
 {proposal.task_update?<p>{t(proposal.task_update.status)} {proposal.task_update.due_at?date(proposal.task_update.due_at):''}</p>:null}
 <label className="field">{t('Your note')}<textarea maxLength={proposal.stock?500:1000} value={note} onChange={event=>setNote(event.target.value)}/></label>
 {error?<ErrorNotice error={error}/>:null}<div className="actions"><button className="primary" disabled={busy||!value||(proposal.stock!==null&&proposal.stock!==undefined&&(!quantity.trim()||!Number.isFinite(Number(quantity))))} onClick={()=>void save()}>{t('Confirm record')}</button><button disabled={busy} onClick={onCancel}>{t('Cancel')}</button></div>
 </BottomSheet>;
}
