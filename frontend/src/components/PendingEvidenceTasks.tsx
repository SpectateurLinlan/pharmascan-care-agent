import type {MedicationSetupEntry} from '../medicationSetup';
import {useLanguage} from '../language';
import {Card,ErrorNotice} from './primitives';
import {useState} from 'react';
import {api} from '../api/client';
import {BottomSheet} from './BottomSheet';
import {ApiError} from '../api/client';

function deleteFailureMessage(error:unknown,t:(value:string)=>string){
 if(error instanceof ApiError&&error.code==='INVALID_INPUT'&&error.message==='This draft has protected or shared records and cannot be deleted.')return t('This draft is linked to protected history or shared records, so it was not deleted.');
 if(error instanceof ApiError&&error.code==='NOT_FOUND')return t('This draft is no longer available. Refresh the list and try again.');
 return t('The draft was not deleted. It is still saved. Try again, or close this message and retry later.');
}

export function PendingEvidenceTasks({entries,error,onRetry,onContinue,onResume}:{entries:MedicationSetupEntry[]|null;error:unknown;onRetry:()=>void;onContinue:(id:string)=>void;onResume:(id:string)=>void}){
 const {t}=useLanguage();
 const [target,setTarget]=useState<MedicationSetupEntry|null>(null),[busy,setBusy]=useState(false),[failure,setFailure]=useState<unknown>(null),[cleanup,setCleanup]=useState<MedicationSetupEntry|null>(null);
 async function remove(row:MedicationSetupEntry){setBusy(true);setFailure(null);try{const result=await api.deleteDraft(row.kind,row.id);setTarget(null);setCleanup(result.cleanup_pending?row:null);onRetry();}catch(caught){setFailure(caught);}finally{setBusy(false);}}
 return <Card title="Finish medication setup">
  {error?<><ErrorNotice error={error}/><button onClick={onRetry}>{t('Retry loading records')}</button></>:null}
  {entries===null&&!error?<p role="status">{t('Loading saved registrations…')}</p>:null}
  {entries?.map(row=><div className="pending-registration" key={`${row.kind}-${row.id}`}><button onClick={()=>row.kind==='source'?onContinue(row.id):onResume(row.id)}>
   {row.name} · {t(row.kind==='draft'?'Review the saved plan':row.conflicting?'Sources need clarification':'Supplement medication information')}
  </button><button className="danger" disabled={busy} onClick={()=>{setFailure(null);setTarget(row);}}>{t('Delete draft')}</button></div>)}
  {cleanup?<p role="status">{t('Draft deleted. Photo cleanup needs a retry.')} <button disabled={busy} onClick={()=>void remove(cleanup)}>{t('Retry photo cleanup')}</button></p>:null}
  {target?<BottomSheet title={t('Delete this draft?')} busy={busy} onCancel={()=>{if(!busy)setTarget(null);}}><p>{target.name}</p><p>{t('This removes the unconfirmed registration and its exclusive draft data. Confirmed history and shared sources are kept. This cannot be undone.')}</p>{failure?<div className="draft-delete-error" role="alert"><p>{deleteFailureMessage(failure,t)}</p><button disabled={busy} onClick={()=>void remove(target)}>{t('Retry deletion')}</button></div>:null}<button className="danger" disabled={busy} onClick={()=>void remove(target)}>{t('Confirm delete')}</button><button disabled={busy} onClick={()=>setTarget(null)}>{t('Cancel')}</button></BottomSheet>:failure?<ErrorNotice error={failure}/>:null}
  {entries?.length===0&&!error?<p>{t('No unfinished medication setup.')}</p>:null}
 </Card>;
}
