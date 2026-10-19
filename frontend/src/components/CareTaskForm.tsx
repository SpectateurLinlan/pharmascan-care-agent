import {useRef,useState,type FormEvent} from 'react';
import {api,type RegimenHistoryItem} from '../api/client';
import type {CareTask,CareTaskInput,TaskCategory,TaskStatus} from '../api/care';
import {useLanguage} from '../language';
import {localFields,patientInstant} from '../patientDateTime';
import {regimenLabel} from '../regimenPresentation';
import {BottomSheet} from './BottomSheet';
import {FollowUpError} from './FollowUpError';
import {careCopy,careLabel} from './followUpCopy';
import '../ui/followups.css';

export function CareTaskForm({task,regimens,onCancel,onSaved,extended=true,multiple=false}:{multiple?:boolean;extended?:boolean;task?:CareTask|undefined;regimens:RegimenHistoryItem[];onCancel:()=>void;onSaved:(task:CareTask)=>void}){
 const {language,t,preferences}=useLanguage(),c=careCopy(language),zone=preferences.timezone;
 const initial=task?localFields(task.due_at,zone):{date:'',time:''};
 const [title,setTitle]=useState(task?.title??''),[category,setCategory]=useState<TaskCategory>(task?.category??'medication_review');
 const [status,setStatus]=useState<TaskStatus>(task&&!['completed','cancelled'].includes(task.status)?task.status:'open');
 const [date,setDate]=useState(initial.date),[time,setTime]=useState(initial.time),[regimen,setRegimen]=useState(task?.regimen_id??''),[notes,setNotes]=useState(task?.notes??'');
 const prior=extended?(task?.reminder_minutes===undefined?60:task.reminder_minutes):0;
 const [reminder,setReminder]=useState(prior===null?'none':[0,15,30,60,180,1440].includes(prior)?String(prior):'custom'),[custom,setCustom]=useState(String(prior??60));
 const [errors,setErrors]=useState<Record<string,string>>({}),[stage,setStage]=useState<'edit'|'historical'|'review'>('edit'),[busy,setBusy]=useState(false),[error,setError]=useState<unknown>(null);
 const [draft,setDraft]=useState<CareTaskInput|null>(null);const form=useRef<HTMLFormElement>(null),key=useRef(crypto.randomUUID());
 const [offsets,setOffsets]=useState<number[]>(task?.reminder_offsets??(prior===null?[]:[prior]));
 const chosenOffsets=[...new Set([...offsets,...(reminder==='custom'?[Number(custom)]:[])])].sort((a,b)=>b-a);
 const lead=multiple?(chosenOffsets.length?Math.max(...chosenOffsets):null):reminder==='none'?null:Number(reminder==='custom'?custom:reminder),instant=patientInstant(date,time,zone);
 const unusuallyOld=!!instant&&Date.now()-Date.parse(instant)>366*86400000;
 const [oldDateChecked,setOldDateChecked]=useState(false);
 const trigger=instant&&lead!==null?new Date(Date.parse(instant)-lead*60000):null;
 const when=(value:string|Date)=>new Date(value).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:zone});
 function submit(event:FormEvent){event.preventDefault();const issues:Record<string,string>={};
  if(!title.trim()||title.trim().length>160)issues.title=c('Enter a title (1–160 characters).','请填写事项名称（1–160字）。');
  if(!extended&&instant&&Date.parse(instant)<Date.now())issues.date=c('Historical entry is not enabled yet. Choose a future date.','历史事项功能尚未启用，请选择未来日期。');
  if(!date)issues.date=c('Choose a date.','请选择日期。');
  if(task&&status==='deferred'&&instant&&Date.parse(instant)<=Date.now())issues.time=c('Choose a future rescheduled time.','改期请选择未来时间。');
  if(!time)issues.time=c('Choose a time.','请选择时间。');
  if(date&&time&&!instant)issues.time=c('This local time is invalid or ambiguous. Choose another time.','该本地时间无效或处于夏令时重叠，请选择其他时间。');
  if(regimen&&!regimens.some(row=>row.regimen_id===regimen))issues.regimen=c('Choose a current available plan.','请选择列表中可用的用药计划。');
  if(lead!==null&&(!Number.isInteger(lead)||lead<0||lead>10080||(reminder==='custom'&&lead<1)))issues.reminder=c('Use 1–10080 minutes for a custom reminder.','自定义提醒请填写1–10080分钟。');
  if(multiple&&(chosenOffsets.length>8||chosenOffsets.some(value=>!Number.isInteger(value)||value<0||value>10080)||(reminder==='custom'&&Number(custom)<1)))issues.reminder=t('Use at most eight valid reminder times.');
  const timingChanged=!task||instant!==task.due_at&&Date.parse(instant??'')!==Date.parse(task.due_at)||lead!==task.reminder_minutes||(multiple&&JSON.stringify(chosenOffsets)!==JSON.stringify(task?.reminder_offsets??(task?.reminder_minutes==null?[]:[task.reminder_minutes])));
  if(timingChanged&&trigger&&trigger.getTime()<=Date.now())issues.reminder=c('The reminder would be in the past. Choose no reminder or a later time.','提醒时间已过去。请选择不提醒或调整事项时间。');
  if(notes.length>1000)issues.notes=c('Use at most 1000 characters.','备注最多1000字。');
  setErrors(issues);if(Object.keys(issues).length){form.current?.querySelector<HTMLElement>(`[name="${Object.keys(issues)[0]}"]`)?.focus();return;}
  const selected=regimens.find(row=>row.regimen_id===regimen);
  const values:CareTaskInput={id:key.current,category,title:title.trim(),due_at:instant!,medication_id:selected?.medication_id??null,regimen_id:selected?.regimen_id??null,notes,reminder_minutes:lead,...(multiple?{reminder_offsets:chosenOffsets}:{}),confirmed:false};
  setOldDateChecked(false);setDraft(values);setStage(Date.parse(instant!)<Date.now()&&timingChanged?'historical':'review');
 }
 async function save(){if(!draft||busy)return;setBusy(true);setError(null);try{
   const values={...draft,confirmed:true};
   const result=task?await api.updateCareTask(task.id,{id:key.current,expected_version:task.version,status,due_at:values.due_at,notes:values.notes,...(!extended||task.source==='stock_estimate'?{}:{title:values.title,category:values.category,medication_id:values.medication_id,regimen_id:values.regimen_id}),reminder_minutes:values.reminder_minutes??null,...(multiple?{reminder_offsets:values.reminder_offsets??[]}:{}),historical_confirmed:values.historical_confirmed??false,confirmed:true}):await api.createCareTask(values);
   window.dispatchEvent(new Event('pharmascan:reminder-refresh'));onSaved(result);
  }catch(caught){setError(caught);}finally{setBusy(false);}}
 const invalid=(name:string)=>({'aria-invalid':!!errors[name],'aria-describedby':errors[name]?`care-error-${name}`:undefined});
 const message=(name:string)=>errors[name]?<span role="alert" id={`care-error-${name}`} className="followup-error">{errors[name]}</span>:null;
 const picker=(input:HTMLInputElement)=>{try{input.showPicker?.();}catch(caught){if(!(caught instanceof DOMException))throw caught;}};
 return <BottomSheet title={task?c('Edit or reschedule follow-up','编辑或改期'):c('New medication follow-up','新建用药跟进')} className="care-flow" onCancel={onCancel} busy={busy}>
  {!extended?<p role="status">{c('Advance reminders, historical entries and expanded editing are not enabled yet. Tasks use a reminder at the scheduled time.','提前提醒、历史录入及扩展编辑尚未启用；事项将在计划时间提醒。')}</p>:null}
  {error?<FollowUpError error={error}/>:null}
  {stage==='edit'?<form ref={form} noValidate onSubmit={submit} onChange={event=>{const name=(event.target as HTMLInputElement).name;setErrors(previous=>Object.fromEntries(Object.entries(previous).filter(([key])=>key!==name&&(!(name==='date'||name==='time')||key!=='reminder'))));}}>
   <label className="field">{c('Follow-up type','跟进类型')}<select disabled={task?.source==='stock_estimate'||(!extended&&!!task)} value={category} onChange={e=>setCategory(e.target.value as TaskCategory)}>{(['medication_review','medication_follow_up','refill','monitoring','adherence','symptom_follow_up','expiry_storage'] as const).map(value=><option key={value} value={value}>{careLabel(value,language,t)}</option>)}</select></label>
   {task?<label className="field">{c('Status','状态')}<select value={status} onChange={e=>setStatus(e.target.value as TaskStatus)}>{(['open','contacted','deferred'] as const).map(value=><option key={value} value={value}>{careLabel(value,language,t)}</option>)}</select></label>:null}
   <label className="field">{c('Title (required)','事项名称（必填）')}<input aria-label={c('Title (required)','事项名称（必填）')} name="title" disabled={task?.source==='stock_estimate'||(!extended&&!!task)} value={title} onChange={e=>setTitle(e.target.value)} {...invalid('title')}/>{message('title')}</label>
   <div className="followup-grid"><label className="field">{c('Date (required)','日期（必填）')}<input aria-label={c('Date (required)','日期（必填）')} name="date" type="date" value={date} onClick={e=>picker(e.currentTarget)} onChange={e=>setDate(e.target.value)} {...invalid('date')}/>{message('date')}</label><label className="field">{c('Time (required)','时间（必填）')}<input aria-label={c('Time (required)','时间（必填）')} name="time" type="time" value={time} onClick={e=>picker(e.currentTarget)} onChange={e=>setTime(e.target.value)} {...invalid('time')}/>{message('time')}</label></div>
   <p className="notice">{c('Patient time zone','患者时区')}: {zone}</p>
   {multiple?<fieldset name="reminder" tabIndex={-1} {...invalid('reminder')} className="care-reminder-options"><legend>{t('Reminder times')}</legend>{[0,15,30,60,180,1440].map(value=><label key={value}><input type="checkbox" checked={offsets.includes(value)} onChange={event=>setOffsets(previous=>event.target.checked?[...previous,value]:previous.filter(item=>item!==value))}/>{value===0?t('At scheduled time'):value===1440?c('1 day before','提前1天'):value===180?c('3 hours before','提前3小时'):value===60?c('1 hour before','提前1小时'):t('{minutes} minutes before').replace('{minutes}',String(value))}</label>)}<label><input type="checkbox" checked={reminder==='custom'} onChange={event=>setReminder(event.target.checked?'custom':'none')}/>{t('Custom')}</label>{reminder==='custom'?<input aria-label={t('Custom minutes')} type="number" min="1" max="10080" value={custom} onChange={event=>setCustom(event.target.value)}/>:null}{message('reminder')}</fieldset>:<>
   <label className="field">{c('Advance reminder','提前提醒')}<select aria-label={c('Advance reminder','提前提醒')} name="reminder" disabled={!extended} value={reminder} onChange={e=>setReminder(e.target.value)} {...invalid('reminder')}><option value="none">{c('No reminder','不提醒')}</option>{[0,15,30,60,180,1440].map(value=><option key={value} value={value}>{value===0?c('At scheduled time','到时提醒'):value===1440?c('1 day before','提前1天'):value===180?c('3 hours before','提前3小时'):value===60?c('1 hour before','提前1小时'):`${value} ${c('minutes before','分钟前')}`}</option>)}<option value="custom">{c('Custom','自定义')}</option></select>{reminder==='custom'?<input aria-label={c('Custom minutes','自定义分钟数')} type="number" min="1" max="10080" value={custom} onChange={e=>setCustom(e.target.value)}/>:null}{message('reminder')}</label></>}
   {multiple&&instant?chosenOffsets.map(value=><p key={value}>{t('Reminder')}: {when(new Date(Date.parse(instant)-value*60000))} ({zone})</p>):null}
   {!multiple&&trigger&&Number.isFinite(trigger.getTime())?<p role="status">{c('Reminder','提醒时间')}: {when(trigger)} ({zone})</p>:null}
   <label className="field">{c('Linked medication plan (optional)','关联用药计划（可选）')}<select name="regimen" disabled={task?.source==='stock_estimate'||(!extended&&!!task)} value={regimen} onChange={e=>setRegimen(e.target.value)} {...invalid('regimen')}><option value="">{t('None')}</option>{regimens.map(row=><option key={row.regimen_id} value={row.regimen_id}>{regimenLabel(row,t,language==='zh'?'zh-CN':'en-SG',zone)}</option>)}</select>{message('regimen')}</label>
   <label className="field">{c('Notes (optional)','备注（可选）')}<textarea name="notes" value={notes} onChange={e=>setNotes(e.target.value)} {...invalid('notes')}/>{message('notes')}</label>
   <div className="followup-actions"><button type="button" onClick={onCancel}>{t('Cancel')}</button><button className="primary" type="submit">{c('Review and save','核对并保存')}</button></div>
  </form>:stage==='historical'?<>{unusuallyOld?<label><input type="checkbox" checked={oldDateChecked} onChange={e=>setOldDateChecked(e.target.checked)}/>{c(`This date (${date}) is more than a year ago. I checked the year and intend to save a historical task.`,`该日期（${date}）距今已超过一年。我已核对年份，确实要保存历史事项。`)}</label>:null}<p>{c('This time is in the past. Save it as a historical task without scheduling a reminder?','该事项时间已过去。是否作为历史事项保存？不会安排过去的提醒。')}</p><button onClick={()=>setStage('edit')}>{c('Back to edit','返回编辑')}</button><button className="primary" disabled={unusuallyOld&&!oldDateChecked} onClick={()=>{setDraft(value=>value?{...value,historical_confirmed:true}:value);setStage('review');}}>{c('Confirm historical entry','确认历史事项')}</button></>:draft?<><h3>{draft.title}</h3><p>{careLabel(draft.category,language,t)} · {when(draft.due_at)}</p>{multiple&&draft.reminder_offsets?.map(value=><p key={value}>{t('Reminder')}: {when(new Date(Date.parse(draft.due_at)-value*60000))}</p>)}<p>{lead===null?c('No reminder','不提醒'):`${c('Reminder','提醒时间')}: ${trigger?when(trigger):''}`}</p>{draft.notes?<p>{draft.notes}</p>:null}<div className="followup-actions"><button disabled={busy} onClick={()=>setStage('edit')}>{c('Back to edit','返回编辑')}</button><button disabled={busy} className="primary" onClick={()=>void save()}>{busy?c('Saving…','正在保存…'):c('Confirm and save','确认保存')}</button></div></>:null}
 </BottomSheet>;
}
