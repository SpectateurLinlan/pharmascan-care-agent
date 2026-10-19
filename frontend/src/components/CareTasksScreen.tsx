import {useEffect,useState} from 'react';
import {api,type RegimenHistoryItem,type MedicationSummary} from '../api/client';
import type {CareTask,TaskStatus} from '../api/care';
import {useLanguage} from '../language';
import {Card} from './primitives';
import {FollowUpError} from './FollowUpError';
import {BottomSheet} from './BottomSheet';
import {CareTaskForm} from './CareTaskForm';
import {careCopy,careLabel} from './followUpCopy';
import '../ui/followups.css';

export function taskView(task:CareTask,now=Date.now()):'pending'|'overdue'|'completed'{
 return ['completed','cancelled'].includes(task.status)?'completed':Date.parse(task.due_at)<now?'overdue':'pending';
}
export function todayTasks(rows:CareTask[],now=Date.now()){
 return rows.filter(row=>taskView(row,now)!=='completed').sort((a,b)=>Number(taskView(a,now)==='overdue')-Number(taskView(b,now)==='overdue')||Date.parse(a.due_at)-Date.parse(b.due_at));
}
// Migration032 records complete title/reminder snapshots. Legacy history has no title;
// its DTO default reminder=null does not establish that a reminder was disabled.
function taskRoute(id:string){return `#care-tasks?task=${encodeURIComponent(id)}`;}
function selectedRoute(){return window.location.hash.startsWith('#care-tasks')?new URLSearchParams(window.location.hash.split('?')[1]??'').get('task'):null;}

export function CareTaskSummary({onOpen,medications=[]}:{onOpen:(taskId?:string)=>void;medications?:Array<Pick<MedicationSummary,'medication_id'|'display_name'>>}){
 const {t,language,preferences}=useLanguage(),c=careCopy(language);const [rows,setRows]=useState<CareTask[]|null>(null),[error,setError]=useState<unknown>(null),[now,setNow]=useState(Date.now());
 useEffect(()=>{let live=true;const refresh=()=>{void api.refreshFollowUps().then(value=>{if(live){setRows(value);setError(null);setNow(Date.now());}}).catch(caught=>{if(live)setError(caught);});};refresh();window.addEventListener('pharmascan:reminder-refresh',refresh);const timer=window.setInterval(()=>setNow(Date.now()),30000);return()=>{live=false;clearInterval(timer);window.removeEventListener('pharmascan:reminder-refresh',refresh);};},[]);
 const when=(value:string)=>new Date(value).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:preferences.timezone});
 const visible=todayTasks(rows??[],now).slice(0,3);
 return <Card title="Medication follow-ups" hint={c('Plan and manage your medication-related tasks.','安排与管理您的用药相关事项。')}>
  {error?<FollowUpError error={error} kind="read"/>:rows===null?<p role="status">{c('Loading follow-ups…','正在读取用药跟进…')}</p>:visible.length?<>
   {(['pending','overdue'] as const).map(view=>{const items=visible.filter(row=>taskView(row,now)===view);return items.length?<section key={view}><h3>{view==='pending'?c('Pending','待处理'):c('Overdue','已过期')} <span className={`care-status care-status--${view}`}>{todayTasks(rows,now).filter(row=>taskView(row,now)===view).length}</span></h3><ul className="care-list">{items.map(row=><li key={row.id}><button className="care-list__button" onClick={()=>onOpen(row.id)}><strong>{row.source==='stock_estimate'?t(row.title):row.title}</strong><span className="care-list__meta">{when(row.due_at)} · {careLabel(row.category,language,t)}{row.medication_id?` · ${medications.find(med=>med.medication_id===row.medication_id)?.display_name??''}`:''}</span></button></li>)}</ul></section>:null;})}
  </>:<p>{c('No pending medication follow-ups.','暂无待处理的用药跟进。')}</p>}
  <button onClick={()=>onOpen()}>{c('View all follow-ups','查看全部用药跟进')}</button>
 </Card>;
}

export function CareTasksScreen({regimens,extended=true,multiple=false}:{regimens:RegimenHistoryItem[];extended?:boolean;multiple?:boolean}){
 const {t,language,preferences}=useLanguage(),c=careCopy(language);
 const [rows,setRows]=useState<CareTask[]|null>(null),[error,setError]=useState<unknown>(null),[view,setView]=useState<'pending'|'overdue'|'completed'>('pending'),[now,setNow]=useState(Date.now());
 const [active,setActive]=useState<string|null>(selectedRoute),[editing,setEditing]=useState<CareTask|'new'|null>(null),[change,setChange]=useState<TaskStatus|null>(null),[busy,setBusy]=useState(false),[updateKey,setUpdateKey]=useState('');
 const refresh=()=>api.careTasks().then(value=>{setRows(value);setError(null);setNow(Date.now());});
 useEffect(()=>{let live=true;void api.careTasks().then(value=>{if(live)setRows(value);}).catch(caught=>{if(live)setError(caught);});const navigation=()=>{setActive(selectedRoute());setChange(null);};window.addEventListener('hashchange',navigation);const timer=setInterval(()=>setNow(Date.now()),30000);return()=>{live=false;clearInterval(timer);window.removeEventListener('hashchange',navigation);};},[]);
 const when=(value:string)=>new Date(value).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:preferences.timezone});
 const row=rows?.find(item=>item.id===active);
 const open=(id:string|null)=>{setActive(id);setChange(null);window.history.replaceState(window.history.state,'',id?taskRoute(id):'#care-tasks');};
 const label=(item:CareTask)=>item.status==='cancelled'?t('cancelled'):taskView(item,now)==='completed'?c('Completed','已完成'):taskView(item,now)==='overdue'?c('Overdue','已过期'):c('Pending','待处理');
 const linked=(item:CareTask)=>regimens.find(plan=>plan.regimen_id===item.regimen_id)?.display_name??regimens.find(plan=>plan.medication_id===item.medication_id)?.display_name;
 async function changeStatus(){if(!row||!change||busy)return;setBusy(true);try{await api.updateCareTask(row.id,{id:updateKey,expected_version:row.version,status:change,due_at:null,notes:row.notes,confirmed:true});setChange(null);await refresh();window.dispatchEvent(new Event('pharmascan:reminder-refresh'));}catch(caught){setError(caught);}finally{setBusy(false);}}
 return <><Card title="Medication follow-ups" hint={c('Plan and manage your medication-related tasks.','安排与管理您的用药相关事项。')}>
  {error?<><FollowUpError error={error}/><button onClick={()=>{setChange(null);void refresh().catch(setError);}}>{c('Reload follow-ups','重新读取用药跟进')}</button></>:null}
  <button className="primary" onClick={()=>setEditing('new')}>{t('Add medication follow-up')}</button>
  <div className="care-tabs" aria-label={c('Follow-up views','用药跟进分类')}>{(['pending','overdue','completed'] as const).map(value=><button key={value} aria-pressed={view===value} onClick={()=>setView(value)}>{value==='pending'?c('Pending','待处理'):value==='overdue'?c('Overdue','已过期'):c('Completed','已完成')}</button>)}</div>
  {rows===null&&!error?<p role="status">{c('Loading follow-ups…','正在读取用药跟进…')}</p>:rows?<ul className="care-list">{rows.filter(item=>taskView(item,now)===view).map(item=><li key={item.id}><button className="care-list__button" onClick={()=>open(item.id)}><span className="care-list__heading"><strong>{item.source==='stock_estimate'?t(item.title):item.title}</strong><span className={`care-status care-status--${taskView(item,now)}`}>{label(item)}</span></span><span>{when(item.due_at)}</span><span className="care-list__meta">{careLabel(item.category,language,t)}{linked(item)?` · ${linked(item)}`:''} · {c('View and manage','查看与管理')} ›</span></button></li>)}{!rows.some(item=>taskView(item,now)===view)?<li>{c('No follow-ups in this view.','该分类暂无事项。')}</li>:null}</ul>:null}
 </Card>
 {active&&rows&&!row?<p role="alert">{c('This follow-up is unavailable.','无法读取该事项。')}<button onClick={()=>open(null)}>{c('Back to list','返回列表')}</button></p>:null}
 {row&&!editing?<BottomSheet title={c('Follow-up details','用药跟进详情')} className="care-flow" onCancel={()=>open(null)} busy={busy}>
  <span className={`care-status care-status--${taskView(row,now)}`}>{label(row)}</span><h3>{row.source==='stock_estimate'?t(row.title):row.title}</h3><p>{careLabel(row.category,language,t)} · {when(row.due_at)} ({preferences.timezone})</p>{linked(row)?<p>{linked(row)}</p>:null}
  {row.reminder_offsets?.map(value=><p key={value}>{c('Reminder','\u63d0\u9192')}: {when(new Date(Date.parse(row.due_at)-value*60000).toISOString())}</p>)}{!row.reminder_offsets?.length?<p>{row.reminder_minutes===null?c('No reminder','不提醒'):`${c('Reminder','提醒时间')}: ${when(new Date(Date.parse(row.due_at)-(row.reminder_minutes??0)*60000).toISOString())}`}</p>:null}{row.notes?<p>{row.notes}</p>:null}
  {error?<><FollowUpError error={error}/><button onClick={()=>{setChange(null);void refresh().catch(setError);}}>{c('Reload follow-ups','重新读取用药跟进')}</button></>:null}
  {change?<><p>{c('Confirm this status change?','确认更改事项状态？')} {careLabel(change,language,t)}</p><div className="followup-actions"><button disabled={busy} onClick={()=>setChange(null)}>{t('Cancel')}</button><button className="primary" disabled={busy} onClick={()=>void changeStatus()}>{c('Confirm','确认')}</button></div></>:<div className="followup-actions">{taskView(row,now)!=='completed'?<><button className="primary" onClick={()=>{setChange('completed');setUpdateKey(crypto.randomUUID());}}>{c('Mark complete','标记完成')}</button><button onClick={()=>{setChange('cancelled');setUpdateKey(crypto.randomUUID());}}>{c('Cancel task','取消事项')}</button></>:null}<button disabled={!extended&&taskView(row,now)==='completed'} onClick={()=>setEditing(row)}>{taskView(row,now)==='completed'?c('Reopen and reschedule','重新打开并改期'):c('Edit or reschedule','编辑或改期')}</button></div>}
  <h3>{c('Change history','变更记录')}</h3><ol className="care-timeline">{row.history.map((event,index)=>{const previous=row.history[index-1];return <li key={event.id}><strong>{index===0?c('Task created','创建事项'):previous?.status!==event.status?`${c('Status','状态')}: ${careLabel(event.status,language,t)}`:c('Task updated','更新事项')}</strong><p>{when(event.recorded_at)}</p>{event.historical_confirmed?<p>{c('Historical date confirmed; no past reminder scheduled.','已确认历史日期，未安排过去的提醒。')}</p>:null}{!previous||previous.due_at!==event.due_at?<p>{previous?`${when(previous.due_at)} → `:''}{when(event.due_at)}</p>:null}{event.title&&previous?.title!==event.title?<p>{event.title}</p>:null}{event.category&&previous?.category!==event.category?<p>{careLabel(event.category,language,t)}</p>:null}{(event.regimen_id||previous?.regimen_id)&&event.regimen_id!==previous?.regimen_id?<p>{c('Linked medication plan','关联用药计划')}: {regimens.find(plan=>plan.regimen_id===event.regimen_id)?.display_name??c('None or unavailable','无关联或资料暂不可用')}</p>:null}{(previous?previous.notes!==event.notes:!!event.notes)?<p>{event.notes||c('Notes cleared','已清除备注')}</p>:null}{event.reminder_offsets&&JSON.stringify(event.reminder_offsets)!==JSON.stringify(previous?.reminder_offsets)?<p>{t('Reminder times')}: {event.reminder_offsets.map(value=>value===0?t('At scheduled time'):t('{minutes} minutes before').replace('{minutes}',String(value))).join(', ')}</p>:null}{!event.reminder_offsets&&event.title!=null&&'reminder_minutes' in event&&(!previous||event.reminder_minutes!==previous.reminder_minutes)?<p>{event.reminder_minutes===null?c('Reminder disabled','已关闭提醒'):`${c('Advance reminder (minutes)','提前提醒（分钟）')}: ${event.reminder_minutes}`}</p>:null}</li>;})}</ol>
  <button onClick={()=>open(null)}>{c('Close','关闭')}</button>
 </BottomSheet>:null}
 {editing?<CareTaskForm multiple={multiple} extended={extended} task={editing==='new'?undefined:editing} regimens={regimens} onCancel={()=>setEditing(null)} onSaved={saved=>{setEditing(null);open(saved.id);void refresh().catch(setError);}}/>:null}
 </>;
}
