import {api,type WorkflowPatientBinding} from './api/client';

export interface WebPushActionOptions {binding?:WorkflowPatientBinding;isCurrent?:()=>boolean;allowAllDevices?:boolean}
function checkCurrent(options?:WebPushActionOptions){if(options?.isCurrent&&!options.isCurrent())throw new Error('The device task changed. Reopen its current controls.');}

export function pushSupported():boolean {
  return window.isSecureContext&&'serviceWorker' in navigator&&'PushManager' in window&&'Notification' in window;
}
export async function enableWebPush(loadedConfig?:{available:boolean;public_key:string|null},options?:WebPushActionOptions):Promise<void> {
  checkCurrent(options);
  if(!pushSupported())throw new Error('Web Push is unsupported on this device.');
  const config=loadedConfig??await api.pushConfig();
  checkCurrent(options);
  if(!config.available||!config.public_key)throw new Error('Web Push is not configured on this server.');
  if(Notification.permission==='denied')throw new Error('Notifications are blocked. Follow the device guide to change system settings.');
  if(Notification.permission!=='granted'&&await Notification.requestPermission()!=='granted')throw new Error('Notification permission was not granted. In-app reminders still work.');
  checkCurrent(options);
  const registration=await navigator.serviceWorker.register('/sw.js',{scope:'/'});
  checkCurrent(options);
  await navigator.serviceWorker.ready;
  checkCurrent(options);
  const encoded=config.public_key.replace(/-/g,'+').replace(/_/g,'/');
  const bytes=Uint8Array.from(atob(encoded+'='.repeat((4-encoded.length%4)%4)),letter=>letter.charCodeAt(0));
  let subscription=await registration.pushManager.getSubscription();
  checkCurrent(options);
  const previousKey=subscription?.options?.applicationServerKey;
  if(subscription&&previousKey&&new Uint8Array(previousKey).some((value,index)=>value!==bytes[index])){
    if(options?.binding)throw new Error('First turn off this device in a separate notification action, then enable it again.');
    await disableWebPush();subscription=null;
  }
  subscription??=await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:bytes});
  checkCurrent(options);
  const value=subscription.toJSON();
  if(!value.endpoint||!value.keys?.p256dh||!value.keys.auth)throw new Error('Could not verify the push subscription.');
  const payload={endpoint:value.endpoint,keys:{p256dh:value.keys.p256dh,auth:value.keys.auth}};
  if(options?.binding)await api.savePushSubscription(payload,options.binding);else await api.savePushSubscription(payload);
  checkCurrent(options);
}

/** A read never registers, requests permission or re-enables a revoked device. */
export async function currentWebPush():Promise<{browserSubscribed:boolean;id:string|null;enabled:boolean}> {
  if(!pushSupported())return {browserSubscribed:false,id:null,enabled:false};
  const registration=await navigator.serviceWorker.getRegistration('/');
  const subscription=await registration?.pushManager.getSubscription();
  const value=subscription?.toJSON();
  if(!value?.endpoint||!value.keys?.p256dh||!value.keys.auth)return {browserSubscribed:false,id:null,enabled:false};
  const row=await api.currentPush({endpoint:value.endpoint,keys:{p256dh:value.keys.p256dh,auth:value.keys.auth}});
  return {browserSubscribed:true,id:row?.id??null,enabled:row?.enabled??false};
}
/** Revoke authenticated server subscriptions before removing the Auth session. */
export async function disableWebPush(allDevices=false,options?:WebPushActionOptions):Promise<void> {
  checkCurrent(options);
  if(allDevices&&options?.binding&&!options.allowAllDevices)throw new Error('Explicitly confirm all devices before this action.');
  const revoke=async()=>{const rows=await api.pushSubscriptions();checkCurrent(options);for(const row of rows)if(row.enabled){if(options?.binding)await api.revokePushSubscription(row.id,options.binding);else await api.revokePushSubscription(row.id);checkCurrent(options);}};
  if(!('serviceWorker' in navigator)){if(allDevices)await revoke();return;}
  const registration=await navigator.serviceWorker.getRegistration('/');
  checkCurrent(options);
  const subscription=await registration?.pushManager?.getSubscription();
  checkCurrent(options);
  if(allDevices){await revoke();}
  else if(subscription){const value=subscription.toJSON();if(value.endpoint&&value.keys?.p256dh&&value.keys.auth){
    const payload={endpoint:value.endpoint,keys:{p256dh:value.keys.p256dh,auth:value.keys.auth}};
    if(options?.binding)await api.revokeCurrentPush(payload,options.binding);else await api.revokeCurrentPush(payload);
    checkCurrent(options);
  }}
  if(subscription)await subscription.unsubscribe();
  checkCurrent(options);
}
