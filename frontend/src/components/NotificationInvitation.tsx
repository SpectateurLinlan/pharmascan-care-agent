import {useEffect,useState} from 'react';
import {api} from '../api/client';
import {useLanguage} from '../language';
import {enableWebPush} from '../webPush';
import {ErrorNotice} from './primitives';
import {Callout} from '../ui/primitives';

/**
 * Optional, once per owner/browser after an actual activation; never requests on mount.
 *
 * Presented as a message rather than a page section, because it appears on
 * whichever screen the patient lands on after activating a plan and must not
 * read as the screen's own content or push the page title down.
 */
export function NotificationInvitation({ownerId,onSettings}:{ownerId:string;onSettings:()=>void}){
 const {t}=useLanguage();
 const [open,setOpen]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState<unknown>(null);
 const [config,setConfig]=useState<Awaited<ReturnType<typeof api.pushConfig>>|null>(null);
 const key=`pharmascan.notification-invitation:${ownerId}`;
 useEffect(()=>{
  let live=true;
  const activated=()=>{
   if(!ownerId||localStorage.getItem(key))return;
   setOpen(true);
   void api.pushConfig().then(value=>{if(live)setConfig(value);}).catch(()=>{if(live)setConfig(null);});
  };
  window.addEventListener('pharmascan:plan-activated',activated);
  return()=>{live=false;window.removeEventListener('pharmascan:plan-activated',activated);};
 },[key,ownerId]);
 function dismiss(){localStorage.setItem(key,'shown');setOpen(false);}
 if(!open)return null;
 return <Callout tone="info" icon="bell" title="Your medication plan is ready">
  <p>{t('Would you like notifications on this device? You can set them up later in Me → Settings.')}</p>
  <div className="actions"><button className="primary" disabled={busy||!config?.available} onClick={()=>{
   setBusy(true);void enableWebPush(config??undefined).then(dismiss).catch(setError).finally(()=>setBusy(false));
  }}>{t('Enable on this device')}</button><button disabled={busy} onClick={dismiss}>{t('Later')}</button><button disabled={busy} onClick={()=>{dismiss();onSettings();}}>{t('View notification guide')}</button></div>
  {config?.available===false?<p>{t('Web Push is not configured on this server.')}</p>:null}
  {error?<ErrorNotice error={error}/>:null}
 </Callout>;
}
