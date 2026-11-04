import {useEffect,useRef,useState} from 'react';
import {api,type PushSubscriptionRecord} from '../api/client';
import type {WorkflowView} from '../api/assistantWorkflows';
import {useLanguage} from '../language';
import {currentWebPush,disableWebPush,enableWebPush,pushSupported} from '../webPush';
import {BottomSheet} from './BottomSheet';
import {NotificationGuide} from './PushNotificationSettings';

type Snapshot={config:Awaited<ReturnType<typeof api.pushConfig>>;current:Awaited<ReturnType<typeof currentWebPush>>;devices:PushSubscriptionRecord[]};

/** Secrets and native IDs stay inside this patient page and the original native APIs. */
export function AssistantNotificationActions({view,busy,onDirtyChange}:{view:WorkflowView;busy:boolean;onDirtyChange?:((dirty:boolean)=>void)|undefined}){
 const {language,t}=useLanguage(),say=(en:string,zh:string)=>language==='zh'?zh:en;
 const [open,setOpen]=useState(false),[loading,setLoading]=useState(false),[working,setWorking]=useState(false),[error,setError]=useState(false),[needsCheck,setNeedsCheck]=useState(false);
 const [snapshot,setSnapshot]=useState<Snapshot|null>(null),[scope,setScope]=useState('current'),[message,setMessage]=useState<'enabled'|'disabled'|'accepted'|null>(null),[attempted,setAttempted]=useState(false),[receipt,setReceipt]=useState<boolean|null>(null);
 const [knownConfig,setKnownConfig]=useState<Snapshot['config']|null>(null);
 const live=useRef(true),pending=useRef(false),currentView=useRef(view);currentView.current=view;
 useEffect(()=>{live.current=true;return()=>{live.current=false;};},[]);
 useEffect(()=>{setOpen(false);setSnapshot(null);setKnownConfig(null);setError(false);setNeedsCheck(false);setMessage(null);},[view.revision,view.save_mode]);
 useEffect(()=>{onDirtyChange?.(open||working);return()=>onDirtyChange?.(false);},[open,working,onDirtyChange]);
 const operation=view.capability_id.split('.').at(-1),binding={task_id:view.task_id,expected_revision:view.revision};
 const isCurrent=()=>live.current&&currentView.current.task_id===view.task_id&&currentView.current.revision===view.revision&&currentView.current.save_mode==='allowed'&&!['suspended','cancelled','completed'].includes(currentView.current.state);
 async function refresh(){
  setLoading(true);
  try{const config=await api.pushConfig(binding);if(!isCurrent())return null;setKnownConfig(config);
   const [current,devices]=await Promise.all([currentWebPush(),api.pushSubscriptions()]);
   if(!isCurrent())return null;const next={config,current,devices};setSnapshot(next);setNeedsCheck(false);setError(false);return next;
  }catch{if(isCurrent()){setSnapshot(null);setError(true);}return null;}finally{if(live.current)setLoading(false);}
 }
 const permission=typeof Notification==='undefined'?'unsupported':Notification.permission,supported=pushSupported();
 const ready=Boolean(snapshot&&!loading&&!working&&!busy&&!needsCheck),testAllowed=view.visible_fields.test_send_allowed===true;
 const canEnable=Boolean(ready&&snapshot?.config.available&&snapshot.config.public_key&&supported&&permission!=='denied'&&!snapshot.current.enabled);
 const canDisable=Boolean(ready&&snapshot&&(scope==='all'?snapshot.current.browserSubscribed||snapshot.devices.some(row=>row.enabled):scope==='current'?snapshot.current.browserSubscribed||snapshot.current.enabled:snapshot.devices.some(row=>row.id===scope&&row.enabled)));
 const canTest=Boolean(ready&&!attempted&&testAllowed&&snapshot?.config.test_available&&snapshot.config.available&&supported&&permission==='granted'&&snapshot.current.enabled&&snapshot.current.id);
 async function confirm(){
  if(pending.current||!isCurrent()||!(operation==='subscribe'?canEnable:operation==='unsubscribe'?canDisable:canTest))return;
  pending.current=true;setWorking(true);setError(false);setMessage(null);
  try{if(operation==='subscribe'){
    await enableWebPush(snapshot!.config,{binding,isCurrent});const next=await refresh();if(!next?.current.enabled)throw new Error('Device state was not verified.');if(isCurrent())setMessage('enabled');
   }else if(operation==='unsubscribe'){
    if(scope==='current'||scope==='all')await disableWebPush(scope==='all',{binding,isCurrent,allowAllDevices:scope==='all'});
    else if(scope===snapshot?.current.id)await disableWebPush(false,{binding,isCurrent});else await api.revokePushSubscription(scope,binding);
    if(!isCurrent())return;const next=await refresh();const checked=next&&(scope==='all'?!next.current.enabled&&!next.current.browserSubscribed&&next.devices.every(row=>!row.enabled):scope==='current'||scope===snapshot?.current.id?!next.current.enabled&&!next.current.browserSubscribed:next.devices.every(row=>row.id!==scope||!row.enabled));
    if(!checked)throw new Error('Device revocation was not verified.');if(isCurrent())setMessage('disabled');
   }else{
    setAttempted(true);const result=await api.testPush(snapshot!.current.id!,crypto.randomUUID(),binding);
    if(!isCurrent())return;if(result.status!=='sent')throw new Error('No service acceptance was verified.');setMessage('accepted');setReceipt(null);
   }
  }catch{if(isCurrent()){setError(true);setNeedsCheck(true);}}finally{pending.current=false;if(live.current)setWorking(false);}
 }
 if(['suspended','cancelled','completed'].includes(view.state))return null;
 if(view.save_mode!=='allowed')return <p>{say('Save this task before changing device notifications.','请先保存此任务，再更改设备通知。')}</p>;
 const title=operation==='subscribe'?say('Enable device notifications','开启设备通知'):operation==='unsubscribe'?say('Turn off device notifications','关闭设备通知'):say('Test device notifications','测试设备通知');
 return <div><button disabled={busy||working} onClick={()=>{setOpen(true);void refresh();}}>{say('Open device notification action','打开设备通知操作')}</button>
  {open?<BottomSheet title={title} onCancel={()=>setOpen(false)} busy={working}>
   <p>{say('Browser permission, a saved subscription, service acceptance and device receipt are separate.','浏览器权限、保存订阅、服务接受发送和设备实际收到是不同状态。')}</p>
   {loading?<p role="status">{say('Checking device status…','正在核查设备状态…')}</p>:null}
   {knownConfig&&!knownConfig.available?<p>{say('Background notifications are not configured for this application.','此应用尚未配置后台通知。')}</p>:null}
   {snapshot?<><p>{snapshot.current.enabled?say('This device is subscribed; delivery has not been verified.','此设备已订阅，尚未验证通知送达。'):say('This device is not subscribed.','此设备尚未订阅。')}</p>
    <p>{say('Browser permission','浏览器权限')}: {permission==='granted'?say('Allowed','已允许'):permission==='denied'?say('Blocked','已禁止'):permission==='default'?say('Not requested','尚未请求'):say('Unsupported','不支持')}</p>
    {!supported?<p>{say('This browser does not support background notifications.','此浏览器不支持后台通知。')}</p>:null}
    {permission==='denied'?<p>{say('Notifications are blocked. Change browser settings before explicitly trying again.','通知已被禁止，请先更改浏览器设置，再明确重试。')}</p>:null}
    {operation==='unsubscribe'?<><label>{say('Turn off notifications for','关闭通知的范围')}<select value={scope} disabled={working} onChange={event=>setScope(event.target.value)}><option value="current">{say('This device','此设备')}</option><option value="all">{say('All saved devices','所有已保存设备')}</option>{snapshot.devices.map((row,index)=><option key={row.id} value={row.id} disabled={!row.enabled}>{say('Saved device','已保存设备')} {index+1}{row.id===snapshot.current.id?say(' (this device)','（此设备）'):''}</option>)}</select></label>{scope==='all'?<p>{say('This turns off every saved device in this account. A partial failure may leave some devices off; check the list before another action.','这会关闭此账户所有已保存设备的通知。部分失败时可能已有设备被关闭，请先核查列表。')}</p>:null}</>:null}
   </>:null}
   {operation==='test'&&!testAllowed?<p>{say('Sending a test notification has not been authorized for this workflow.','此办理尚未获准发送测试通知。')}</p>:null}
   {operation==='test'&&snapshot&&!snapshot.config.test_available?<p>{say('A notification test service is not available.','通知测试服务不可用。')}</p>:null}
   {operation==='test'&&attempted?<p>{say('A test was attempted for this task. Do not resend it; device receipt is not confirmed by the request.','本任务已尝试测试，请勿重复发送。请求本身不能确认设备实际收到。')}</p>:null}
   <button disabled={!(operation==='subscribe'?canEnable:operation==='unsubscribe'?canDisable:canTest)} onClick={()=>void confirm()}>{operation==='subscribe'?say('Confirm enable on this device','确认在此设备开启'):operation==='unsubscribe'?say('Confirm turn off notifications','确认关闭通知'):say('Confirm send one test notification','确认发送一条测试通知')}</button>
   <button disabled={loading||working} onClick={()=>void refresh()}>{say('Refresh device status','刷新设备状态')}</button>
   {error?<p role="alert">{say('The action or status check did not finish. Some device changes may already have happened. Check the current status before another action; no device receipt was confirmed.','操作或状态核查未完成，部分设备状态可能已改变。请先核查当前状态，再进行下一次操作，尚未确认设备收到通知。')}</p>:null}
   {message==='enabled'?<p role="status">{say('Device subscription saved. Delivery has not been verified.','设备订阅已保存，尚未验证通知送达。')}</p>:message==='disabled'?<p role="status">{say('The selected device notifications are off.','所选设备通知已关闭。')}</p>:message==='accepted'?<><p role="status">{say('The service accepted the test. Device receipt has not been verified.','服务已接受测试，尚未验证设备实际收到。')}</p><button disabled={working} onClick={()=>setReceipt(true)}>{say('I received it','我收到了')}</button><button disabled={working} onClick={()=>setReceipt(false)}>{say('I did not receive it','我没有收到')}</button>{receipt!==null?<p>{say('Your answer stays on this page and is not a system delivery receipt.','您的回答仅保留在此页面，不是系统送达回执。')}</p>:null}</>:null}
   <NotificationGuide/><button disabled={working} onClick={()=>setOpen(false)}>{t('Cancel')}</button>
  </BottomSheet>:null}
 </div>;
}
