import {useCallback,useEffect,useRef,useState} from 'react';
import {api,type PushSubscriptionRecord} from '../api/client';
import {useLanguage} from '../language';
import {currentWebPush,disableWebPush,enableWebPush,pushSupported} from '../webPush';
import {AutoDismissNotice} from './primitives';
import {BottomSheet} from './BottomSheet';

type Platform='Windows'|'Android'|'iOS'|'macOS';
type RefreshSnapshot={current:Awaited<ReturnType<typeof currentWebPush>>|null;devices:PushSubscriptionRecord[]|null};
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
  <label className="field">{t('Your device')}<select value={platform} onChange={event=>setPlatform(event.target.value as Platform)}>{Object.keys(guides).map(value=><option key={value} value={value}>{value==='iOS'?'iPhone / iPad':value}</option>)}</select></label>
  <p>{t(guides[platform])}</p>
  <p>{t('If setup fails, use the main page switch to turn notifications off and on again after checking system permission. A changed notification key may require a new subscription.')}</p>
  <p>{t('Permission, subscription and server setup are separate. A successful test request does not prove device receipt. Offline devices, Focus and power-saving settings can delay notifications.')}</p>
 </details>;
}

function currentDeviceLabel(){
 const ua=typeof navigator==='undefined'?'':navigator.userAgent;
 const platform=/iPhone|iPad|iPod/i.test(ua)?'iPhone / iPad':/Android/i.test(ua)?'Android':/Windows/i.test(ua)?'Windows':/Macintosh|Mac OS/i.test(ua)?'macOS':/Linux/i.test(ua)?'Linux':'';
 const browser=/Edg\//i.test(ua)?'Edge':/Firefox\//i.test(ua)?'Firefox':/Chrome\//i.test(ua)?'Chrome':/Safari\//i.test(ua)?'Safari':'';
 return [platform,browser].filter(Boolean).join(' · ');
}

export function PushNotificationSettings(){
 const {t}=useLanguage();
 const [config,setConfig]=useState<Awaited<ReturnType<typeof api.pushConfig>>|null>(null);
 const [configStatus,setConfigStatus]=useState<'loading'|'ready'|'error'>('loading');
 const [devices,setDevices]=useState<PushSubscriptionRecord[]>([]),[devicesStatus,setDevicesStatus]=useState<'loading'|'ready'|'error'>('loading');
 const [current,setCurrent]=useState<Awaited<ReturnType<typeof currentWebPush>>|null>(null);
 const [currentStatus,setCurrentStatus]=useState<'loading'|'ready'|'error'>('loading');
 const [errorCopy,setErrorCopy]=useState<string|null>(null),[busy,setBusy]=useState(false),[setupOpen,setSetupOpen]=useState(false),[testAccepted,setTestAccepted]=useState(false),[testReceipt,setTestReceipt]=useState<'received'|'not-received'|null>(null),[toastKey,setToastKey]=useState(0),[toastCopy,setToastCopy]=useState(''),[confirmDisableAll,setConfirmDisableAll]=useState(false);
 const generation=useRef(0),alive=useRef(true),operationLock=useRef(false);
 const permission=typeof Notification==='undefined'?'Unsupported':Notification.permission==='granted'?'Allowed':Notification.permission==='denied'?'Blocked':'Not asked yet';
 const refresh=useCallback(async()=>{
  if(!alive.current)return null;
  const version=++generation.current;
  const [nextConfig,nextDevices,nextCurrent]=await Promise.allSettled([api.pushConfig(),api.pushSubscriptions(),currentWebPush()]);
  if(version!==generation.current)return null;
  if(nextConfig.status==='fulfilled'){setConfig(nextConfig.value);setConfigStatus('ready');}else setConfigStatus('error');
  if(nextDevices.status==='fulfilled'){setDevices(nextDevices.value);setDevicesStatus('ready');}else setDevicesStatus('error');
  if(nextCurrent.status==='fulfilled'){setCurrent(nextCurrent.value);setCurrentStatus('ready');}else setCurrentStatus('error');
  return {current:nextCurrent.status==='fulfilled'?nextCurrent.value:null,devices:nextDevices.status==='fulfilled'?nextDevices.value:null};
 },[]);
 useEffect(()=>{alive.current=true;void refresh();const focus=()=>void refresh();window.addEventListener('focus',focus);return()=>{alive.current=false;generation.current++;window.removeEventListener('focus',focus);};},[refresh]);
 async function run(action:()=>Promise<void>,successMessage:string,failureMessage:string,expectedEnabled?:boolean,verify?:(snapshot:RefreshSnapshot)=>boolean){
  if(operationLock.current)return;
  operationLock.current=true;
  setBusy(true);setErrorCopy(null);
  try{
   await action();
   if(expectedEnabled!==undefined){
    const confirmed=await refresh();if(!confirmed||confirmed.current?.enabled!==expectedEnabled)throw new Error(failureMessage);
   }
   if(verify){const confirmed=await refresh();if(!confirmed||!verify(confirmed))throw new Error(failureMessage);}
   if(alive.current){setToastCopy(successMessage);setToastKey(key=>key+1);}
  }catch{if(alive.current)setErrorCopy(failureMessage);}finally{operationLock.current=false;if(alive.current)setBusy(false);}
 }
 async function disableAllDevices(){
  if(operationLock.current)return;
  operationLock.current=true;setBusy(true);setErrorCopy(null);setConfirmDisableAll(false);
  try{
   await disableWebPush(true);
   const confirmed=await refresh();
   if(!confirmed?.current||!confirmed.devices||confirmed.current.enabled||confirmed.devices.some(row=>row.enabled))throw new Error('Could not verify all devices are off.');
   if(alive.current){setToastCopy('Push notifications are off on all account devices.');setToastKey(key=>key+1);}
  }catch{
   if(alive.current){await refresh();setErrorCopy('The all-device request did not complete. Some devices may already be off; refresh the list to confirm. Medication plans, adherence history, and reminder preferences are unchanged.');}
  }finally{operationLock.current=false;if(alive.current)setBusy(false);}
 }
 const deviceEnabled=current?.enabled===true;
 const canToggle=currentStatus==='ready'&&current!==null&&!busy&&(deviceEnabled||Boolean(configStatus==='ready'&&config?.available&&config.public_key&&pushSupported()&&permission!=='Blocked'));
 const testReason=configStatus==='loading'?t('Checking notification availability.'):configStatus==='error'?t('Could not check notification availability. Retry in Notification Settings.'):!config?.available||!config.public_key?t('This application is not configured for new device subscriptions.'):!config.test_available?t('A test notification cannot be sent from this page. Device subscription is managed separately.'):currentStatus==='loading'?t('Checking this device subscription.'):currentStatus==='error'?t('Could not check this device subscription. Retry in Notification Settings.'):!pushSupported()?t('This browser or device does not support background notifications.'):permission==='Blocked'?t('Notifications are blocked in your browser.'):permission!=='Allowed'?t('Allow browser notifications before sending a test.'):!deviceEnabled?t('Turn on device notifications before sending a test.'):!current?.id?t('This device subscription could not be confirmed.'):'';
 const canTest=Boolean(!busy&&configStatus==='ready'&&config?.test_available&&currentStatus==='ready'&&deviceEnabled&&current?.id&&pushSupported()&&permission==='Allowed');
 const deviceDescription=currentStatus==='loading'?t('Device notification status is being checked.'):currentStatus==='error'?t('Could not check this device subscription. Retry in Notification Settings.'):deviceEnabled?t('This device is subscribed to notifications.'):t('Device notifications are off.');
 const setupUnavailable=configStatus==='ready'&&(!config?.available||!config.public_key);
 const deviceSetupWarning=configStatus==='error'?t('Could not check notification availability. Retry in Notification Settings.'):setupUnavailable&&deviceEnabled?t('This device is already subscribed. New device setup is currently unavailable.'):setupUnavailable?t('This application is not configured for new device subscriptions.'):!pushSupported()?t('This browser or device does not support background notifications.'):permission==='Blocked'?t('Notifications are blocked in your browser. Change site or device notification settings, then refresh this page.'):'';
 async function sendTest(){
  if(!current?.id)return;
  await run(async()=>{
   const result=await api.testPush(current.id!,crypto.randomUUID());
   if(result.status!=='sent')throw new Error('The test could not be accepted. Check notification settings and try again.');
   setTestAccepted(true);setTestReceipt(null);
  },'The test was accepted by the service. Check this device; receipt is not confirmed.','The test notification request failed. No device receipt was confirmed.');
 }
 return <>
  <section className="card reminder-settings__section" aria-labelledby="device-notifications-title">
   <h2 id="device-notifications-title" className="card__title">{t('Device Notifications')}</h2>
   <div className="reminder-control-row">
    <div className="reminder-control-row__copy"><strong>{t('Receive Device Notifications')}</strong><span>{deviceDescription}</span></div>
    <button type="button" role="switch" aria-label={t('Receive Device Notifications')} aria-checked={deviceEnabled} disabled={!canToggle} aria-busy={busy} className="patient-switch" onClick={()=>void run(()=>deviceEnabled?disableWebPush():enableWebPush(config??undefined),deviceEnabled?'Device notifications turned off.':'Device subscription saved.','Could not update device notification settings. Your previous confirmed state is unchanged.',!deviceEnabled) }><span/></button>
   </div>
   {deviceSetupWarning?<p className="notification-warning">{deviceSetupWarning}</p>:null}
   {busy?<p className="reminder-status" role="status">{t('Saving device notification setting…')}</p>:null}
   <div className="device-notification-actions">
    <button className="device-notification-action" type="button" disabled={!canTest} onClick={()=>void sendTest()}><svg aria-hidden="true" viewBox="0 0 24 24"><path d="M18 9a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/></svg>{t('Test Notification')}</button>
    <button className="device-notification-action" type="button" onClick={()=>{setSetupOpen(true);setTestAccepted(false);setTestReceipt(null);}}><svg aria-hidden="true" viewBox="0 0 24 24"><path d="M12 3v2m0 14v2M3 12h2m14 0h2M5.6 5.6 7 7m10 10 1.4 1.4m0-12.8L17 7M7 17l-1.4 1.4M12 8v4l3 2"/></svg>{t('Notification Settings')}</button>
    {!canTest?<p className="device-notification-actions__reason">{testReason}</p>:null}
   </div>
   {errorCopy&&!setupOpen?<div className="notification-warning push-action-error" role="alert"><span>{t(errorCopy)}</span><button type="button" onClick={()=>setErrorCopy(null)}>{t('Dismiss')}</button></div>:null}
  </section>
  {toastKey?<AutoDismissNotice key={toastKey}>{t(toastCopy)}</AutoDismissNotice>:null}
  {setupOpen?<BottomSheet title={t('Notification Settings')} onCancel={()=>setSetupOpen(false)} busy={busy} className="push-setup-flow">
   <p>{t('Complete the available steps. Browser permission is requested only when you turn on device notifications.')}</p>
   <section className="push-management-section" aria-labelledby="push-current-device-title">
    <h3 id="push-current-device-title">{t('Current device')}</h3>
    <div className="push-current-device"><span>{currentDeviceLabel()||t('This device')}</span><strong role="status">{currentStatus==='loading'?t('Checking'):currentStatus==='error'?t('Could not check'):deviceEnabled?t('Enabled'):current?.browserSubscribed?t('Browser subscription present; notifications off'):t('Not subscribed')}</strong></div>
   </section>
   <ol className="push-setup-steps">
    <li><strong>{t('Background Push')}</strong><span>{configStatus==='loading'?t('Checking'):configStatus==='error'?t('Could not check'):setupUnavailable?t('Requires application setup'):t('Configured for device setup')}</span></li>
    <li><strong>{t('Browser notification permission')}</strong><span>{t(permission)}</span></li>
    <li><strong>{t('This device subscription')}</strong><span>{currentStatus==='loading'?t('Checking'):currentStatus==='error'?t('Could not check'):deviceEnabled?t('Enabled'):t('Off')}</span></li>
    <li><strong>{t('Test notification')}</strong><span>{testReceipt==='received'?t('You confirmed it arrived'):testReceipt==='not-received'?t('You did not receive it'):testAccepted?t('Service accepted; receipt not confirmed'):config?.test_available?t('Not tested'):t('Test unavailable in this application')}</span></li>
   </ol>
   {configStatus==='loading'?<p className="reminder-settings__hint">{t('Background notification availability has not been checked.')}</p>:configStatus==='error'?<p className="reminder-settings__hint">{t('Could not check notification availability. Retry in Notification Settings.')}</p>:setupUnavailable?<p className="notice">{t('Background notifications need Web Push configured for this application. Ask the application administrator to configure it. In-app reminders and calendar export remain available.')}</p>:<p className="reminder-settings__hint">{t('A device subscription does not guarantee delivery. Background delivery depends on the service and device settings.')}</p>}
   {config?.available&&currentStatus==='ready'&&!deviceEnabled&&permission!=='Blocked'&&pushSupported()?<p>{t('Close settings and use the device notification switch to continue setup.')}</p>:null}
   {!pushSupported()?<p>{t('This browser or device does not support background notifications.')}</p>:null}
   {permission==='Blocked'?<p>{t('Notifications are blocked in your browser. Change site or device notification settings, then refresh this page.')}</p>:null}
   {config?.available&&!config.test_available?<p className="reminder-settings__hint">{t('A test notification is not available here. The device subscription can still be set up; delivery has not been verified.')}</p>:null}
   {testAccepted?<div className="push-test-receipt"><p>{t('Check this device. The service response does not confirm receipt.')}</p><button type="button" onClick={()=>setTestReceipt('received')}>{t('I received it')}</button><button type="button" onClick={()=>setTestReceipt('not-received')}>{t('I did not receive it')}</button></div>:null}
   {errorCopy?<div className="notification-warning push-action-error" role="alert"><span>{t(errorCopy)}</span><button type="button" onClick={()=>setErrorCopy(null)}>{t('Dismiss')}</button></div>:null}
   <details className="push-management-section" id="notification-account-devices"><summary>{t('Account devices')} {devicesStatus==='ready'?` · ${devices.length}`:''}</summary>
    <p className="reminder-settings__hint">{t('Device names are not provided; entries are numbered from the saved subscriptions.')}</p>
    {devicesStatus==='ready'?devices.length?<ul className="push-devices">{devices.map((row,index)=><li key={row.id}><div><strong>{t('Device')} {index+1}{row.id===current?.id?` · ${t('This device')}`:''}</strong><span>{t(row.enabled?'Enabled':'Off')}</span></div>{row.enabled?(row.id===current?.id?<span className="reminder-settings__hint">{t('Use the device switch on the main page to manage this device.')}</span>:<button type="button" disabled={busy} onClick={()=>void run(()=>api.revokePushSubscription(row.id),'Device subscription turned off.','Could not confirm this device was turned off. Refresh the device list to check.',undefined,snapshot=>snapshot.devices?.every(item=>item.id!==row.id||!item.enabled)===true)}>{t('Turn off device')} {index+1}</button>):null}</li>)}</ul>:<p role="status">{t('No saved devices.')}</p>:<p role="status">{t(devicesStatus==='loading'?'Checking account devices.':'Could not load account devices. Refresh to try again.')}</p>}
   <button type="button" disabled={busy} onClick={()=>void refresh()}>{t('Refresh device list')}</button>
  </details>
  <NotificationGuide/>
  <details className="push-management-section" id="notification-troubleshooting"><summary>{t('Troubleshooting')}</summary>
   <dl className="push-status"><dt>{t('Browser permission')}</dt><dd>{t(permission)}</dd><dt>{t('This device subscription')}</dt><dd>{currentStatus==='loading'?t('Checking'):currentStatus==='error'?t('Could not check'):deviceEnabled?t('Enabled'):t('Off')}</dd><dt>{t('Application push setup')}</dt><dd>{configStatus==='loading'?t('Checking'):configStatus==='error'?t('Could not check'):config?.available?t('Configured'):t('Not configured')}</dd><dt>{t('Background delivery confirmation')}</dt><dd>{t('Not verified')}</dd></dl>
   <p className="reminder-settings__hint">{t('A device subscription does not guarantee delivery. Background delivery depends on the service and device settings.')}</p>
   <button type="button" disabled={busy} onClick={()=>void refresh()}>{t('Refresh notification status')}</button>
  </details>
  <section className="push-management-section push-account-wide-action" aria-labelledby="push-disable-all-title">
   <h3 id="push-disable-all-title">{t('Disable push on all devices')}</h3>
   <p>{t('This turns off saved push subscriptions on every device in this account, including this device. It does not change medication plans, adherence history, or reminder preferences.')}</p>
   {!confirmDisableAll?<button type="button" disabled={busy||devicesStatus!=='ready'||(!devices.some(row=>row.enabled)&&!deviceEnabled)} onClick={()=>setConfirmDisableAll(true)}>{t('Disable all device notifications')}</button>:<div role="group" aria-label={t('Confirm account-wide disable')}><p>{t('If the request fails partway, some devices may already be off. Refresh the list to check each status.')}</p><button type="button" disabled={busy} onClick={()=>void disableAllDevices()}>{busy?t('Disabling…'):t('Confirm disable all devices')}</button><button type="button" disabled={busy} onClick={()=>setConfirmDisableAll(false)}>{t('Cancel')}</button></div>}
  </section>
  <button type="button" disabled={busy} onClick={()=>setSetupOpen(false)}>{t('Close')}</button>
  </BottomSheet>:null}
 </>;
}
