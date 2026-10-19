import {useEffect,useState} from 'react';
import {api,type RegimenHistoryItem,type MedicationSummary} from '../api/client';
import type {CareTask,TaskStatus} from '../api/care';
import {careTaskLocalDate,careTaskMonthDays,shiftCareTaskMonth,sortCareTasks,taskView,type CareTaskStatusFilter,type CareTaskViewStatus} from '../careTaskCalendar';
import {localFields} from '../patientDateTime';
import {useLanguage} from '../language';
import {FollowUpError} from './FollowUpError';
import {BottomSheet} from './BottomSheet';
import {CareTaskForm} from './CareTaskForm';
import {careCopy,careLabel} from './followUpCopy';
import {Icon} from './Icon';
import '../ui/followups.css';

export {taskView};
export function todayTasks(rows:CareTask[],now=Date.now()){
 const actionable=rows.filter(row=>taskView(row,now)!=='completed');
 return actionable.sort((left,right)=>{
  const rank=(row:CareTask)=>taskView(row,now)==='pending'?0:1;
  if(rank(left)!==rank(right))return rank(left)-rank(right);
  const leftDue=Date.parse(left.due_at),rightDue=Date.parse(right.due_at);
  if(!Number.isFinite(leftDue))return Number.isFinite(rightDue)?1:0;
  if(!Number.isFinite(rightDue))return -1;
  return rank(left)===0?leftDue-rightDue:rightDue-leftDue;
 });
}
// Migration032 records complete title/reminder snapshots. Legacy history has no title;
// its DTO default reminder=null does not establish that a reminder was disabled.
function taskRoute(id:string){return `#care-tasks?task=${encodeURIComponent(id)}`;}
function selectedRoute(){return window.location.hash.startsWith('#care-tasks')?new URLSearchParams(window.location.hash.split('?')[1]??'').get('task'):null;}

export function CareTaskSummary({onOpen,medications=[],regimens=[],extended=true,multiple=false}:{onOpen:(taskId?:string)=>void;medications?:Array<Pick<MedicationSummary,'medication_id'|'display_name'>>;regimens?:RegimenHistoryItem[];extended?:boolean;multiple?:boolean}){
 const {t,language,preferences}=useLanguage();const [rows,setRows]=useState<CareTask[]|null>(null),[error,setError]=useState<unknown>(null),[now,setNow]=useState(Date.now()),[editing,setEditing]=useState(false);
 useEffect(()=>{let live=true;const refresh=()=>{void api.refreshFollowUps().then(value=>{if(live){setRows(value);setError(null);setNow(Date.now());}}).catch(caught=>{if(live)setError(caught);});};refresh();window.addEventListener('pharmascan:reminder-refresh',refresh);const timer=window.setInterval(()=>setNow(Date.now()),30000);return()=>{live=false;clearInterval(timer);window.removeEventListener('pharmascan:reminder-refresh',refresh);};},[]);
 const actionable=todayTasks(rows??[],now),visible=actionable.slice(0,3),pending=actionable.filter(row=>taskView(row,now)==='pending').length,overdue=actionable.filter(row=>taskView(row,now)==='overdue').length;
 const when=(value:string)=>{const instant=Date.parse(value);return Number.isFinite(instant)?new Date(instant).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:preferences.timezone,month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}):t('Date unavailable');};
 let today='';try{today=localFields(new Date(now).toISOString(),preferences.timezone).date;}catch{/* Leave date selection to the patient when the saved zone is unavailable. */}
 return <section className="card care-summary" aria-labelledby="today-care-tasks-title">
  <header className="care-summary__header"><h2 id="today-care-tasks-title" className="card__title">{t('Medication follow-ups')}</h2><button type="button" className="care-summary__add" onClick={()=>setEditing(true)}><Icon name="plus"/>{t('Add Follow-up')}</button></header>
  {error?<FollowUpError error={error} kind="read"/>:rows===null?<p role="status">{t('Loading follow-ups\u2026')}</p>:<>
   <div className="care-summary__counts"><span className="care-status">{t('Pending')} {pending}</span><span className="care-status care-status--overdue">{t('Overdue')} {overdue}</span></div>
   {visible.length?<ul className="care-list care-list--compact">{visible.map(row=><li key={row.id}><button className="care-list__button" onClick={()=>onOpen(row.id)}><span className="care-list__heading"><strong>{row.source==='stock_estimate'?t(row.title):row.title}</strong><span className={`care-status care-status--${taskView(row,now)}`}>{taskView(row,now)==='overdue'?t('Overdue'):t('Pending')}</span></span><span className="care-list__meta">{when(row.due_at)}{row.medication_id?` / ${medications.find(med=>med.medication_id===row.medication_id)?.display_name??''}`:''}</span></button></li>)}</ul>:<p className="care-summary__empty">{t('No pending medication follow-ups.')}</p>}
  </>}
  <button type="button" className="care-summary__calendar" onClick={()=>onOpen()}><Icon name="calendar"/>{t('View calendar and all follow-ups')}<Icon name="chevron-right"/></button>
  {editing?<CareTaskForm multiple={multiple} extended={extended} initialDate={today} regimens={regimens} onCancel={()=>setEditing(false)} onSaved={()=>setEditing(false)}/>:null}
 </section>;
}
export function CareTasksScreen({regimens,extended=true,multiple=false}:{regimens:RegimenHistoryItem[];extended?:boolean;multiple?:boolean}){
 const {t,language,preferences}=useLanguage(),c=careCopy(language);
 const [rows,setRows]=useState<CareTask[]|null>(null),[error,setError]=useState<unknown>(null),[status,setStatus]=useState<CareTaskStatusFilter>('all'),[displayView,setDisplayView]=useState<'calendar'|'list'>('calendar'),[now,setNow]=useState(Date.now());
 const todayDate=careTaskLocalDate(new Date(now).toISOString(),preferences.timezone)??'';
 const [selectedDate,setSelectedDate]=useState(()=>careTaskLocalDate(new Date(Date.now()).toISOString(),preferences.timezone)??'');
 const [month,setMonth]=useState(()=>careTaskLocalDate(new Date(Date.now()).toISOString(),preferences.timezone)?.slice(0,7)??'');
 const [active,setActive]=useState<string|null>(selectedRoute),[editing,setEditing]=useState<CareTask|'new'|null>(null),[change,setChange]=useState<TaskStatus|null>(null),[busy,setBusy]=useState(false),[updateKey,setUpdateKey]=useState('');
 const refresh=()=>api.careTasks().then(value=>{setRows(value);setError(null);setNow(Date.now());});
 useEffect(()=>{let live=true;void api.careTasks().then(value=>{if(live)setRows(value);}).catch(caught=>{if(live)setError(caught);});const navigation=()=>{setActive(selectedRoute());setChange(null);};window.addEventListener('hashchange',navigation);const timer=setInterval(()=>setNow(Date.now()),30000);return()=>{live=false;clearInterval(timer);window.removeEventListener('hashchange',navigation);};},[]);
 const when=(value:string)=>Number.isFinite(Date.parse(value))?new Date(value).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:preferences.timezone}):t('Date unavailable');
 const row=rows?.find(item=>item.id===active);
 const open=(id:string|null)=>{setActive(id);setChange(null);window.history.replaceState(window.history.state,'',id?taskRoute(id):'#care-tasks');};
 const label=(item:CareTask)=>item.status==='cancelled'?t('Cancelled'):taskView(item,now)==='completed'?t('Completed'):taskView(item,now)==='overdue'?t('Overdue'):t('Pending');
 const linked=(item:CareTask)=>regimens.find(plan=>plan.regimen_id===item.regimen_id)?.display_name??regimens.find(plan=>plan.medication_id===item.medication_id)?.display_name;
 const matchingRows=(rows??[]).filter(item=>status==='all'||taskView(item,now)===status);
 const tasksForDay=sortCareTasks(matchingRows.filter(item=>careTaskLocalDate(item.due_at,preferences.timezone)===selectedDate),now);
 const monthTasks=new Map<string,CareTask[]>();for(const item of matchingRows){const key=careTaskLocalDate(item.due_at,preferences.timezone);if(key?.startsWith(`${month}-`))monthTasks.set(key,[...(monthTasks.get(key)??[]),item]);}
 const days=careTaskMonthDays(month);
 const monthLabel=month?new Date(`${month}-01T12:00:00Z`).toLocaleDateString(language==='zh'?'zh-CN':'en-SG',{timeZone:'UTC',year:'numeric',month:'long'}):'';
 const weekdayKeys=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];
 const listGroups:CareTaskViewStatus[]=status==='all'?['overdue','pending','completed']:[status];
 const setMonthBy=(delta:number)=>{const next=shiftCareTaskMonth(month,delta);setMonth(next);setSelectedDate(todayDate.startsWith(`${next}-`)?todayDate:`${next}-01`);};
 const goToday=()=>{if(todayDate){setSelectedDate(todayDate);setMonth(todayDate.slice(0,7));}};
 async function changeStatus(){if(!row||!change||busy)return;setBusy(true);try{await api.updateCareTask(row.id,{id:updateKey,expected_version:row.version,status:change,due_at:null,notes:row.notes,confirmed:true});setChange(null);await refresh();window.dispatchEvent(new Event('pharmascan:reminder-refresh'));}catch(caught){setError(caught);}finally{setBusy(false);}}
 return <><section className="card care-task-page" aria-labelledby="care-task-page-title">
  <header className="care-task-page__header"><div><h2 id="care-task-page-title" className="card__title">{t('Medication follow-ups')}</h2><p className="card__hint">{t('Plan and manage your medication-related tasks.')}</p></div><button type="button" className="primary" onClick={()=>setEditing('new')}><span aria-hidden="true">+</span> {t('Add Follow-up')}</button></header>
  <div className="care-view-switch" role="group" aria-label={t('Care Task view')}><button type="button" aria-pressed={displayView==='calendar'} onClick={()=>setDisplayView('calendar')}>{t('Calendar')}</button><button type="button" aria-pressed={displayView==='list'} onClick={()=>setDisplayView('list')}>{t('List')}</button></div>
  <div className="care-status-filter care-status-filter--desktop" role="group" aria-label={t('Filter by status')}>{(['all','pending','overdue','completed'] as const).map(value=><button key={value} type="button" aria-pressed={status===value} onClick={()=>setStatus(value)}>{t(value==='all'?'All':value==='pending'?'Pending':value==='overdue'?'Overdue':'Completed')}</button>)}</div>
  <label className="care-status-filter__mobile">{t('Filter by status')}<select value={status} onChange={event=>setStatus(event.target.value as CareTaskStatusFilter)}><option value="all">{t('All')}</option><option value="pending">{t('Pending')}</option><option value="overdue">{t('Overdue')}</option><option value="completed">{t('Completed')}</option></select></label>
  {error?<div><FollowUpError error={error}/><button onClick={()=>{setChange(null);void refresh().catch(setError);}}>{t('Reload follow-ups')}</button></div>:null}
  {rows===null&&!error?<p role="status">{t('Loading follow-ups...')}</p>:rows&&displayView==='calendar'?<section className="care-calendar" aria-label={t('Care Task calendar')}>
   <div className="care-calendar__month"><button type="button" aria-label={t('Previous month')} onClick={()=>setMonthBy(-1)}><span aria-hidden="true">&#8249;</span></button><h3>{monthLabel}</h3><button type="button" aria-label={t('Next month')} onClick={()=>setMonthBy(1)}><span aria-hidden="true">&#8250;</span></button><button type="button" onClick={goToday}>{t('Today')}</button></div>
   <div className="care-calendar__grid" role="grid" aria-label={monthLabel}>{weekdayKeys.map(day=><span key={day} role="columnheader">{t(day)}</span>)}{days.map((day,index)=>day?<button key={day} type="button" role="gridcell" aria-selected={selectedDate===day} aria-label={`${new Date(`${day}T12:00:00Z`).toLocaleDateString(language==='zh'?'zh-CN':'en-SG',{timeZone:'UTC',year:'numeric',month:'long',day:'numeric'})}, ${monthTasks.get(day)?.length??0} ${t('Care Tasks')}`} className={`care-calendar__day${todayDate===day?' is-today':''}`} onClick={()=>setSelectedDate(day)} onKeyDown={event=>{const delta=event.key==='ArrowLeft'?-1:event.key==='ArrowRight'?1:event.key==='ArrowUp'?-7:event.key==='ArrowDown'?7:0;if(delta){event.preventDefault();const next=new Date(`${day}T12:00:00Z`);next.setUTCDate(next.getUTCDate()+delta);const nextKey=next.toISOString().slice(0,10);setSelectedDate(nextKey);setMonth(nextKey.slice(0,7));document.getElementById(`care-day-${nextKey}`)?.focus();}}} id={`care-day-${day}`}><span>{Number(day.slice(-2))}</span>{monthTasks.has(day)?<span className="care-calendar__markers" aria-hidden="true">{(['pending','overdue','completed'] as const).filter(value=>(monthTasks.get(day)??[]).some(item=>taskView(item,now)===value)).map(value=><i key={value} className={`care-calendar__marker care-calendar__marker--${value}`}/>)}</span>:null}</button>:<span key={`empty-${index}`} aria-hidden="true"/> )}</div>
   <ul className="care-calendar__legend" aria-label={t('Task status legend')}>{(['pending','overdue','completed'] as const).map(value=><li key={value}><i className={`care-calendar__marker care-calendar__marker--${value}`}/>{t(value==='pending'?'Pending':value==='overdue'?'Overdue':'Completed')}</li>)}</ul>
   {(rows??[]).some(item=>!careTaskLocalDate(item.due_at,preferences.timezone))?<p className="care-calendar__hint">{t('Tasks without a valid date are available in List view.')}</p>:null}
   <section className="care-calendar__agenda" aria-labelledby="care-agenda-title"><header><h3 id="care-agenda-title">{selectedDate?new Date(`${selectedDate}T12:00:00Z`).toLocaleDateString(language==='zh'?'zh-CN':'en-SG',{timeZone:'UTC',month:'long',day:'numeric'}) : t('Select a date')}</h3><span>{tasksForDay.length} {t('Care Tasks')}</span></header>{tasksForDay.length?<ul className="care-list care-list--compact">{tasksForDay.map(item=><li key={item.id}><button className="care-list__button" onClick={()=>open(item.id)}><span className="care-list__heading"><strong>{item.source==='stock_estimate'?t(item.title):item.title}</strong><span className={`care-status care-status--${taskView(item,now)}`}>{label(item)}</span></span><span className="care-list__meta">{when(item.due_at)} / {careLabel(item.category,language,t)}</span></button></li>)}</ul>:<p className="care-calendar__empty">{t('No follow-ups on this date.')}</p>}</section>
  </section>:rows&&displayView==='list'?<div className="care-list-view">{listGroups.map(group=>{const groupRows=sortCareTasks(matchingRows.filter(item=>taskView(item,now)===group),now);return <section key={group} aria-labelledby={`care-list-${group}`}><h3 id={`care-list-${group}`}>{t(group==='pending'?'Pending':group==='overdue'?'Overdue':'Completed')} <span className={`care-status care-status--${group}`}>{groupRows.length}</span></h3>{groupRows.length?<ul className="care-list">{groupRows.map(item=><li key={item.id}><button className="care-list__button" onClick={()=>open(item.id)}><span className="care-list__heading"><strong>{item.source==='stock_estimate'?t(item.title):item.title}</strong><span className={`care-status care-status--${taskView(item,now)}`}>{label(item)}</span></span><span>{when(item.due_at)}</span><span className="care-list__meta">{careLabel(item.category,language,t)}{linked(item)?` / ${linked(item)}`:''} ? {t('View and manage')}</span></button></li>)}</ul>:<p className="care-calendar__empty">{t('No follow-ups in this view.')}</p>}</section>;})}</div>:null}
 </section>
 {active&&rows&&!row?<p role="alert">{c('This follow-up is unavailable.','无法读取该事项。')}<button onClick={()=>open(null)}>{c('Back to list','返回列表')}</button></p>:null}
 {row&&!editing?<BottomSheet title={c('Follow-up details','用药跟进详情')} className="care-flow" onCancel={()=>open(null)} busy={busy}>
  <span className={`care-status care-status--${taskView(row,now)}`}>{label(row)}</span><h3>{row.source==='stock_estimate'?t(row.title):row.title}</h3><p>{careLabel(row.category,language,t)} · {when(row.due_at)} ({preferences.timezone})</p>{linked(row)?<p>{linked(row)}</p>:null}
  {row.reminder_offsets?.map(value=><p key={value}>{c('Reminder','\u63d0\u9192')}: {when(new Date(Date.parse(row.due_at)-value*60000).toISOString())}</p>)}{!row.reminder_offsets?.length?<p>{row.reminder_minutes===null?c('No reminder','不提醒'):`${c('Reminder','提醒时间')}: ${when(new Date(Date.parse(row.due_at)-(row.reminder_minutes??0)*60000).toISOString())}`}</p>:null}{row.notes?<p>{row.notes}</p>:null}
  {error?<><FollowUpError error={error}/><button onClick={()=>{setChange(null);void refresh().catch(setError);}}>{c('Reload follow-ups','重新读取用药跟进')}</button></>:null}
  {change?<><p>{c('Confirm this status change?','确认更改事项状态？')} {careLabel(change,language,t)}</p><div className="followup-actions"><button disabled={busy} onClick={()=>setChange(null)}>{t('Cancel')}</button><button className="primary" disabled={busy} onClick={()=>void changeStatus()}>{c('Confirm','确认')}</button></div></>:<div className="followup-actions">{taskView(row,now)!=='completed'?<><button className="primary" onClick={()=>{setChange('completed');setUpdateKey(crypto.randomUUID());}}>{c('Mark complete','标记完成')}</button><button onClick={()=>{setChange('cancelled');setUpdateKey(crypto.randomUUID());}}>{c('Cancel task','取消事项')}</button></>:null}<button disabled={!extended&&taskView(row,now)==='completed'} onClick={()=>setEditing(row)}>{taskView(row,now)==='completed'?c('Reopen and reschedule','重新打开并改期'):c('Edit or reschedule','编辑或改期')}</button></div>}
  <h3>{c('Change history','变更记录')}</h3><ol className="care-timeline">{row.history.map((event,index)=>{const previous=row.history[index-1];return <li key={event.id}><strong>{index===0?c('Task created','创建事项'):previous?.status!==event.status?`${c('Status','状态')}: ${careLabel(event.status,language,t)}`:c('Task updated','更新事项')}</strong><p>{when(event.recorded_at)}</p>{event.historical_confirmed?<p>{c('Historical date confirmed; no past reminder scheduled.','已确认历史日期，未安排过去的提醒。')}</p>:null}{!previous||previous.due_at!==event.due_at?<p>{previous?`${when(previous.due_at)} → `:''}{when(event.due_at)}</p>:null}{event.title&&previous?.title!==event.title?<p>{event.title}</p>:null}{event.category&&previous?.category!==event.category?<p>{careLabel(event.category,language,t)}</p>:null}{(event.regimen_id||previous?.regimen_id)&&event.regimen_id!==previous?.regimen_id?<p>{c('Linked medication plan','关联用药计划')}: {regimens.find(plan=>plan.regimen_id===event.regimen_id)?.display_name??c('None or unavailable','无关联或资料暂不可用')}</p>:null}{(previous?previous.notes!==event.notes:!!event.notes)?<p>{event.notes||c('Notes cleared','已清除备注')}</p>:null}{event.reminder_offsets&&JSON.stringify(event.reminder_offsets)!==JSON.stringify(previous?.reminder_offsets)?<p>{t('Reminder times')}: {event.reminder_offsets.map(value=>value===0?t('At scheduled time'):t('{minutes} minutes before').replace('{minutes}',String(value))).join(', ')}</p>:null}{!event.reminder_offsets&&event.title!=null&&'reminder_minutes' in event&&(!previous||event.reminder_minutes!==previous.reminder_minutes)?<p>{event.reminder_minutes===null?c('Reminder disabled','已关闭提醒'):`${c('Advance reminder (minutes)','提前提醒（分钟）')}: ${event.reminder_minutes}`}</p>:null}</li>;})}</ol>
  <button onClick={()=>open(null)}>{c('Close','关闭')}</button>
 </BottomSheet>:null}
 {editing?<CareTaskForm multiple={multiple} extended={extended} initialDate={editing==='new'&&displayView==='calendar'?selectedDate:undefined} task={editing==='new'?undefined:editing} regimens={regimens} onCancel={()=>setEditing(null)} onSaved={saved=>{setEditing(null);open(saved.id);void refresh().catch(setError);}}/>:null}
 </>;
}
