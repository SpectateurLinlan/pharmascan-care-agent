import {useMemo,useState} from 'react';
import type {RegimenHistoryItem} from '../api/client';
import {useLanguage} from '../language';
import {Card} from './primitives';
import {Icon} from './Icon';
import {regimenCourseGroups,plannedEndElapsed,plannedStartPending,type HistoricalRegimenGroup} from '../regimenHistoryModel';

type HistoryStatus='all'|'ended'|'active'|'upcoming';
type HistorySort='recent-ended'|'oldest-ended'|'recent-started'|'name-asc'|'name-desc';
export function RegimenHistoryScreen({regimens,onOpen,active=true}:{regimens:RegimenHistoryItem[];onOpen:(regimenId:string)=>void;active?:boolean}){
 const {t,preferences}=useLanguage();
 const [search,setSearch]=useState('');
 const [status,setStatus]=useState<HistoryStatus>('all');
 const [sort,setSort]=useState<HistorySort>('recent-ended');
 const groups=useMemo(()=>regimenCourseGroups(regimens),[regimens]);
 const visible=useMemo(()=>{
  const query=search.trim().toLocaleLowerCase();
  const filtered=groups.filter(({row})=>{
   if(query&&!row.display_name.toLocaleLowerCase().includes(query))return false;
   if(status==='active'&&(row.state!=='active'||plannedEndElapsed(row,preferences.timezone)||plannedStartPending(row,preferences.timezone)))return false;
   if(status==='upcoming'&&!plannedStartPending(row,preferences.timezone))return false;
   if(status==='ended'&&!['ended','superseded'].includes(row.state)&&!plannedEndElapsed(row,preferences.timezone))return false;
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
    <label className="field">{t('Filter by status')}<select value={status} onChange={event=>setStatus(event.target.value as HistoryStatus)}><option value="all">{t('All Courses')}</option><option value="ended">{t('Ended')}</option><option value="active">{t('Currently Tracked')}</option><option value="upcoming">{t('Upcoming course')}</option></select></label>
    <label className="field">{t('Sort regimens')}<select value={sort} onChange={event=>setSort(event.target.value as HistorySort)}><option value="recent-ended">{t('Most Recently Ended')}</option><option value="oldest-ended">{t('Oldest Ended')}</option><option value="recent-started">{t('Most Recently Started')}</option><option value="name-asc">{t('Name A-Z')}</option><option value="name-desc">{t('Name Z-A')}</option></select></label>
   </div>
   {visible.length?<div className="regimen-history-list">{visible.map(({row,versionCount})=><button className="regimen-history-card" type="button" key={row.regimen_id} onClick={()=>onOpen(row.regimen_id)}>
    <span className="regimen-history-card__header"><strong>{row.display_name}</strong><span className={`regimen-history-badge regimen-history-badge--${row.state}`}>{t(plannedEndElapsed(row,preferences.timezone)?'Course Ended as Scheduled':plannedStartPending(row,preferences.timezone)?'Upcoming course':row.state==='active'?'Currently Tracked':row.state==='superseded'?'Superseded':'Ended')}</span></span>
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
 if(sort==='name-desc')return b.display_name.localeCompare(a.display_name,undefined,{sensitivity:'base'})||a.regimen_id.localeCompare(b.regimen_id);
 const field=sort==='recent-started'?'course_start_date':'course_end_date';
 const first=a[field],second=b[field];
 if(!first&&!second)return tie();
 if(!first)return 1;
 if(!second)return -1;
 const byDate=sort==='oldest-ended'?first.localeCompare(second):second.localeCompare(first);
 return byDate||tie();
}

function courseDateLabel(row:RegimenHistoryItem,t:(key:string)=>string){
 if(row.course_start_date&&row.course_end_date)return `${row.course_start_date} ${t('to')} ${row.course_end_date}`;
 if(row.course_start_date)return `${row.course_start_date} ${t('to')} ${t('End date not recorded')}`;
 if(row.course_end_date)return `${t('Start date not recorded')} ${t('to')} ${row.course_end_date}`;
 return `${t('Start date not recorded')} ${t('to')} ${t('End date not recorded')}`;
}
