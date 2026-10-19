import {useCallback,useEffect,useRef,useState,type FormEvent} from 'react';
import {ApiError,api,type CalendarExportOptions,type PlannedReminder, type PreferenceUpdate} from '../api/client';
import {useLanguage} from '../language';
import {PushNotificationSettings} from './PushNotificationSettings';
import type {CareTask} from '../api/care';
import {AutoDismissNotice,ErrorNotice} from './primitives';
import {careLabel} from './followUpCopy';
import {BottomSheet} from './BottomSheet';

const reminderLeadChoices=[0,15,30,60] as const;

export function CalendarExportAction(){
 const {t,preferences}=useLanguage();
 const [busy,setBusy]=useState(false),[dialogOpen,setDialogOpen]=useState(false),[error,setError]=useState<string|null>(null),[toastKey,setToastKey]=useState(0);
 const [range,setRange]=useState<CalendarExportOptions['range']>('30'),[customStart,setCustomStart]=useState(''),[customEnd,setCustomEnd]=useState('');
 const [includeMedications,setIncludeMedications]=useState(true),[includeTasks,setIncludeTasks]=useState(true);
 const exportLock=useRef(false);
 function dateInPatientTimezone(){
  const parts=new Intl.DateTimeFormat('en-CA',{timeZone:preferences.timezone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
  const values=Object.fromEntries(parts.map(part=>[part.type,part.value]));
  return `${values.year}-${values.month}-${values.day}`;
 }
 function addCalendarDays(value:string,days:number){const [year,month,day]=value.split('-').map(Number) as [number,number,number];return new Date(Date.UTC(year,month-1,day+days)).toISOString().slice(0,10);}
 function openDialog(){const today=dateInPatientTimezone();setRange('30');setCustomStart(today);setCustomEnd(today);setIncludeMedications(true);setIncludeTasks(true);setError(null);setDialogOpen(true);}
 function validateSelection():CalendarExportOptions|null{
  if(!includeMedications&&!includeTasks){setError('Select at least one type of reminder to export.');return null;}
  if(range!=='custom')return {range,include_medications:includeMedications,include_tasks:includeTasks};
  if(!customStart||!customEnd){setError('Choose a start and end date.');return null;}
  if(customEnd<customStart){setError('The end date must be on or after the start date.');return null;}
  const days=(Date.parse(`${customEnd}T00:00:00Z`)-Date.parse(`${customStart}T00:00:00Z`))/86400000+1;
  if(days>366){setError('Custom date ranges can include up to 366 days.');return null;}
  if(customStart<dateInPatientTimezone()){setError('Choose a date range that starts today or later.');return null;}
  return {range,start_date:customStart,end_date:customEnd,include_medications:includeMedications,include_tasks:includeTasks};
 }
 function exportErrorMessage(caught:unknown){
  if(caught instanceof ApiError&&caught.code==='INVALID_INPUT'){
   const known=['Calendar export exceeds 500 events. Choose a shorter date range or remove an export category.','No upcoming calendar events match the selected options.','Custom calendar ranges cannot exceed 366 days.','Calendar exports can only include today or future dates.'];
   if(known.includes(caught.message))return caught.message;
   return 'Calendar export could not be completed. Check the selected range and try again.';
  }
  return 'Calendar export could not be completed. Check the selected range and try again.';
 }
 async function exportCalendar(event:FormEvent<HTMLFormElement>){
  event.preventDefault();
  if(exportLock.current||busy)return;
  const options=validateSelection();if(!options)return;
  exportLock.current=true;
  setBusy(true);setError(null);
  try{
   const blob=await api.reminderCalendar(options);const content=await blob.text();
   const eventStarts=(content.match(/^BEGIN:VEVENT\r?$/gm)??[]).length,eventEnds=(content.match(/^END:VEVENT\r?$/gm)??[]).length;
   if(!content.trim()||!/^BEGIN:VCALENDAR\r?$/m.test(content)||!/^VERSION:2\.0\r?$/m.test(content)||!/^END:VCALENDAR\r?$/m.test(content)||eventStarts<1||eventStarts!==eventEnds)throw new Error('invalid-calendar-file');
   const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download='pharmascan-reminders.ics';link.hidden=true;document.body.append(link);link.click();link.remove();window.setTimeout(()=>URL.revokeObjectURL(url),1000);
   setDialogOpen(false);setToastKey(value=>value+1);
  }catch(caught){setError(caught instanceof Error&&caught.message==='invalid-calendar-file'?'The calendar file is empty or invalid. No download was started.':exportErrorMessage(caught));}
  finally{exportLock.current=false;setBusy(false);}
 }
 return <>
  <div className="calendar-export-action">
   <button type="button" onClick={openDialog}>{t('Export Calendar')}</button>
   <span>{t('Exported events will not sync automatically.')}</span>
  </div>
  {dialogOpen?<BottomSheet title={t('Export to Calendar')} onCancel={()=>setDialogOpen(false)} busy={busy} className="calendar-export-dialog">
   <p className="calendar-export-dialog__hint">{t('One-time calendar import. Changes in MediThread will not update this file.')}</p>
   <form onSubmit={event=>void exportCalendar(event)}>
    <fieldset className="calendar-export-options"><legend>{t('Time range')}</legend>
     {([['30','Next 30 days'],['90','Next 90 days'],['remaining','Full remaining course'],['custom','Custom date range']] as const).map(([value,label])=><label key={value}><input type="radio" name="calendar-range" value={value} checked={range===value} onChange={()=>{setRange(value);setError(null);}}/><span>{t(label)}</span></label>)}
    </fieldset>
    {range==='remaining'?<p className="calendar-export-dialog__hint">{t('Open-ended courses include the next 90 days.')}</p>:null}
    {range==='custom'?<div className="calendar-export-dates"><label>{t('Start date')}<input type="date" value={customStart} min={dateInPatientTimezone()} max={customEnd||undefined} onChange={event=>setCustomStart(event.target.value)} required/></label><label>{t('End date')}<input type="date" value={customEnd} min={customStart||dateInPatientTimezone()} max={customStart?addCalendarDays(customStart,365):undefined} onChange={event=>setCustomEnd(event.target.value)} required/></label></div>:null}
    <fieldset className="calendar-export-options calendar-export-options--content"><legend>{t('Export content')}</legend>
     <label><input type="checkbox" checked={includeMedications} onChange={event=>setIncludeMedications(event.target.checked)}/><span>{t('Medication reminders')}</span></label>
     <label><input type="checkbox" checked={includeTasks} onChange={event=>setIncludeTasks(event.target.checked)}/><span>{t('Care Task reminders')}</span></label>
    </fieldset>
    {error?<p className="calendar-export-dialog__error" role="alert">{t(error)}</p>:null}
    <div className="actions calendar-export-dialog__actions"><button type="button" className="ui-btn ui-btn--quiet" disabled={busy} onClick={()=>setDialogOpen(false)}>{t('Cancel')}</button><button type="submit" className="ui-btn ui-btn--primary" disabled={busy}>{t(busy?'Exporting calendar…':'Export .ics')}</button></div>
   </form>
  </BottomSheet>:null}
  {toastKey?<AutoDismissNotice key={toastKey}>{t('Calendar file generated. Import it into your calendar app.')}</AutoDismissNotice>:null}
 </>;
}

export function ReminderSettings({onOpenCareTask,multipleCareRemindersEnabled=false}:{onOpenCareTask?:(taskId:string)=>void;multipleCareRemindersEnabled?:boolean}){
 const {t,language,preferences,savePreferences}=useLanguage();
 const [rows,setRows]=useState<PlannedReminder[]|null>(null),[planFailed,setPlanFailed]=useState(false),[error,setError]=useState<unknown>(null);
 const [preferenceBusy,setPreferenceBusy]=useState(false),[toastKey,setToastKey]=useState(0),[toastCopy,setToastCopy]=useState('');
 const [tasks,setTasks]=useState<CareTask[]|null>(null),[taskFailed,setTaskFailed]=useState(false);
 const [remindersExpanded,setRemindersExpanded]=useState(false),[tasksExpanded,setTasksExpanded]=useState(false);
 const enabled=preferences.reminders_enabled!==false;
 const preferenceLock=useRef(false);
 const loadTasks=useCallback(async()=>{setTasks(null);setTaskFailed(false);try{setTasks(await api.careTasks());}catch{setTaskFailed(true);}},[]);
 useEffect(()=>{void loadTasks();},[loadTasks]);
 useEffect(()=>{let active=true;setRows(null);setPlanFailed(false);void api.reminderPlan().then(value=>{if(active)setRows(value);}).catch(caught=>{if(active){setPlanFailed(true);setError(caught);}});return()=>{active=false;};},[preferences.reminders_enabled,preferences.reminder_lead_minutes]);

 async function persistPreference(value:PreferenceUpdate,successMessage:string){
  if(preferenceLock.current)return;
  preferenceLock.current=true;
  setPreferenceBusy(true);setError(null);
  try{
   if(await savePreferences(value)){setToastCopy(successMessage);setToastKey(key=>key+1);}
   else setError(new Error('Could not save this setting. Your previous choice is unchanged.'));
  }finally{preferenceLock.current=false;setPreferenceBusy(false);}
 }
 const taskReminders=(tasks??[]).filter(task=>!['completed','cancelled'].includes(task.status)).flatMap(task=>(multipleCareRemindersEnabled?(task.reminder_offsets??(task.reminder_minutes===null?[]:[task.reminder_minutes??0])):(task.reminder_minutes===null?[]:[task.reminder_minutes??0])).map(lead=>({task,lead,at:Date.parse(task.due_at)-lead*60000}))).filter(row=>row.at>Date.now()).sort((a,b)=>a.at-b.at).slice(0,50);
 const uniqueTaskReminders=taskReminders.filter((row,index,all)=>all.findIndex(candidate=>candidate.task.id===row.task.id)===index);
 const firstTaskReminder=uniqueTaskReminders[0];
 const currentLead=preferences.reminder_lead_minutes;
 const supportedLead=reminderLeadChoices.some(value=>value===currentLead);
 return <div className="reminder-settings">
  <section className="card reminder-settings__section" aria-labelledby="reminder-schedule-title">
   <h2 id="reminder-schedule-title" className="card__title">{t('Reminder Schedule')}</h2>
   <div className="reminder-control-row">
    <div className="reminder-control-row__copy"><strong>{t('Medication Reminders')}</strong></div>
    <button type="button" role="switch" aria-label={t('Medication Reminders')} aria-checked={enabled} aria-busy={preferenceBusy} disabled={preferenceBusy} className="patient-switch" onClick={()=>void persistPreference({reminders_enabled:!enabled},'Medication reminder preference saved.')}><span/></button>
   </div>
   {preferenceBusy?<p className="reminder-status" role="status">{t('Saving medication reminder preference…')}</p>:null}
   {enabled?<label className="reminder-lead-control" htmlFor="reminder-lead-time"><span>{t('Reminder Lead Time')}</span>
    <select id="reminder-lead-time" disabled={preferenceBusy} value={currentLead} onChange={event=>{const value=Number(event.target.value);if(Number.isInteger(value)&&value>=0&&value<=120)void persistPreference({reminder_lead_minutes:value},'Reminder lead time saved.');}}>
     {!supportedLead?<option value={currentLead}>{t('Current setting: {minutes} minutes').replace('{minutes}',String(currentLead))}</option>:null}
     <option value={0}>{t('At scheduled time')}</option><option value={15}>{t('15 minutes before')}</option><option value={30}>{t('30 minutes before')}</option><option value={60}>{t('1 hour before')}</option>
    </select>
   </label>:null}

   <div className="reminder-settings__subsection">
    {rows?.length?<>
     <button type="button" className="reminder-disclosure" aria-expanded={remindersExpanded} aria-controls="upcoming-reminder-list" onClick={()=>setRemindersExpanded(value=>!value)}><span>{t('Upcoming Medication Reminders')} · {t(language==='zh'?'Upcoming reminder count: {count}':rows.length===1?'1 reminder':'{count} reminders').replace('{count}',String(rows.length))}</span><span aria-hidden="true">{remindersExpanded?'⌃':'⌄'}</span></button>
     {remindersExpanded?<div className="reminder-disclosure__body"><ul id="upcoming-reminder-list">{rows.map(row=><li key={row.occurrence_id}><strong>{row.medication_name}</strong><span>{new Date(row.remind_at).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:preferences.timezone})}</span></li>)}</ul></div>:null}
    </>:<h3>{t('Upcoming Medication Reminders')}</h3>}
    {rows===null?<p className="reminder-status" role="status">{t(planFailed?'Could not load reminders. Your medication records have not changed.':'Loading…')}</p>:rows.length===0?<p className="reminder-settings__hint">{t('No upcoming medication reminders.')}</p>:null}
   </div>
   <div className="reminder-settings__subsection">
    <h3>{t('Care Task Reminders')}</h3>
    {taskFailed?<div className="reminder-task-summary" role="status"><span>{t('Could not load Care Task reminders.')}</span><button type="button" className="reminder-link" onClick={()=>void loadTasks()}>{t('Try again')}</button></div>:tasks===null?<p className="reminder-status" role="status">{t('Loading…')}</p>:firstTaskReminder?<>
     <div className="reminder-task-summary"><span>{t(uniqueTaskReminders.length===1?'One upcoming Care Task':'{count} upcoming Care Tasks').replace('{count}',String(uniqueTaskReminders.length))} · {careLabel(firstTaskReminder.task.category,language,t)}</span>
      {uniqueTaskReminders.length===1?<button type="button" className="reminder-link" aria-label={t('View task: {title}').replace('{title}',firstTaskReminder.task.title)} onClick={()=>onOpenCareTask?.(firstTaskReminder.task.id)}>{t('View')} ›</button>:<button type="button" className="reminder-link" aria-expanded={tasksExpanded} aria-controls="care-task-reminder-list" onClick={()=>setTasksExpanded(value=>!value)}>{t(tasksExpanded?'Show fewer reminders':'View')} {tasksExpanded?'⌃':'›'}</button>}
     </div>
     {uniqueTaskReminders.length>1&&tasksExpanded?<ul id="care-task-reminder-list" className="reminder-task-list">{uniqueTaskReminders.map(({task,at})=><li key={task.id}><div><strong>{task.source==='stock_estimate'?t(task.title):task.title}</strong><span>{careLabel(task.category,language,t)} · {new Date(at).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:preferences.timezone})}</span></div><button type="button" className="reminder-link" aria-label={t('View task: {title}').replace('{title}',task.title)} onClick={()=>onOpenCareTask?.(task.id)}>{t('View')} ›</button></li>)}</ul>:null}
    </>:<p className="reminder-settings__hint">{t('No upcoming Care Task reminders.')}</p>}
   </div>
  </section>
  <PushNotificationSettings/>
  {error?<ErrorNotice error={error}/>:null}
  {toastKey?<AutoDismissNotice key={toastKey}>{t(toastCopy)}</AutoDismissNotice>:null}
 </div>;
}
