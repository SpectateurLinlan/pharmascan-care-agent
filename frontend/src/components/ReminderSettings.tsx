import {useEffect,useState} from 'react';
import {api,type PlannedReminder} from '../api/client';
import {useLanguage} from '../language';
import {PushNotificationSettings} from './PushNotificationSettings';
import {ErrorNotice} from './primitives';

export function ReminderSettings(){
 const {t,language,preferences,updatePreferences}=useLanguage();
 const [rows,setRows]=useState<PlannedReminder[]|null>(null),[planFailed,setPlanFailed]=useState(false),[error,setError]=useState<unknown>(null),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false);
 const [enabledDraft,setEnabledDraft]=useState<boolean|null>(null);
 const [showAll,setShowAll]=useState(false);

 useEffect(()=>{let active=true;setRows(null);setPlanFailed(false);void api.reminderPlan().then(value=>{if(active)setRows(value);}).catch(caught=>{if(active){setPlanFailed(true);setError(caught);}});return()=>{active=false;};},[preferences.reminders_enabled,preferences.reminder_lead_minutes]);
 async function run(action:()=>Promise<void>,success:string){setBusy(true);setError(null);setNotice('');try{await action();setNotice(success);}catch(caught){setError(caught);}finally{setBusy(false);}}
 return <><label className="consent"><input type="checkbox" disabled={enabledDraft!==null} checked={enabledDraft??preferences.reminders_enabled!==false} onChange={event=>{const value=event.target.checked;setEnabledDraft(value);void updatePreferences({reminders_enabled:value}).finally(()=>setEnabledDraft(null));}}/>{t('Enable medication reminders')}</label>
 <label className="field">{t('Reminder lead minutes')}<input type="number" min="0" max="120" value={preferences.reminder_lead_minutes} onChange={event=>{const value=Number(event.target.value);if(Number.isInteger(value)&&value>=0&&value<=120)void updatePreferences({reminder_lead_minutes:value});}}/></label>
 <p>{t('Reminders come from your reviewed active timed plans. As-needed medicines have no automatic fixed reminders.')}</p>
 <h3>{t('Upcoming reminders')}</h3>{rows===null?<p role="status">{t(planFailed?'Could not load reminders. Your medication records have not changed.':'Loading…')}</p>:rows.length?<><ul id="upcoming-reminder-list">{(showAll?rows:rows.slice(0,3)).map(row=><li key={row.occurrence_id}>{row.medication_name} · {new Date(row.remind_at).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:preferences.timezone})}</li>)}</ul>{rows.length>3?<button aria-expanded={showAll} aria-controls="upcoming-reminder-list" onClick={()=>setShowAll(value=>!value)}>{t(showAll?'Show fewer reminders':'View all upcoming reminders')}</button>:null}</>:<p>{t('No upcoming timed reminders. Review your plan and confirm specific times in Medicines.')}</p>}
 <p>{t('In-app reminders work while open or reopened. Background push also needs server configuration, a running scheduler and an authorized device.')}</p>
 <PushNotificationSettings/>
 <div className="actions"> <button disabled={busy} onClick={()=>void run(async()=>{const blob=await api.reminderCalendar();const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download='pharmascan-reminders.ics';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);},'Calendar downloaded. Import it into your calendar app.')}>{t('Add to Calendar')}</button></div>

 <p className="notice">{t('Calendar export covers the next 30 days within your course. This is a one-time import, not synchronization. After changing or stopping a plan, update or delete old events in your calendar.')}</p>
 <p>{t('On iPhone or iPad, Web Push requires iOS/iPadOS 16.4 or later and adding the app to the Home Screen. Delivery is not guaranteed by every device or browser.')}</p>
 {error?<ErrorNotice error={error}/>:null}{notice?<p role="status">{t(notice)}</p>:null}</>;
}
