import {useCallback,useEffect,useRef,useState,type ReactNode} from 'react';
import {api,type MedicationSummary} from '../api/client';
import {useLanguage} from '../language';
import {careTaskLocalDate} from '../careTaskCalendar';
import {LateDoseFollowUps} from './LateDoseFollowUps';
import {TodayMedicationCarousel} from './TodayMedicationCarousel';
import type {DoseFollowUp} from '../api/doseFollowUps';

type Attention=Awaited<ReturnType<typeof api.todayAttention>>;

/** Read-only attention groups; no inferred intake event or persisted closure. */
export function TodayAttentionOverview({medications,focusRegimenId,onHistory,children,lateReportsEnabled=true}:{lateReportsEnabled?:boolean;medications:MedicationSummary[];focusRegimenId:string|null;onHistory:()=>void;children:(medicine:MedicationSummary,onInteractionChange:(regimen:string,locked:boolean)=>void,todayOccurrenceIds:readonly string[])=>ReactNode}){
 const {t,language}=useLanguage();
 const [data,setData]=useState<Attention|null>(null),[failed,setFailed]=useState(false),[retry,setRetry]=useState(0),[todayOccurrenceIds,setTodayOccurrenceIds]=useState<string[]>([]);
 const locks=useRef(new Set<string>());const onInteractionChange=useCallback((regimen:string,locked:boolean)=>{if(locked)locks.current.add(regimen);else locks.current.delete(regimen);},[]);
 const onTodayItemsChange=useCallback((items:DoseFollowUp[])=>setTodayOccurrenceIds(items.map(item=>item.occurrence_id)),[]);
 const medicationKey=medications.map(row=>row.regimen_id).join('|');
 useEffect(()=>{let live=true;let pending=false;setData(null);setFailed(false);
  const refresh=async()=>{if(pending||document.visibilityState==='hidden')return;pending=true;try{const value=await api.todayAttention();if(live){setData(previous=>locks.current.size===0||previous===null?value:previous);setFailed(false);}}catch{if(live)setFailed(true);}finally{pending=false;}};
  // Skip work for an effect cleaned up before its initial microtask (StrictMode/navigation).
  void Promise.resolve().then(()=>{if(live)void refresh();});const timer=window.setInterval(()=>void refresh(),15000);document.addEventListener('visibilitychange',refresh);
  return()=>{live=false;window.clearInterval(timer);document.removeEventListener('visibilitychange',refresh);};
 },[medicationKey,retry]);
 const rows=new Map((data?.plans??[]).map(row=>[row.regimen_id,row]));
 const current=medications.filter(row=>(['pending','upcoming'].includes(rows.get(row.regimen_id)?.state??'')||!!rows.get(row.regimen_id)?.next_due_at));
 const prn=medications.filter(row=>rows.get(row.regimen_id)?.state==='as_needed');
 const unavailable=medications.filter(row=>rows.get(row.regimen_id)?.state==='unavailable');
 const recorded=medications.filter(row=>rows.get(row.regimen_id)?.state==='recorded').length;
 const patientDate=data?careTaskLocalDate(data.as_of,data.timezone):null;
 const formattedDate=patientDate?new Date(`${patientDate}T12:00:00Z`).toLocaleDateString(language==='zh'?'zh-CN':'en-SG',{timeZone:'UTC',month:'short',day:'numeric'}):null;
 return <section className="today-attention card" data-today-schedule-state={failed?'error':!data?'loading':unavailable.length||medications.some(row=>!rows.has(row.regimen_id))?'unavailable':'ready'} data-today-needs-dose={current.length>0?'true':'false'} aria-label={t("Today's medication")}>
  <header className="today-attention__heading"><h2>{t("Today's medication")}</h2>{formattedDate?<time dateTime={patientDate??undefined}>{formattedDate}</time>:null}</header>
  {failed?<section role="alert"><p>{t('Schedule unavailable. Try loading it again.')}</p><button onClick={()=>setRetry(value=>value+1)}>{t('Retry loading schedule')}</button></section>:!data?<p role="status">{t('Loading your reviewed schedule…')}</p>:<>
  {current.length?<TodayMedicationCarousel embedded medications={current} focusRegimenId={focusRegimenId}>{medicine=>children(medicine,onInteractionChange,todayOccurrenceIds)}</TodayMedicationCarousel>:!unavailable.length?<p className="today-schedule-empty" role="status">{t('No scheduled doses need attention right now.')}</p>:null}
  {unavailable.map(row=><p key={row.regimen_id} role="status"><strong>{row.display_name}</strong>: {t('This schedule cannot be assessed automatically. Review the saved plan in Medicines.')}</p>)}
  {recorded?<p>{t('Recorded plans today')}: {recorded} <button className="text-button" onClick={onHistory}>{t('View records')}</button></p>:null}
  {prn.length?<details className="today-prn"><summary>{t('As-needed medicines')} · {prn.length}</summary><p>{t('As-needed medicines have no daily required dose.')}</p><TodayMedicationCarousel embedded medications={prn} focusRegimenId={focusRegimenId}>{medicine=>children(medicine,onInteractionChange,todayOccurrenceIds)}</TodayMedicationCarousel></details>:null}
  </>}
  <div className="today-confirmation-region">
  <LateDoseFollowUps enabled={lateReportsEnabled} todayOnly onHistory={onHistory} onInteractionChange={onInteractionChange} onTodayItemsChange={onTodayItemsChange}/>
  </div>
 </section>;
}
