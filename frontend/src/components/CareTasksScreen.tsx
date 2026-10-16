import {useEffect,useState} from 'react';
import {api,type RegimenHistoryItem,type MedicationSummary} from '../api/client';
import type {CareReview,CareTask,TaskCategory,TaskStatus} from '../api/care';
import {useLanguage} from '../language';
import {Card,ErrorNotice} from './primitives';
import {CareReviewSheet} from './CareReviewSheet';

export function CareTaskSummary({onOpen,medications=[]}:{onOpen:()=>void;medications?:Array<Pick<MedicationSummary,'medication_id'|'display_name'>>}){
 const {t,language,preferences}=useLanguage();const [rows,setRows]=useState<CareTask[]|null>(null),[error,setError]=useState<unknown>(null);
 useEffect(()=>{let live=true;const refresh=()=>{void api.refreshFollowUps().then(value=>{if(live){setRows(value);setError(null);}}).catch(caught=>{if(live)setError(caught);});};refresh();window.addEventListener('pharmascan:reminder-refresh',refresh);return()=>{live=false;window.removeEventListener('pharmascan:reminder-refresh',refresh);};},[]);
 const when=(value:string)=>new Date(value).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:preferences.timezone});
 return <Card title="Medication follow-ups" hint="These are the follow-ups you recorded. Nothing is ordered or changed for you.">
  {error?<ErrorNotice error={error}/>
   :rows===null?<p className="notice" role="status">{t('Loading follow-ups…')}</p>
   :rows.length?<ul className="task-summary">{rows.slice(0,3).map(row=><li key={row.id}>
     <span className="task-summary__title">{row.source==='stock_estimate'?t(row.title):row.title}</span>
     {row.medication_id?<span className="task-summary__meta">{medications.find(med=>med.medication_id===row.medication_id)?.display_name??''}</span>:null}
     <span className="task-summary__meta">{when(row.due_at)} · {t(row.status)}</span>
    </li>)}</ul>
   :<p className="notice">{t('No open medication follow-ups.')}</p>}
  <button onClick={onOpen}>{t('View or add follow-up')}</button>
 </Card>;
}

export function CareTasksScreen({regimens}:{regimens:RegimenHistoryItem[]}){
 const {t,language,preferences}=useLanguage();const [rows,setRows]=useState<CareTask[]|null>(null),[pending,setPending]=useState<CareReview|null>(null),[error,setError]=useState<unknown>(null);
 const [category,setCategory]=useState<TaskCategory>('medication_review'),[title,setTitle]=useState(''),[due,setDue]=useState(''),[regimen,setRegimen]=useState(''),[notes,setNotes]=useState('');
 const [updating,setUpdating]=useState<CareTask|null>(null),[status,setStatus]=useState<TaskStatus>('completed'),[newDue,setNewDue]=useState('');
 const refresh=()=>api.careTasks().then(setRows);
 useEffect(()=>{let live=true;void api.careTasks().then(value=>{if(live)setRows(value);}).catch(caught=>{if(live)setError(caught);});return()=>{live=false;};},[]);
 const date=(value:string)=>new Date(value).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:preferences.timezone});
 function propose(){if(!title.trim()||!due)return;const time=new Date(due);if(Number.isNaN(time.getTime()))return;const selected=regimens.find(row=>row.regimen_id===regimen);setPending({action:'task',task:{id:crypto.randomUUID(),category,title:title.trim(),due_at:time.toISOString(),regimen_id:selected?.regimen_id??null,medication_id:selected?.medication_id??null,notes,confirmed:false}});}
 return <><Card title="Medication follow-ups" hint="These are the follow-ups you recorded. Nothing is ordered or changed for you.">{error?<ErrorNotice error={error}/>:null}
 <details><summary>{t('Add medication follow-up')}</summary><label className="field">{t('Follow-up type')}<select value={category} onChange={event=>setCategory(event.target.value as TaskCategory)}>{(['medication_review','medication_follow_up','refill','monitoring','adherence','symptom_follow_up','expiry_storage'] as const).map(value=><option key={value} value={value}>{t(value)}</option>)}</select></label>
 <label className="field">{t('Follow-up title')}<input maxLength={160} value={title} onChange={event=>setTitle(event.target.value)}/></label><label className="field">{t('Date and time')}<input type="datetime-local" value={due} onChange={event=>setDue(event.target.value)}/></label><p className="notice">{t('Time is entered in your device time zone. Leave blank for now.')}</p>
 <label className="field">{t('Related medication (optional)')}<select value={regimen} onChange={event=>setRegimen(event.target.value)}><option value="">{t('None')}</option>{regimens.map(row=><option key={row.regimen_id} value={row.regimen_id}>{row.display_name} · {t('version')} {row.version_no}</option>)}</select></label><label className="field">{t('Your note')}<textarea maxLength={1000} value={notes} onChange={event=>setNotes(event.target.value)}/></label><button disabled={!title.trim()||!due} onClick={propose}>{t('Review follow-up')}</button></details>
 {rows===null?<p>{t('Loading follow-ups…')}</p>:rows.length?rows.map(row=><article className="health-note" key={row.id}><h3>{row.source==='stock_estimate'?t(row.title):row.title}</h3>{row.medication_id?<p>{regimens.find(med=>med.medication_id===row.medication_id)?.display_name}</p>:null}<p>{t(row.category)} · {t(row.status)}</p><p>{date(row.due_at)}</p><p>{row.notes}</p><p className="notice">{t(row.source==='stock_estimate'?'Created from a low-stock estimate. Confirm your supply with your pharmacy.':'Patient-reported plan; not independently verified.')}</p>{!['completed','cancelled'].includes(row.status)?<button onClick={()=>{setUpdating(row);setNewDue('');setStatus('completed');}}>{t('Update follow-up')}</button>:null}<details><summary>{t('Follow-up history')}</summary>{row.history.map(event=><p key={event.id}>{date(event.recorded_at)} · {t(event.status)} · {date(event.due_at)} · {event.notes}</p>)}</details></article>):<p>{t('No medication follow-ups recorded.')}</p>}</Card>
 {updating?<Card title="Update follow-up"><h3>{updating.title}</h3><label className="field">{t('Status')}<select value={status} onChange={event=>setStatus(event.target.value as TaskStatus)}>{(['completed','contacted','deferred','cancelled'] as const).map(value=><option value={value} key={value}>{t(value)}</option>)}</select></label>{status==='deferred'?<label className="field">{t('New follow-up time')}<input type="datetime-local" value={newDue} onChange={event=>setNewDue(event.target.value)}/></label>:null}<button disabled={status==='deferred'&&!newDue} onClick={()=>setPending({action:'task_update',task_id:updating.id,task_update:{id:crypto.randomUUID(),expected_version:updating.version,status,due_at:newDue?new Date(newDue).toISOString():null,notes,confirmed:false}})}>{t('Review follow-up change')}</button><button onClick={()=>setUpdating(null)}>{t('Cancel')}</button></Card>:null}
 {pending?<CareReviewSheet proposal={pending} onCancel={()=>setPending(null)} onSaved={()=>{setPending(null);setUpdating(null);setTitle('');setNotes('');void refresh().catch(setError);}}/>:null}</>;
}
