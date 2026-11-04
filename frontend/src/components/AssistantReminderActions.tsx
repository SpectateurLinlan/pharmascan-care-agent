import {useEffect,useRef,useState} from 'react';
import {api,type CalendarExportOptions} from '../api/client';
import type {JsonValue,WorkflowEventHandler,WorkflowView} from '../api/assistantWorkflows';
import {workflowChoice} from '../assistantWorkflowActions';
import {useLanguage} from '../language';
import {currentWebPush,pushSupported} from '../webPush';
import {CalendarExportAction} from './ReminderSettings';

function rows(value:JsonValue|undefined):Record<string,JsonValue>[] {
 return Array.isArray(value)?value.flatMap(row=>row&&typeof row==='object'&&!Array.isArray(row)?[row]:[]):[];
}

export function AssistantReminderActions({view,busy,onEvent,onDirtyChange}:{
 view:WorkflowView;busy:boolean;onEvent:WorkflowEventHandler;onDirtyChange?:((dirty:boolean)=>void)|undefined;
}){
 const {language}=useLanguage(),say=(en:string,zh:string)=>language==='zh'?zh:en;
 const [working,setWorking]=useState(false),[formOpen,setFormOpen]=useState(false),[error,setError]=useState(false);
 const [device,setDevice]=useState<{available:boolean;supported:boolean;enabled:boolean;permission:string}|null>(null);
 const live=useRef(true),pending=useRef(false),current=useRef(view);current.current=view;
 useEffect(()=>{live.current=true;return()=>{live.current=false;};},[]);
 useEffect(()=>{setDevice(null);setError(false);},[view.task_id,view.revision,view.save_mode]);
 useEffect(()=>{onDirtyChange?.(working||formOpen);return()=>onDirtyChange?.(false);},[working,formOpen,onDirtyChange]);
 const blocked=busy||working;
 async function exportCalendar(options:CalendarExportOptions){
  const next=await onEvent({event_id:crypto.randomUUID(),expected_revision:view.revision,kind:'provide_fields',values:{...options,start_date:options.range==='custom'?options.start_date??null:null,end_date:options.range==='custom'?options.end_date??null:null}});
  const valid=()=>live.current&&next&&next.task_id===view.task_id&&current.current.revision<=next.revision&&current.current.save_mode===next.save_mode;
  if(!next||next.revision<=view.revision||!valid())throw new Error('Check the current calendar task.');
  const result=await api.reminderCalendar(options,{task_id:view.task_id,expected_revision:next.revision});
  if(!valid())throw new Error('The calendar task changed.');return result;
 }
 async function readDevice(){
  if(blocked||pending.current)return;pending.current=true;setWorking(true);setError(false);setDevice(null);
  const revision=view.revision,mode=view.save_mode,valid=()=>live.current&&current.current.revision===revision&&current.current.save_mode===mode;
  try{const config=await api.pushConfig();if(!valid())return;
   const supported=pushSupported(),status=await currentWebPush();if(!valid())return;
   setDevice({available:config.available,supported,enabled:status.enabled,permission:typeof Notification==='undefined'?'unsupported':Notification.permission});
  }catch{if(valid())setError(true);}finally{pending.current=false;if(live.current)setWorking(false);}
 }
 if(['suspended','cancelled','completed'].includes(view.state))return null;
 if(view.capability_id==='reminder.calendar.export'){
  const fields=view.input_fields??{};
  const initial:CalendarExportOptions={range:(fields.range??'30') as CalendarExportOptions['range'],include_medications:fields.include_medications!==false,include_tasks:fields.include_tasks!==false,...(typeof fields.start_date==='string'?{start_date:fields.start_date}:{}),...(typeof fields.end_date==='string'?{end_date:fields.end_date}:{})};
  return <div><p>{say('Choose and download a one-time calendar file. This does not create dose records or import events into your device.','请选择并下载一次性日历文件，不会建立服药记录，也不会直接导入设备日历。')}</p><CalendarExportAction initialOptions={initial} port={exportCalendar} onDirtyChange={setFormOpen}/></div>;
 }
 if(view.capability_id==='notification.status')return <div>
  <p>{say('Check this browser and application setup. A status read does not request permission, subscribe a device or send a test.','核查当前浏览器和应用配置。状态查询不会请求权限、订阅设备或发送测试通知。')}</p>
  <button disabled={blocked} onClick={()=>void readDevice()}>{say('Check device notification status','核查设备通知状态')}</button>
  {working?<p role="status">{say('Checking device status…','正在核查设备状态…')}</p>:null}
  {error?<p role="alert">{say('Device status could not be checked. Retry explicitly; no notification was sent.','暂时无法核查设备状态，请明确重试，未发送通知。')}</p>:null}
  {device?<div aria-live="polite"><p>{device.enabled?say('This device is subscribed; delivery has not been verified.','此设备已订阅，尚未验证通知送达。'):say('This device is not subscribed.','此设备尚未订阅。')}</p>
   {!device.available?<p>{say('Background notifications are not configured for this application.','此应用尚未配置后台通知。')}</p>:null}
   {!device.supported?<p>{say('This browser does not support background notifications.','此浏览器不支持后台通知。')}</p>:null}
   <p>{say('Browser permission','浏览器权限')}: {device.permission==='granted'?say('Allowed','已允许'):device.permission==='denied'?say('Blocked','已禁止'):device.permission==='default'?say('Not requested','尚未请求'):say('Unsupported','不支持')}</p>
  </div>:null}
 </div>;
 const values=view.visible_fields,timezone=typeof values.timezone==='string'?values.timezone:'Asia/Singapore';
 const date=(value:JsonValue|undefined)=>typeof value==='string'&&Number.isFinite(Date.parse(value))?new Date(value).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:timezone}):'';
 const page=Number(values.page??0),pages=Number(values.page_count??1),medications=rows(values.medications),tasks=rows(values.care_tasks),snoozes=rows(values.snoozes);
 const apply=(fields:Record<string,JsonValue>)=>onEvent({event_id:crypto.randomUUID(),expected_revision:view.revision,kind:'provide_fields',values:fields});
 return <div><p>{say('Times follow your recorded timezone','时间按已登记时区显示')}: {timezone}</p>
  <div className="actions">{view.actions.flatMap(action=>action.kind==='choice'?action.options.map(option=><button key={option.value} disabled={blocked} onClick={()=>void onEvent(workflowChoice(view,action,option.value))}>{option.value==='1'?say('Next 1 day','未来 1 天'):say(`Next ${option.value} days`,`未来 ${option.value} 天`)}</button>):[])}</div>
  <p>{say('Projected reminders do not create dose records or prove that a dose was taken.','预计提醒不会建立剂次记录，也不表示已经服药。')}</p>
  {values.reminders_enabled===false?<p>{say('Medication reminder preferences are off.','药物提醒偏好已关闭。')}</p>:null}
  <h3>{say('Medication reminders','药物提醒')}</h3>{medications.length?<ul>{medications.map((row,index)=><li key={index}><strong>{String(row.medication_name)}</strong><p>{date(row.remind_at)}</p></li>)}</ul>:<p>{say('No medication reminders in this window.','此范围内没有药物提醒。')}</p>}
  {tasks.length?<><h3>{say('Care Task reminders','关怀事项提醒')}</h3><ul>{tasks.map((row,index)=><li key={index}>{String(row.title)} · {date(row.due_at)}</li>)}</ul></>:null}
  {snoozes.length?<><h3>{say('Saved snoozes','已保存的稍后提醒')}</h3><ul>{snoozes.map((row,index)=><li key={index}>{date(row.remind_at)}</li>)}</ul></>:null}
  {page>0?<button disabled={blocked} onClick={()=>void apply({page:page-1})}>{say('Previous page','上一页')}</button>:null}{page+1<pages?<button disabled={blocked} onClick={()=>void apply({page:page+1})}>{say('Next page','下一页')}</button>:null}
 </div>;
}
