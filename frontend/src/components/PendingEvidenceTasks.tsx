import type {MedicationSetupEntry} from '../medicationSetup';
import {useLanguage} from '../language';
import {Card,ErrorNotice} from './primitives';

export function PendingEvidenceTasks({entries,error,onRetry,onContinue,onResume}:{entries:MedicationSetupEntry[]|null;error:unknown;onRetry:()=>void;onContinue:(id:string)=>void;onResume:(id:string)=>void}){
 const {t}=useLanguage();
 return <Card title="Finish medication setup">
  {error?<><ErrorNotice error={error}/><button onClick={onRetry}>{t('Retry loading records')}</button></>:null}
  {entries===null&&!error?<p role="status">{t('Loading saved registrations…')}</p>:null}
  {entries?.map(row=><button key={`${row.kind}-${row.id}`} onClick={()=>row.kind==='source'?onContinue(row.id):onResume(row.id)}>
   {row.name} · {t(row.kind==='draft'?'Review the saved plan':row.conflicting?'Sources need clarification':'Supplement medication information')}
  </button>)}
  {entries?.length===0&&!error?<p>{t('No unfinished medication setup.')}</p>:null}
 </Card>;
}
