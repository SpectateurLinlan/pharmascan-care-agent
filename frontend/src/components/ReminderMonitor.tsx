/** Polling wakes presentation only. The server decides when an alert is due. */
import {useEffect,useMemo,useRef,useState} from 'react';
import {api,ApiError,type DoseReminderAlert} from '../api/client';
import {createBrowserReminderPort,type ReminderPort} from '../reminders';
import {useLanguage} from '../language';
export function ReminderMonitor({enabled,onReview,port}:{enabled:boolean;onReview:(regimenId:string)=>void;port?:ReminderPort}){
 const {language,t,preferences}=useLanguage();const [alert,setAlert]=useState<DoseReminderAlert|null>(null),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false);
 const tabOwner=useRef(crypto.randomUUID());
 const notificationLanguage=useRef(language);notificationLanguage.current=language;
 const leaseKey=(row:DoseReminderAlert)=>'pharmascan.reminder-owner:'+row.occurrence_id;
 const ownsLease=(row:DoseReminderAlert)=>{try{const value:unknown=JSON.parse(localStorage.getItem(leaseKey(row))??'null');return typeof value==='object'&&value!==null&&'owner' in value&&value.owner===tabOwner.current;}catch{return false;}};
 const takeLease=(row:DoseReminderAlert)=>{try{const value:unknown=JSON.parse(localStorage.getItem(leaseKey(row))??'null');if(typeof value==='object'&&value!==null&&'until' in value&&typeof value.until==='number'&&value.until>Date.now()&&!ownsLease(row))return false;}catch{/* Ignore a malformed expired local presentation lease. */}localStorage.setItem(leaseKey(row),JSON.stringify({owner:tabOwner.current,until:Date.now()+30000}));return true;};
 const revision=useRef(0),changing=useRef(false);
 const expires=(row:DoseReminderAlert)=>Date.parse(row.expires_at??new Date(Date.parse(row.due_at)+2*3600000).toISOString());
 const quietKey=(row:DoseReminderAlert)=>'pharmascan.reminder-quiet:'+row.occurrence_id;
 const isQuiet=(row:DoseReminderAlert)=>Number(localStorage.getItem(quietKey(row))??0)>Date.now();
 function close(until:number){if(!alert)return;revision.current++;localStorage.setItem(quietKey(alert),String(until));if(ownsLease(alert))localStorage.removeItem(leaseKey(alert));setAlert(null);active.current=null;}
 const shown=useRef(new Set<string>()),pending=useRef(false),active=useRef<DoseReminderAlert|null>(null);
 const notifications=useMemo(()=>port??createBrowserReminderPort(),[port]);
 const dialog=useRef<HTMLElement|null>(null);
 useEffect(()=>{if(!alert)return;const previous=document.activeElement;dialog.current?.focus();return()=>{if(previous instanceof HTMLElement)previous.focus();};},[alert]);
 useEffect(()=>{active.current=alert;},[alert]);
 useEffect(()=>{if(!enabled||!api.reminderAlerts)return;let live=true;let failures=0,nextAttemptAt=0;
  async function refresh(){if(changing.current||pending.current||Date.now()<nextAttemptAt||document.visibilityState==='hidden'||(!active.current&&document.querySelector('[aria-modal="true"]')))return;pending.current=true;try{
   const requestRevision=revision.current;const received=await api.reminderAlerts();if(!live||requestRevision!==revision.current)return;const rows=received.filter(row=>Date.parse(row.remind_at)<=Date.now()&&expires(row)>Date.now()&&!isQuiet(row));failures=0;nextAttemptAt=0;window.dispatchEvent(new Event('pharmascan:reminder-refresh'));if(!active.current&&document.querySelector('[aria-modal="true"]'))return;setNotice('');
   if(active.current){const current=rows.find(row=>row.key===active.current?.key);if(!current){active.current=null;setAlert(null);}else return;}
   const next=rows.find(row=>!shown.current.has(row.key)&&!sessionStorage.getItem('pharmascan.alert:'+row.key));
   if(next&&takeLease(next)){shown.current.add(next.key);sessionStorage.setItem('pharmascan.alert:'+next.key,'shown');active.current=next;setAlert(next);setNotice('');
    if(notifications.support()==='granted')void notifications.notify('MediThread',notificationLanguage.current==='zh'?'您有已安排的用药需要查看。':'You have a scheduled medication to review.').catch(()=>undefined);}
  }catch{if(live){failures=Math.min(failures+1,4);nextAttemptAt=Date.now()+Math.min(120000,15000*2**(failures-1));setNotice('Could not refresh reminders. Your medication records have not changed.');}}finally{pending.current=false;}}
  void refresh();const timer=setInterval(()=>void refresh(),15000);const wake=()=>void refresh();document.addEventListener('visibilitychange',wake);
  return()=>{live=false;clearInterval(timer);document.removeEventListener('visibilitychange',wake);};
 },[enabled,notifications]);
 useEffect(()=>{const expire=()=>{const row=active.current;if(row&&(Date.now()>=expires(row)||isQuiet(row)||!ownsLease(row))){if(ownsLease(row))localStorage.removeItem(leaseKey(row));active.current=null;setAlert(null);}else if(row){localStorage.setItem(leaseKey(row),JSON.stringify({owner:tabOwner.current,until:Date.now()+30000}));}};const timer=setInterval(expire,1000);window.addEventListener('storage',expire);return()=>{clearInterval(timer);window.removeEventListener('storage',expire);if(active.current&&ownsLease(active.current))localStorage.removeItem(leaseKey(active.current));};},[]);
 if(!alert)return notice?<p role="status" className="notice">{t(notice)}</p>:null;
 async function snooze(minutes:number){if(!alert)return;setBusy(true);changing.current=true;revision.current++;try{const saved=await api.snoozeReminder(alert.occurrence_id,minutes);close(Date.parse(saved.remind_at));}catch(error){setNotice(error instanceof ApiError?error.message:'Could not change your reminder. Please try again.');}finally{changing.current=false;setBusy(false);}}
 return <div className="modal-backdrop"><section ref={dialog} tabIndex={-1} onKeyDown={event=>{if(event.key==='Escape'&&!busy){close(expires(alert));}if(event.key==='Tab'){const controls=dialog.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)');const first=controls?.[0],last=controls?.[controls.length-1];if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}}}} className="reminder-dialog" role="dialog" aria-modal="true" aria-label={t('Medication reminder')}><h2>{t('You have a scheduled medication to review.')}</h2><p className="dose-name">{alert.medication_name}</p><p>{alert.dose_amount} {t(alert.dose_unit??'')} · {new Date(alert.due_at).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:preferences.timezone})}</p><p>{t('Review your recorded instructions. A reminder does not confirm intake.')}</p>
 <button className="primary" onClick={()=>{onReview(alert.regimen_id);close(expires(alert));}}>{t('Review medication')}</button>
 <div className="actions">{[15,30].map(minutes=><button key={minutes} disabled={busy} onClick={()=>void snooze(minutes)}>{minutes} {t('min later')}</button>)}<button disabled={busy} onClick={()=>close(expires(alert))}>{t('Dismiss')}</button></div>{notice?<p role="status">{t(notice)}</p>:null}</section></div>;
}
