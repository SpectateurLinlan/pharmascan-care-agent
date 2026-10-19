import {useMemo,useState} from 'react';
import type {RegimenHistoryItem} from '../api/client';
import {useLanguage} from '../language';
import {Card} from './primitives';
import {Icon} from './Icon';
import {regimenCourseGroups,plannedEndElapsed,plannedStartPending,regimenStatusLabelKey,type HistoricalRegimenGroup} from '../regimenHistoryModel';

type HistoryStatus='all'|'ended'|'active';
type HistorySort='recent-started'|'oldest-started'|'name-asc';
export function RegimenHistoryScreen({regimens,onOpen,active=true}:{regimens:RegimenHistoryItem[];onOpen:(regimenId:string)=>void;active?:boolean}){
 const {t,preferences}=useLanguage();
 const [search,setSearch]=useState('');
 const [status,setStatus]=useState<HistoryStatus>('all');
 const [sort,setSort]=useState<HistorySort>('recent-started');
 const groups=useMemo(()=>regimenCourseGroups(regimens),[regimens]);
 const visible=useMemo(()=>{
  const query=search.trim().toLocaleLowerCase();
  const filtered=groups.filter(({row})=>{
   if(query&&!row.display_name.toLocaleLowerCase().includes(query))return false;
   if(status==='active'&&(row.state!=='active'||plannedEndElapsed(row,preferences.timezone)||plannedStartPending(row,preferences.timezone)))return false;
   if(status==='ended'&&row.state!=='ended'&&!plannedEndElapsed(row,preferences.timezone))return false;
   return true;
  });
  return filtered.sort((left,right)=>compareGroups(left,right,sort));
 },[groups,search,status,sort,preferences.timezone]);
 const hasHistory=groups.length>0;

 return <div hidden={!active} className="regimen-history-page" data-testid="regimen-history-page">
  <section aria-labelledby="regimen-history-title">
   <header className="regimen-history-header">
    <h1 id="regimen-history-title">{t('Regimen Records')}</h1>
    <p>{t('Review currently tracked and ended courses, including their plan versions.')}</p>
   </header>
   <div className="regimen-history-controls">
    <label className="field regimen-history-search">{t('Search medication name')}<input type="search" value={search} onChange={event=>setSearch(event.target.value)} placeholder={t('Search medication name')} /></label>
    <label className="field">{t('Filter by status')}<select value={status} onChange={event=>setStatus(event.target.value as HistoryStatus)}><option value="all">{t('All Courses')}</option><option value="active">{t('Currently Tracked')}</option><option value="ended">{t('Ended')}</option></select></label>
    <label className="field">{t('Sort regimens')}<select value={sort} onChange={event=>setSort(normalizeHistorySort(event.target.value))}><option value="recent-started">{t('Most Recently Started')}</option><option value="oldest-started">{t('Earliest Started')}</option><option value="name-asc">{t('Name A-Z')}</option></select></label>
   </div>
   {visible.length?<div className="regimen-history-list">{visible.map(({row,versionCount})=><button className="regimen-history-card" type="button" key={row.regimen_id} onClick={()=>onOpen(row.regimen_id)}>
    <span className="regimen-history-card__header"><strong>{row.display_name}</strong><span className={`regimen-history-badge regimen-history-badge--${row.state}`}>{t(regimenStatusLabelKey(row,preferences.timezone))}</span></span>
    <span className="regimen-history-card__date"><Icon name="calendar"/><span>{courseDateLabel(row,t)}</span></span>
    {versionCount>1?<span className="regimen-history-card__versions">{t('{count} plan versions').replace('{count}',String(versionCount))}</span>:null}
    <span className="regimen-history-card__action">{t('View Regimen Details')}<Icon name="chevron-right"/></span>
   </button>)}</div>:<Card title={t(hasHistory?'No regimens match these filters.':'No regimen records yet.')}><p>{t(hasHistory?'Try changing the search or status filter.':'Reviewed courses appear here; unfinished setup remains in medication review.')}</p></Card>}
  </section>
 </div>;
}

function compareGroups(left:HistoricalRegimenGroup,right:HistoricalRegimenGroup,sort:HistorySort){
 const a=left.row,b=right.row;
 const tie=()=>a.display_name.localeCompare(b.display_name,undefined,{sensitivity:'base'})||a.regimen_id.localeCompare(b.regimen_id);
 if(sort==='name-asc')return tie();
 const first=a.course_start_date,second=b.course_start_date;
 if(!first&&!second)return tie();
 if(!first)return 1;
 if(!second)return -1;
 const byDate=sort==='oldest-started'?first.localeCompare(second):second.localeCompare(first);
 return byDate||tie();
}

function normalizeHistorySort(value:string):HistorySort{
 return value==='oldest-started'||value==='name-asc'||value==='recent-started'?value:'recent-started';
}

function courseDateLabel(row:RegimenHistoryItem,t:(key:string)=>string){
 if(row.course_start_date&&row.course_end_date)return `${row.course_start_date} ${t('to')} ${row.course_end_date}`;
 if(row.course_start_date)return `${row.course_start_date} ${t('to')} ${t('End date not recorded')}`;
 if(row.course_end_date)return `${t('Start date not recorded')} ${t('to')} ${row.course_end_date}`;
 return `${t('Start date not recorded')} ${t('to')} ${t('End date not recorded')}`;
}
