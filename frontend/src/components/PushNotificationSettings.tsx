import {useCallback,useEffect,useRef,useState} from 'react';
import {api,type PushSubscriptionRecord} from '../api/client';
import {useLanguage} from '../language';
import {currentWebPush,disableWebPush,enableWebPush,pushSupported} from '../webPush';
import {ErrorNotice} from './primitives';

type Platform='Windows'|'Android'|'iOS'|'macOS';
const guides:Record<Platform,string>={
 Windows:'In Chrome or Edge, open the site controls beside the address bar and allow Notifications. In Windows Settings → System → Notifications, allow your browser. Keep the browser able to run in the background.',
 Android:'In Chrome, open this site → Site settings → Notifications → Allow. You can install the app from the browser menu. Also check Android Settings → Apps → Chrome → Notifications and battery restrictions.',
 iOS:'Use iOS/iPadOS 16.4 or later. In Safari, Share → Add to Home Screen. Open the installed app, then choose Enable on this device. Check Settings → Notifications for the installed app. An ordinary Safari tab is not enough.',
 macOS:'In Safari, use Safari Settings → Websites → Notifications; in Chrome or Edge, use the site controls. Also allow the browser or installed app in System Settings → Notifications. Focus modes may silence alerts.',
};

export function NotificationGuide(){
 const {t}=useLanguage();
 const [platform,setPlatform]=useState<Platform>(()=>/iPhone|iPad/i.test(navigator.userAgent)?'iOS':/Android/i.test(navigator.userAgent)?'Android':/Mac/i.test(navigator.userAgent)?'macOS':'Windows');
 return <details id="notification-guide"><summary>{t('Device notification guide')}</summary>
  <label className="field">{t('Your device')}<select value={platform} onChange={event=>setPlatform(event.target.value as Platform)}>{Object.keys(guides).map(value=><option key={value}>{value}</option>)}</select></label>
  <p>{t(guides[platform])}</p>
  <p>{t('If setup fails, turn off this device here, check system permission, then enable it again. A changed notification key may require a new subscription.')}</p>
  <p>{t('Permission, subscription and server setup are separate. A successful test request does not prove device receipt. Offline devices, Focus and power-saving settings can delay notifications.')}</p>
 </details>;
}

export function PushNotificationSettings(){
 const {t}=useLanguage();
 const [config,setConfig]=useState<Awaited<ReturnType<typeof api.pushConfig>>|null>(null);
 const [devices,setDevices]=useState<PushSubscriptionRecord[]>([]);
 const [current,setCurrent]=useState<Awaited<ReturnType<typeof currentWebPush>>|null>(null);
 const [error,setError]=useState<unknown>(null),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false),[loaded,setLoaded]=useState(false);
 const generation=useRef(0);
 const alive=useRef(true);
 const permission=typeof Notification==='undefined'?'Unsupported':Notification.permission==='granted'?'Allowed':Notification.permission==='denied'?'Blocked':'Not asked yet';
 const refresh=useCallback(async()=>{
  if(!alive.current)return;
  const version=++generation.current;
  try{
   const [nextConfig,nextDevices,nextCurrent]=await Promise.allSettled([api.pushConfig(),api.pushSubscriptions(),currentWebPush()]);
   if(version!==generation.current)return;
   setConfig(nextConfig.status==='fulfilled'?nextConfig.value:null);
   setDevices(nextDevices.status==='fulfilled'?nextDevices.value:[]);
   setCurrent(nextCurrent.status==='fulfilled'?nextCurrent.value:null);
   setLoaded(nextDevices.status==='fulfilled'&&nextCurrent.status==='fulfilled');
   const failure=[nextConfig,nextDevices,nextCurrent].find(value=>value.status==='rejected');
   setError(failure?.status==='rejected'?failure.reason:null);
  }catch(caught){if(version===generation.current){setError(caught);setLoaded(false);setCurrent(null);setDevices([]);}}
 },[]);
 useEffect(()=>{alive.current=true;void refresh();const focus=()=>void refresh();window.addEventListener('focus',focus);return()=>{alive.current=false;generation.current++;window.removeEventListener('focus',focus);};},[refresh]);
 async function run(action:()=>Promise<void>,message:string){
  setBusy(true);setError(null);setNotice('');
  try{await action();if(alive.current){setNotice(message);await refresh();}}catch(caught){if(alive.current)setError(caught);}finally{if(alive.current)setBusy(false);}
 }
 return <section aria-label={t('Device notifications')}>
  <h3>{t('Device notifications')}</h3>
  <dl className="push-status"><dt>{t('Browser permission')}</dt><dd>{t(permission)}</dd>
   <dt>{t('This device subscription')}</dt><dd>{t(!loaded?'Not checked':current?.enabled?'Enabled':current?.browserSubscribed?'Not linked to this account':'Off')}</dd>
   <dt>{t('Server notification configuration')}</dt><dd>{t(config===null?'Not checked':config.available?'Configured':'Not configured')}</dd>
   <dt>{t('Scheduled background delivery')}</dt><dd>{t('Not verified on this device')}</dd></dl>
  <p>{t('This device setting is separate from your medication reminder preference. Testing sends a generic notification and does not record medication intake.')}</p>
  <div className="actions">
   <button className="primary" disabled={busy||!loaded||!pushSupported()||!config?.available} onClick={()=>void run(()=>enableWebPush(config??undefined),'Push subscription saved. Device delivery still depends on the browser and scheduler.')}>{t('Enable on this device')}</button>
   <button disabled={busy||!current?.browserSubscribed} onClick={()=>void run(()=>disableWebPush(),'This device subscription is off. Browser permission is unchanged.')}>{t('Turn off this device')}</button>
   <button disabled={busy||!loaded||!current?.enabled||!current.id||!config?.test_available} onClick={()=>void run(async()=>{
    const result=await api.testPush(current!.id!,crypto.randomUUID());
    if(result.status!=='sent')throw new Error('The test was not confirmed by the push service. Check the guide and retry later.');
   },'The push service accepted the test. Check your device; receipt has not been verified.')}>{t('Send test notification')}</button>
   <button disabled={busy} onClick={()=>void refresh()}>{t('Refresh notification status')}</button>
  </div>
  {!pushSupported()?<p>{t('Web Push is unsupported on this device.')}</p>:null}
  {config?.available===false?<p>{t('Web Push is not configured on this server.')}</p>:null}
  {typeof Notification!=='undefined'&&Notification.permission==='denied'?<p>{t('Notifications are blocked. Follow the device guide to change system settings.')}</p>:null}
  <h4>{t('Account devices')}</h4>
  {loaded?devices.length?<ul className="push-devices">{devices.map((row,index)=><li key={row.id}>{t('Device')} {index+1}{row.id===current?.id?` · ${t('This device')}`:''} · {t(row.enabled?'Enabled':'Off')}
   {row.enabled?<button disabled={busy} onClick={()=>void run(()=>row.id===current?.id?disableWebPush():api.revokePushSubscription(row.id),'Device subscription disabled.')}>{t('Disable device')} {index+1}</button>:null}</li>)}</ul>:<p>{t('No saved devices.')}</p>:<p role="status">{t('Device status has not been checked. Refresh to retry.')}</p>}
  <button disabled={busy||!loaded} onClick={()=>void run(()=>disableWebPush(true),'Push subscriptions disabled for this account.')}>{t('Disable Web Push on all devices')}</button>
  <NotificationGuide/>
  {busy?<p role="status">{t('Updating notification settings…')}</p>:null}
  {notice?<p role="status">{t(notice)}</p>:null}{error?<ErrorNotice error={error}/>:null}
 </section>;
}
