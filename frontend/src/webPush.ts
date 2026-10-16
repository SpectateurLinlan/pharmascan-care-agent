import {api} from './api/client';

export function pushSupported():boolean {
  return window.isSecureContext&&'serviceWorker' in navigator&&'PushManager' in window&&'Notification' in window;
}
export async function enableWebPush(loadedConfig?:{available:boolean;public_key:string|null}):Promise<void> {
  if(!pushSupported())throw new Error('Web Push is unsupported on this device.');
  const config=loadedConfig??await api.pushConfig();
  if(!config.available||!config.public_key)throw new Error('Web Push is not configured on this server.');
  if(Notification.permission==='denied')throw new Error('Notifications are blocked. Follow the device guide to change system settings.');
  if(Notification.permission!=='granted'&&await Notification.requestPermission()!=='granted')throw new Error('Notification permission was not granted. In-app reminders still work.');
  const registration=await navigator.serviceWorker.register('/sw.js',{scope:'/'});
  await navigator.serviceWorker.ready;
  const encoded=config.public_key.replace(/-/g,'+').replace(/_/g,'/');
  const bytes=Uint8Array.from(atob(encoded+'='.repeat((4-encoded.length%4)%4)),letter=>letter.charCodeAt(0));
  let subscription=await registration.pushManager.getSubscription();
  const previousKey=subscription?.options?.applicationServerKey;
  if(subscription&&previousKey&&new Uint8Array(previousKey).some((value,index)=>value!==bytes[index])){
    await disableWebPush();subscription=null;
  }
  subscription??=await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:bytes});
  const value=subscription.toJSON();
  if(!value.endpoint||!value.keys?.p256dh||!value.keys.auth)throw new Error('Could not verify the push subscription.');
  await api.savePushSubscription({endpoint:value.endpoint,keys:{p256dh:value.keys.p256dh,auth:value.keys.auth}});
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
export async function disableWebPush(allDevices=false):Promise<void> {
  if(!('serviceWorker' in navigator)){if(allDevices)for(const row of await api.pushSubscriptions())if(row.enabled)await api.revokePushSubscription(row.id);return;}
  const registration=await navigator.serviceWorker.getRegistration('/');
  const subscription=await registration?.pushManager?.getSubscription();
  if(allDevices){for(const row of await api.pushSubscriptions())if(row.enabled)await api.revokePushSubscription(row.id);}
  else if(subscription){const value=subscription.toJSON();if(value.endpoint&&value.keys?.p256dh&&value.keys.auth){
    await api.revokeCurrentPush({endpoint:value.endpoint,keys:{p256dh:value.keys.p256dh,auth:value.keys.auth}});
  }}
  if(subscription)await subscription.unsubscribe();
}
