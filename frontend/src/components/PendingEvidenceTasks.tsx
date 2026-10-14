import {useEffect,useState} from 'react';
import {api,type EvidenceTask} from '../api/client';
import {useLanguage} from '../language';
import {Card,ErrorNotice} from './primitives';

export function PendingEvidenceTasks({onContinue}:{onContinue:(id:string)=>void}){
 const {t}=useLanguage();const [tasks,setTasks]=useState<EvidenceTask[]>([]),[error,setError]=useState<unknown>(null);
 useEffect(()=>{let live=true;if(api.evidenceTasks)void api.evidenceTasks().then(rows=>{if(live)setTasks(rows.filter(row=>row.status!=='draft_created'));}).catch(caught=>{if(live)setError(caught);});return()=>{live=false;};},[]);
 return <Card title="Source registrations to complete">{error?<ErrorNotice error={error}/>:null}{tasks.map(row=><button key={row.id} onClick={()=>onContinue(row.id)}>{row.product.name} {row.product.strength??''} · {t(row.conflicts.length?'Sources need clarification':'Information still needed')}</button>)}{!tasks.length&&!error?<p>{t('No pending source registrations.')}</p>:null}</Card>;
}
