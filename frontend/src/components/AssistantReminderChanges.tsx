import {useEffect,useRef,useState} from 'react';
import {api} from '../api/client';
import type {JsonValue,WorkflowEventHandler,WorkflowView} from '../api/assistantWorkflows';
import {useLanguage} from '../language';
import {BottomSheet} from './BottomSheet';
import {ReminderLeadSelect} from './ReminderLeadSelect';

const record=(value:JsonValue|undefined):Record<string,JsonValue>=>value&&typeof value==='object'&&!Array.isArray(value)?value:{};

export function AssistantReminderChanges({view,busy,onEvent,onDirtyChange,onClinicalChanged}:{view:WorkflowView;busy:boolean;onEvent:WorkflowEventHandler;onDirtyChange?:((dirty:boolean)=>void)|undefined;onClinicalChanged?:(()=>void)|undefined}){
 const {language,t,loadPreferences}=useLanguage(),say=(en:string,zh:string)=>language==='zh'?zh:en;
 const fields=view.input_fields??{},current=record(view.visible_fields.current_settings),snooze=view.capability_id==='reminder.snooze';
 const [enabled,setEnabled]=useState(fields.reminders_enabled===undefined?current.reminders_enabled!==false:fields.reminders_enabled===true);
 const [lead,setLead]=useState(Number(fields.reminder_lead_minutes??current.reminder_lead_minutes??0)),[minutes,setMinutes]=useState(String(fields.minutes??15));
 const [dirty,setDirty]=useState(false),[open,setOpen]=useState(false),[editing,setEditing]=useState(false),[working,setWorking]=useState(false),[uncertain,setUncertain]=useState(false),[error,setError]=useState(false);
 const pending=useRef(false),live=useRef(true);
 useEffect(()=>{live.current=true;return()=>{live.current=false;};},[]);
 useEffect(()=>{onDirtyChange?.(dirty||open||working);return()=>onDirtyChange?.(false);},[dirty,open,working,onDirtyChange]);
 const bound=view.save_mode==='allowed'&&view.state==='awaiting_confirmation'&&view.result_ref?.kind==='reminder_review';
 const blocked=busy||working;
 const timezone=String(view.visible_fields.timezone??'Asia/Singapore'),when=(value:JsonValue|undefined)=>typeof value==='string'?new Date(value).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:timezone}):'';
 async function dispatch(values:Record<string,JsonValue>){
  if(pending.current||blocked)return;pending.current=true;setWorking(true);setError(false);
  try{await onEvent({event_id:crypto.randomUUID(),expected_revision:view.revision,kind:'provide_fields',values});if(live.current)setDirty(false);}
  catch{if(live.current)setError(true);}finally{pending.current=false;if(live.current)setWorking(false);}
 }
 async function check(){
  const next=await onEvent({event_id:crypto.randomUUID(),expected_revision:view.revision,kind:'report_business_result',values:{}});
  if(!next||next.task_id!==view.task_id||next.revision<=view.revision)throw new Error('Recheck the current task.');
  if(live.current){setOpen(false);setUncertain(false);}
  if(next.state==='completed')onClinicalChanged?.();
 }
 async function confirm(){
  if(!bound||blocked||pending.current||uncertain)return;pending.current=true;setWorking(true);setError(false);
  const binding={task_id:view.task_id,expected_revision:view.revision},payload=record(record(view.visible_fields.reminder_review).payload);
  try{if(snooze)await api.snoozeReminder(String(payload.occurrence_id),Number(payload.minutes),binding);
   else {await api.updatePreferences({reminders_enabled:payload.reminders_enabled===true,reminder_lead_minutes:Number(payload.reminder_lead_minutes)},binding);await loadPreferences();}
   await check();
  }catch{if(live.current){setError(true);setUncertain(true);}}finally{pending.current=false;if(live.current)setWorking(false);}
 }
 if(view.state==='suspended'||view.state==='cancelled')return null;
 const summary=<>
  {snooze?<><strong>{String(view.visible_fields.medication_name??'')}</strong><p>{say('Scheduled time','计划时间')}: {when(view.visible_fields.due_at)}</p><p>{say('Delay from confirmation','从确认时刻起延后')}: {String(fields.minutes??minutes)} {say('minutes','分钟')}</p></>:<><p>{say('Medication reminders','药物提醒')}: {fields.reminders_enabled===true?say('On','开启'):say('Off','关闭')}</p><p>{t('Reminder Lead Time')}: {String(fields.reminder_lead_minutes??lead)} {say('minutes','分钟')}</p></>}
  <p>{say('Timezone','时区')}: {timezone}</p>
  <p>{say('This changes reminders only. It does not change your medication plan or record a dose.','这只更改提醒，不会修改用药计划或记录服药。')}</p>
 </>;
 if(view.state==='completed')return <div><p>{say('The earlier reminder change was saved. Current settings are shown below.','此前的提醒变更已保存，以下显示当前设置。')}</p>{snooze?<p>{say('Current saved snooze','当前保存的稍后提醒')}: {when(view.visible_fields.previous_remind_at)||say('None','无')}</p>:<p>{current.reminders_enabled===false?say('Medication reminders are off.','药物提醒已关闭。'):say('Medication reminders are on.','药物提醒已开启。')} · {String(current.reminder_lead_minutes??0)} {say('minutes before','分钟前')}</p>}</div>;
 if(bound&&!editing)return <div>
  {view.prompt_key==='assistant.reminder.check_result'?<button disabled={blocked} onClick={()=>void check().catch(()=>setError(true))}>{say('Check reminder result','核查提醒结果')}</button>:<>
   <button disabled={blocked} onClick={()=>setOpen(true)}>{say('Review reminder change','核对提醒变更')}</button>
   <button disabled={blocked||uncertain} onClick={()=>setEditing(true)}>{say('Edit reminder details','修改提醒资料')}</button>
  </>}
  {open?<BottomSheet title={say('Review reminder change','核对提醒变更')} onCancel={()=>setOpen(false)} busy={working}>{summary}
   {!uncertain?<button disabled={blocked} onClick={()=>void confirm()}>{say('Confirm reminder change','确认提醒变更')}</button>:<button disabled={blocked} onClick={()=>void check().catch(()=>setError(true))}>{say('Check reminder result','核查提醒结果')}</button>}
   <button disabled={working} onClick={()=>setOpen(false)}>{t('Cancel')}</button>
   {error?<p role="alert">{say('The save or result check did not finish. Your details are retained. Check the result before another change.','保存或结果核查未完成，资料仍保留。请先核查结果，再进行下一次变更。')}</p>:null}
  </BottomSheet>:null}
  {error&&!open?<p role="alert">{say('The reminder result is not confirmed.','提醒结果尚未确认。')}</p>:null}
 </div>;
 const choices=view.actions.flatMap(action=>action.kind==='choice'&&action.action_id==='reminder.occurrence'?action.options:[]);
 return <div>
  {choices.map(option=><button disabled={blocked} key={option.value} onClick={()=>void dispatch({occurrence_id:option.value,previous_remind_at:null,previous_timezone:timezone})}>{say('Select','选择')}: {option.label_text}</button>)}
  {snooze&&!fields.occurrence_id?<p>{say('Select an existing scheduled dose. A projected reminder alone cannot be snoozed.','请选择已有的计划剂次，预计提醒本身不能办理稍后提醒。')}</p>:<form onSubmit={event=>{event.preventDefault();void dispatch(snooze?{occurrence_id:fields.occurrence_id??null,minutes:Number(minutes),previous_remind_at:view.visible_fields.previous_remind_at??null,previous_timezone:timezone}:{reminders_enabled:enabled,reminder_lead_minutes:lead,previous_enabled:current.reminders_enabled??true,previous_lead_minutes:current.reminder_lead_minutes??0,previous_timezone:timezone});}}>
   {snooze?<><strong>{String(view.visible_fields.medication_name??'')}</strong><label>{say('Minutes later','延后分钟数')}<input type="number" min="1" max="1440" required value={minutes} disabled={blocked} onChange={event=>{setMinutes(event.target.value);setDirty(true);}}/></label></>:<>
    <label><input type="checkbox" checked={enabled} disabled={blocked} onChange={event=>{setEnabled(event.target.checked);setDirty(true);}}/>{t('Medication Reminders')}</label>
    <ReminderLeadSelect value={lead} disabled={blocked} id={`assistant-reminder-lead-${view.task_id}`} onChange={value=>{setLead(value);setDirty(true);}}/>
   </>}
   <button disabled={blocked} type="submit">{say('Apply reminder details','使用提醒资料')}</button>
   {dirty?<button type="button" disabled={blocked} onClick={()=>{setEnabled(fields.reminders_enabled===undefined?current.reminders_enabled!==false:fields.reminders_enabled===true);setLead(Number(fields.reminder_lead_minutes??current.reminder_lead_minutes??0));setMinutes(String(fields.minutes??15));setDirty(false);}}>{say('Undo unsent changes','撤回未提交的更改')}</button>:null}
  </form>}
  {error?<p role="alert">{say('The draft could not be updated. Your input is still here.','暂时无法更新草稿，输入仍保留。')}</p>:null}
 </div>;
}
