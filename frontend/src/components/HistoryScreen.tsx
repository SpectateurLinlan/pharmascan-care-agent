import {useEffect,useRef,useState} from 'react';
import {useLanguage} from '../language';
import {api,type HistoryCatalogue,type MedicationHistoryFilters,type MedicationHistoryPage,type MedicationHistoryEntry,type MedicationHistoryRange} from '../api/client';
import {Card} from './primitives';
import {historyMedicationOptions,historyPlanLabel,historyName} from '../historyFilterLabels';

export function intakeLabel(value:string|null):string{
 return ({reported_taken:'You reported taking this dose',reported_not_taken:'You reported not taking this dose',unsure:'You were unsure'} as Record<string,string>)[value??'']??'This dose has no record of whether you took it yet.';
}

export function HistoryScreen(){
 const {t,language,preferences}=useLanguage();
 const [catalogue,setCatalogue]=useState<HistoryCatalogue|null>(null);
 const [search,setSearch]=useState('');
 const [filters,setFilters]=useState<MedicationHistoryFilters>({range_kind:'30'});
 const [page,setPage]=useState<MedicationHistoryPage|null>(null),[entries,setEntries]=useState<MedicationHistoryEntry[]>([]);
 const [loading,setLoading]=useState(false),[catalogueLoading,setCatalogueLoading]=useState(true),[error,setError]=useState<unknown>(null),[retry,setRetry]=useState(0);
 const generation=useRef(0),inFlight=useRef(false);
 const locale=language==='zh'?'zh-SG':'en-SG';
 const queryKey=JSON.stringify(filters);
 const valid=filters.range_kind!=='custom'||Boolean(filters.start&&filters.end&&filters.start<=filters.end);
 useEffect(()=>{let live=true;setCatalogueLoading(true);void api.historyCatalogue().then(data=>{if(live){setCatalogue(data);setError(null);}}).catch(caught=>{if(live)setError(caught);}).finally(()=>{if(live)setCatalogueLoading(false);});return()=>{live=false;};},[retry]);
 useEffect(()=>{
  const version=++generation.current;setEntries([]);setPage(null);
  if(!catalogue||!valid){setLoading(false);return;}
  const query=JSON.parse(queryKey) as MedicationHistoryFilters;
  inFlight.current=true;setLoading(true);setError(null);
  void api.medicationHistory(query).then(data=>{if(generation.current===version){setPage(data);setEntries(data.entries);}})
   .catch(caught=>{if(generation.current===version)setError(caught);})
   .finally(()=>{if(generation.current===version){inFlight.current=false;setLoading(false);}});
  return()=>{generation.current+=1;};
 },[catalogue,queryKey,valid,retry]);
 function change(next:MedicationHistoryFilters){
  if(next.range_kind===filters.range_kind&&next.medication_id===filters.medication_id&&next.medication_name===filters.medication_name&&next.regimen_id===filters.regimen_id&&next.start===filters.start&&next.end===filters.end)return;
  generation.current+=1;inFlight.current=false;setEntries([]);setPage(null);setError(null);setFilters(next);
 }
 async function more(){
  if(!page?.next_cursor||inFlight.current)return;
  const version=generation.current,cursor=page.next_cursor;inFlight.current=true;setLoading(true);setError(null);
  try{const data=await api.medicationHistory(filters,cursor);if(generation.current!==version)return;
   if(data.next_cursor===cursor)throw new Error('History changed. Restart the query.');
   setEntries(previous=>[...previous,...data.entries.filter(row=>!previous.some(old=>old.id===row.id))]);setPage(data);
  }catch(caught){if(generation.current===version)setError(caught);}finally{if(generation.current===version){inFlight.current=false;setLoading(false);}}
 }
 const options=catalogue?historyMedicationOptions(catalogue,t):[];
 const group=options.find(row=>row.id===filters.medication_name);
 const plans=(catalogue?.plans??[]).filter(row=>(!group||group.medication_ids.includes(row.medication_id))&&(!filters.medication_id||row.medication_id===filters.medication_id))
  .sort((a,b)=>Date.parse(b.effective_from??'0001-01-01')-Date.parse(a.effective_from??'0001-01-01')||b.id.localeCompare(a.id));
 const selectedPlan=plans.find(row=>row.id===filters.regimen_id);
 const date=(value:string)=>new Date(value).toLocaleString(locale,{timeZone:preferences.timezone});
 const planName=(id:string)=>{const plan=catalogue?.plans.find(row=>row.id===id);return plan?.effective_from?`${t('Plan effective from')}: ${new Date(plan.effective_from).toLocaleDateString(locale,{timeZone:preferences.timezone})}`:t('Start date not recorded');};
 const matching=options.filter(row=>row.label.normalize('NFKC').toLocaleLowerCase().includes(search.trim().normalize('NFKC').toLocaleLowerCase()));
 const visibleOptions=options.filter(row=>matching.some(match=>match.id===row.id)||row.id===filters.medication_name);
 const planLabels=plans.map(row=>({id:row.id,label:(!filters.medication_name?`${catalogue?.medications.find(med=>med.id===row.medication_id)?.display_name??''} \u00b7 `:'')+historyPlanLabel(row,t,locale,preferences.timezone)}));

 function chooseMedicine(value:string){change({range_kind:filters.range_kind==='plan'?'30':filters.range_kind,...(value?{medication_name:historyName(value)}:{}),...(filters.range_kind==='custom'?{start:filters.start??'',end:filters.end??''}:{})});}
 function choosePlan(value:string){const next={...filters};delete next.regimen_id;if(!value&&next.range_kind==='plan')next.range_kind='30';if(value)next.regimen_id=value;change(next);}
 function chooseRange(value:MedicationHistoryRange){const next={...filters,range_kind:value};delete next.start;delete next.end;change(next);}
 return <Card title="My medication records" hint="View saved dose reports and past scheduled doses by medicine and date."><div className="record-history">
  <div className="record-history__filters record-history__filters--grouped">
   <div className="field record-history__search"><label htmlFor="history-search">{t('Search medicines')}</label><input id="history-search" type="search" value={search} onChange={event=>setSearch(event.target.value)} placeholder={t('Search medicine names')} aria-describedby="history-search-count"/>
    {search?<button type="button" onClick={()=>{setSearch('');document.getElementById('history-search')?.focus();}}>{t('Clear search')}</button>:null}
    <small id="history-search-count" role="status">{catalogueLoading?t('Loading medicine filters...'):error&&!catalogue?t('Medicine history filters are unavailable.'): `${t('Matching medicines')}: ${matching.length}`}</small>
   </div>
   <div className="field"><label htmlFor="history-drug">{t('Medicine')}</label><select id="history-drug" value={filters.medication_name??''} onChange={event=>chooseMedicine(event.target.value)}>
    <option value="">{t('All medicines')}</option>{visibleOptions.map(row=><option key={row.id} value={row.id}>{row.label}</option>)}
   </select></div>
   <div className="field"><label htmlFor="history-medication">{t('Medication plan')}</label><select id="history-medication" value={filters.regimen_id??''} onChange={event=>choosePlan(event.target.value)}>
    <option value="">{t('All related plans')}</option>{planLabels.map(row=>{const duplicates=planLabels.filter(other=>other.label===row.label);return <option key={row.id} value={row.id}>{row.label}{duplicates.length>1?` \u00b7 ${t('Plan')} ${duplicates.findIndex(other=>other.id===row.id)+1}`:''}</option>;})}
   </select></div>
   <div className="field"><label htmlFor="history-range">{t('Date range')}</label><select id="history-range" value={filters.range_kind} onChange={event=>chooseRange(event.target.value as MedicationHistoryRange)}>
    {(['7','30','90'] as const).map(days=><option key={days} value={days}>{t(`Last ${days} days`)}</option>)}<option value="custom">{t('Custom dates')}</option><option value="all">{t('All available history')}</option>{selectedPlan?<option value="plan">{t('Selected plan effective period')}</option>:null}
   </select></div>
   {filters.range_kind==='custom'?<div className="record-history__dates"><label>{t('Start date')}<input type="date" value={filters.start??''} onChange={event=>change({...filters,start:event.target.value})}/></label><label>{t('End date')}<input type="date" min={filters.start} value={filters.end??''} onChange={event=>change({...filters,end:event.target.value})}/></label></div>:null}
  </div>
  <p className="notice">{t('Only stored dose reports and already generated past scheduled doses are shown. Missing schedules are not generated here; future doses are excluded.')}</p>
  {!valid?<p role="status">{t('Choose a valid start and end date.')}</p>:null}
  {page?<><p className="notice">{t('Query period')}: {page.window_start?date(page.window_start):t('All available history')} - {date(page.window_end)}</p>{page.missing_plan_start?<p className="notice">{t('The plan start date is missing; showing its available stored records.')}</p>:null}</>:null}
  {error?<div className="record-history__error" role="alert"><p>{t('Could not load medication history. Please retry.')}</p><button type="button" onClick={()=>setRetry(value=>value+1)}>{t('Retry history query')}</button></div>:null}
  {loading?<p role="status">{t('Loading your history...')}</p>:null}
  {page&&!entries.length&&!loading?<p>{t('No records in this range.')}</p>:null}
  {page?<p role="status">{t('Displayed records')}: {entries.length}</p>:null}
  <ul className="history">{entries.map(row=><li key={row.id}><div><strong>{row.display_name}</strong><p>{t(row.due_at?'Scheduled time':'Event time')}: {date(row.sort_time)}</p><small>{planName(row.regimen_id)}</small>
   {row.reported?<details><summary>{t('Report timestamps')}</summary>{row.event_time?<p>{t('Event time')}: {date(row.event_time)}</p>:null}{row.submitted_at?<p>{t('Submitted at')}: {date(row.submitted_at)}</p>:null}<p>{t('A report does not establish actual ingestion time.')}</p></details>:null}</div><span>{t(intakeLabel(row.reported?row.intake_status:null))}</span></li>)}</ul>
  {page?.next_cursor?<button className="record-history__more" disabled={loading} onClick={()=>void more()}>{t('Load more records')}</button>:null}
 </div></Card>;
}
