/** Polling wakes presentation only. The server decides when an alert is due. */
import {useEffect,useMemo,useRef,useState} from 'react';
import {api,type DoseReminderAlert} from '../api/client';
import {createBrowserReminderPort,type ReminderPort} from '../reminders';
import {useLanguage} from '../language';
export function ReminderMonitor({enabled,onReview,port}:{enabled:boolean;onReview:(regimenId:string)=>void;port?:ReminderPort}){
 const {language,t,preferences}=useLanguage();const [alert,setAlert]=useState<DoseReminderAlert|null>(null),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false);
 const shown=useRef(new Set<string>()),pending=useRef(false),active=useRef<DoseReminderAlert|null>(null);
 const notifications=useMemo(()=>port??createBrowserReminderPort(),[port]);
 const dialog=useRef<HTMLElement|null>(null);
 useEffect(()=>{if(!alert)return;const previous=document.activeElement;dialog.current?.focus();return()=>{if(previous instanceof HTMLElement)previous.focus();};},[alert]);
 useEffect(()=>{active.current=alert;},[alert]);
 useEffect(()=>{if(!enabled||!api.reminderAlerts)return;let live=true;let failures=0,nextAttemptAt=0;
  async function refresh(){if(pending.current||Date.now()<nextAttemptAt||document.visibilityState==='hidden'||(!active.current&&document.querySelector('[aria-modal="true"]')))return;pending.current=true;try{
   const rows=await api.reminderAlerts();if(!live)return;failures=0;nextAttemptAt=0;window.dispatchEvent(new Event('pharmascan:reminder-refresh'));if(!active.current&&document.querySelector('[aria-modal="true"]'))return;setNotice('');
   if(active.current){const current=rows.find(row=>row.key===active.current?.key);if(!current){active.current=null;setAlert(null);}else return;}
   const next=rows.find(row=>!shown.current.has(row.key)&&!sessionStorage.getItem('pharmascan.alert:'+row.key));
   if(next){shown.current.add(next.key);sessionStorage.setItem('pharmascan.alert:'+next.key,'shown');active.current=next;setAlert(next);setNotice('');
    if(notifications.support()==='granted')void notifications.notify('MediThread',language==='zh'?'您有已安排的用药需要查看。':'You have a scheduled medication to review.').catch(()=>undefined);}
  }catch{if(live){failures=Math.min(failures+1,4);nextAttemptAt=Date.now()+Math.min(120000,15000*2**(failures-1));setNotice('Could not refresh reminders. Your medication records have not changed.');}}finally{pending.current=false;}}
  void refresh();const timer=setInterval(()=>void refresh(),15000);const wake=()=>void refresh();document.addEventListener('visibilitychange',wake);
  return()=>{live=false;clearInterval(timer);document.removeEventListener('visibilitychange',wake);};
 },[enabled,notifications,language]);
 if(!alert)return notice?<p role="status" className="notice">{t(notice)}</p>:null;
 async function snooze(minutes:number){if(!alert)return;setBusy(true);try{await api.snoozeReminder(alert.occurrence_id,minutes);setAlert(null);active.current=null;}catch{setNotice('Could not change your reminder. Please try again.');}finally{setBusy(false);}}
 return <div className="modal-backdrop"><section ref={dialog} tabIndex={-1} onKeyDown={event=>{if(event.key==='Escape'&&!busy){setAlert(null);active.current=null;}if(event.key==='Tab'){const controls=dialog.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)');const first=controls?.[0],last=controls?.[controls.length-1];if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}}}} className="reminder-dialog" role="dialog" aria-modal="true" aria-label={t('Medication reminder')}><h2>{t('You have a scheduled medication to review.')}</h2><p className="dose-name">{alert.medication_name}</p><p>{alert.dose_amount} {t(alert.dose_unit??'')} · {new Date(alert.due_at).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:preferences.timezone})}</p><p>{t('Review your recorded instructions. A reminder does not confirm intake.')}</p>
 <button className="primary" onClick={()=>{onReview(alert.regimen_id);setAlert(null);active.current=null;}}>{t('Review medication')}</button>
 <div className="actions">{[15,30].map(minutes=><button key={minutes} disabled={busy} onClick={()=>void snooze(minutes)}>{minutes} {t('min later')}</button>)}<button disabled={busy} onClick={()=>{setAlert(null);active.current=null;}}>{t('Dismiss')}</button></div>{notice?<p role="status">{t(notice)}</p>:null}</section></div>;
}
