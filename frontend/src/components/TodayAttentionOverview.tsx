import {useCallback,useEffect,useRef,useState,type ReactNode} from 'react';
import {api,type MedicationSummary} from '../api/client';
import {useLanguage} from '../language';
import {LateDoseFollowUps} from './LateDoseFollowUps';
import {TodayMedicationCarousel} from './TodayMedicationCarousel';

type Attention=Awaited<ReturnType<typeof api.todayAttention>>;

/** Read-only attention groups; no inferred intake event or persisted closure. */
export function TodayAttentionOverview({medications,focusRegimenId,onHistory,children,lateReportsEnabled=true}:{lateReportsEnabled?:boolean;medications:MedicationSummary[];focusRegimenId:string|null;onHistory:()=>void;children:(medicine:MedicationSummary,onInteractionChange:(regimen:string,locked:boolean)=>void)=>ReactNode}){
 const {t}=useLanguage();
 const [data,setData]=useState<Attention|null>(null),[failed,setFailed]=useState(false),[retry,setRetry]=useState(0);
 const locks=useRef(new Set<string>());const onInteractionChange=useCallback((regimen:string,locked:boolean)=>{if(locked)locks.current.add(regimen);else locks.current.delete(regimen);},[]);
 const medicationKey=medications.map(row=>row.regimen_id).join('|');
 useEffect(()=>{let live=true;let version=0;setData(null);setFailed(false);
  const refresh=async()=>{if(document.visibilityState==='hidden')return;const request=++version;try{const value=await api.todayAttention();if(live&&request===version&&locks.current.size===0){setData(value);setFailed(false);}}catch{if(live&&request===version&&locks.current.size===0)setFailed(true);}};
  void refresh();const timer=window.setInterval(()=>void refresh(),15000);document.addEventListener('visibilitychange',refresh);
  return()=>{live=false;window.clearInterval(timer);document.removeEventListener('visibilitychange',refresh);};
 },[medicationKey,retry]);
 if(failed)return <section role="alert"><p>{t('Schedule unavailable. Try loading it again.')}</p><button onClick={()=>setRetry(value=>value+1)}>{t('Retry loading schedule')}</button></section>;
 if(!data)return <p role="status">{t('Loading your reviewed schedule…')}</p>;
 const rows=new Map(data.plans.map(row=>[row.regimen_id,row]));
 const current=medications.filter(row=>['pending','upcoming'].includes(rows.get(row.regimen_id)?.state??''));
 const prn=medications.filter(row=>rows.get(row.regimen_id)?.state==='as_needed');
 const unavailable=medications.filter(row=>rows.get(row.regimen_id)?.state==='unavailable');
 const recorded=medications.filter(row=>rows.get(row.regimen_id)?.state==='recorded').length;
 return <div className="today-attention">
  {current.length?<TodayMedicationCarousel medications={current} focusRegimenId={focusRegimenId}>{medicine=>children(medicine,onInteractionChange)}</TodayMedicationCarousel>:!unavailable.length?<p role="status">{t('No scheduled doses need attention right now.')}</p>:null}
  {unavailable.map(row=><p key={row.regimen_id} role="status"><strong>{row.display_name}</strong>: {t('This schedule cannot be assessed automatically. Review the saved plan in Medicines.')}</p>)}
  <LateDoseFollowUps enabled={lateReportsEnabled} onInteractionChange={onInteractionChange}/>
  {recorded?<p>{t('Recorded plans today')}: {recorded} <button className="text-button" onClick={onHistory}>{t('View records')}</button></p>:null}
  {prn.length?<details className="today-prn"><summary>{t('As-needed medicines')} · {prn.length}</summary><p>{t('As-needed medicines have no daily required dose.')}</p><TodayMedicationCarousel medications={prn} focusRegimenId={focusRegimenId}>{medicine=>children(medicine,onInteractionChange)}</TodayMedicationCarousel></details>:null}
 </div>;
}
