import {useEffect,useState} from 'react';
import {api,type RegimenHistoryItem} from '../api/client';
import type {Barrier,BarrierKind,CareReview,CareTask} from '../api/care';
import {useLanguage} from '../language';
import {Card,ErrorNotice} from './primitives';
import {CareReviewSheet} from './CareReviewSheet';
import {MedicationDifficultiesPanel} from './MedicationDifficultiesPanel';

export function AdherenceBarriersScreen({regimens}:{regimens:RegimenHistoryItem[]}){
 const {t,language,preferences}=useLanguage();const [rows,setRows]=useState<Barrier[]|null>(null),[tasks,setTasks]=useState<CareTask[]>([]),[error,setError]=useState<unknown>(null),[pending,setPending]=useState<CareReview|null>(null);
 const [category,setCategory]=useState<BarrierKind>('forgetfulness'),[description,setDescription]=useState(''),[regimen,setRegimen]=useState(''),[action,setAction]=useState(''),[task,setTask]=useState('');
 const refresh=()=>api.barriers().then(setRows);
 useEffect(()=>{let live=true;void Promise.all([api.barriers(),api.careTasks(true)]).then(([barriers,followups])=>{if(live){setRows(barriers);setTasks(followups);}}).catch(caught=>{if(live)setError(caught);});return()=>{live=false;};},[]);
 const suggestions:Record<BarrierKind,string>={forgetfulness:'Review reminder settings',running_out:'Review stock and contact pharmacy',side_effect_concern:'Record symptoms and prepare professional review',scheduling:'Prepare timing questions for your pharmacist',unclear_instructions:'Review original label and ask your pharmacist',complexity:'Prepare a medication review',unsure_taken:'Check reported history; do not assume an extra dose',other:'Choose your own support action',prefer_not_to_say:'Choose your own support action'};
 return <Card title="Medication difficulties" hint="Missing reports do not mean missed doses. These are your experiences, not diagnoses.">{error?<ErrorNotice error={error}/>:null}
 <MedicationDifficultiesPanel regimens={regimens} barriers={rows??[]} onAddNote={suggestion=>{if(suggestion.category)setCategory(suggestion.category);setDescription(suggestion.description);setAction('');}}/>
 <label className="field">{t('What made medication management difficult?')}<select value={category} onChange={event=>{setCategory(event.target.value as BarrierKind);setAction('');}}>{(Object.keys(suggestions) as BarrierKind[]).map(value=><option key={value} value={value}>{t(value)}</option>)}</select></label><p className="notice">{t(suggestions[category])}</p>
 <label className="field">{t('Your description')}<textarea maxLength={1000} value={description} onChange={event=>setDescription(event.target.value)}/></label><label className="field">{t('Related medication (optional)')}<select value={regimen} onChange={event=>setRegimen(event.target.value)}><option value="">{t('None')}</option>{regimens.map(row=><option key={row.regimen_id} value={row.regimen_id}>{row.display_name} · {t('version')} {row.version_no}</option>)}</select></label>
 <label className="field">{t('Chosen support action')}<input maxLength={500} value={action} onChange={event=>setAction(event.target.value)}/></label><label className="field">{t('Linked follow-up (optional)')}<select value={task} onChange={event=>setTask(event.target.value)}><option value="">{t('None')}</option>{tasks.map(row=><option key={row.id} value={row.id}>{row.title}</option>)}</select></label>
 <button onClick={()=>setPending({action:'barrier',barrier:{id:crypto.randomUUID(),category,occurred_at:new Date().toISOString(),regimen_id:regimen||null,description,chosen_action:action,follow_up_task_id:task||null,confirmed:false}})}>{t('Review difficulty record')}</button>
 {rows===null?<p>{t('Loading records…')}</p>:rows.map(row=><article className="health-note" key={row.id}><h3>{t(row.category)}</h3><time>{new Date(row.occurred_at).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:preferences.timezone})}</time><p>{row.description}</p><p>{t('Chosen support action')}: {row.chosen_action||t('Not specified')}</p></article>)}
 {pending?<CareReviewSheet proposal={pending} onCancel={()=>setPending(null)} onSaved={()=>{setPending(null);setDescription('');void refresh().catch(setError);}}/>:null}</Card>;
}
