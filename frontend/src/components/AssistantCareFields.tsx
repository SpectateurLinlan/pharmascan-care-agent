import {useEffect,useState,type FormEvent} from 'react';
import type {JsonValue,WorkflowEventHandler,WorkflowView} from '../api/assistantWorkflows';
import type {Measurement} from '../api/client';
import {useLanguage} from '../language';
import {localFields,patientInstant} from '../patientDateTime';
import {MeasurementFields} from './HealthTrackingScreen';
import {FollowUpError} from './FollowUpError';

type Named={id:string;name:string};
function named(value:JsonValue|undefined):Named[]{return Array.isArray(value)?value.flatMap(row=>row&&typeof row==='object'&&!Array.isArray(row)&&typeof row.id==='string'&&typeof row.name==='string'?[{id:row.id,name:row.name}]:[]):[];}

export function AssistantCareFields({view,busy,onEvent,onDirtyChange}:{view:WorkflowView;busy:boolean;onEvent:WorkflowEventHandler;onDirtyChange?:((value:boolean)=>void)|undefined}){
 const {language,t}=useLanguage(),say=(en:string,zh:string)=>language==='zh'?zh:en;
 const capability=view.capability_id,observation=capability==='observation.add'||capability==='observation.edit',stock=capability==='inventory.count',barrier=capability==='barrier.add',adding=capability==='followup.add',editing=capability==='followup.edit';
 const rawTarget=view.visible_fields.target_task??view.visible_fields.observation;
 const target=rawTarget&&typeof rawTarget==='object'&&!Array.isArray(rawTarget)?rawTarget:{};
 const inputs=view.input_fields??{};
 const initial:Record<string,JsonValue>={...inputs,...(!editing&&capability.startsWith('followup.')&&!adding&&target.notes!==undefined&&inputs.notes===undefined?{notes:target.notes}:{}),...(stock&&inputs.unit===undefined?{unit:'tablet'}:{}),...(observation||editing?Object.fromEntries(Object.entries(target).filter(([key])=>['description','occurred_at','notes',...(observation?['kind','value','secondary_value','unit','medication_id','severity']:['title','category','due_at','regimen_id','medication_id','reminder_minutes'])].includes(key)&&inputs[key]===undefined)):{}),...(barrier&&inputs.category===undefined?{category:'scheduling'}:{})};
 const [data,setData]=useState<Record<string,JsonValue>>(initial),[working,setWorking]=useState(false),[error,setError]=useState<unknown>(null),[dirty,setDirty]=useState(false);
 const zone=typeof view.visible_fields.timezone==='string'?view.visible_fields.timezone:'Asia/Singapore';
 const instantKey=observation||barrier?'occurred_at':'due_at';
 const instant=typeof initial[instantKey]==='string'?String(initial[instantKey]):observation||barrier?String(view.visible_fields.as_of??''):'';
 const parts=instant?localFields(instant,zone):{date:'',time:''};
 const [date,setDate]=useState(parts.date),[time,setTime]=useState(parts.time);
 useEffect(()=>{onDirtyChange?.(dirty||working);return()=>onDirtyChange?.(false);},[dirty,working,onDirtyChange]);
 const change=(key:string,value:JsonValue)=>{setData(previous=>({...previous,[key]:value,...(editing&&key==='regimen_id'?{clear_plan:value===null,medication_id:null}:{}),...(editing&&key==='reminder_minutes'?{disable_reminder:value===null}:{})}));setDirty(true);};
 const text=(key:string)=>typeof data[key]==='string'?data[key] as string:'';
 const textField=(key:string,en:string,zh:string,limit=1000)=><label className="field">{say(en,zh)}<textarea maxLength={limit} value={text(key)} onChange={event=>change(key,event.target.value)}/></label>;
 const medSelect=(key:string,rows:Named[],en:string,zh:string)=><label className="field">{say(en,zh)}<select value={text(key)} onChange={event=>change(key,event.target.value||null)}><option value="">{t('None')}</option>{rows.map(row=><option key={row.id} value={row.id}>{row.name}</option>)}</select></label>;
 const numberField=(key:string,en:string,zh:string)=><label className="field">{say(en,zh)}<input type="number" step="any" value={typeof data[key]==='number'?data[key]:''} onChange={event=>change(key,event.target.value===''?null:Number(event.target.value))}/></label>;
 const dateFields=<div className="followup-grid"><label className="field">{say('Date','日期')}<input type="date" value={date} onChange={event=>{setDate(event.target.value);setDirty(true);}}/></label><label className="field">{say('Time','时间')}<input type="time" value={time} onChange={event=>{setTime(event.target.value);setDirty(true);}}/></label><p>{zone}</p></div>;
 async function apply(event:FormEvent){
  event.preventDefault();if(working||busy)return;setWorking(true);setError(null);
  try{const values={...data};if(observation||barrier||adding||editing||capability==='followup.defer'){
    const chosen=instant&&date===parts.date&&time===parts.time?instant:patientInstant(date,time,zone);if(!chosen)throw new Error('Choose a valid unambiguous patient date and time.');values[instantKey]=chosen;
   }
   const result=await onEvent({event_id:crypto.randomUUID(),expected_revision:view.revision,kind:'provide_fields',values});
   if(!result||result.task_id!==view.task_id||result.revision<=view.revision)throw new Error('Check the current draft before continuing. Your entries remain here.');setDirty(false);
  }catch(caught){setError(caught);}finally{setWorking(false);}
 }
 const needsTarget=capability==='observation.edit'&&!data.observation_id||capability.startsWith('followup.')&&!adding&&!data.task_id||stock&&!data.medication_id;
 if(needsTarget||capability==='observation.delete')return null;
 return <form onSubmit={event=>void apply(event)}><fieldset disabled={busy||working}>
  {observation?<><MeasurementFields value={{kind:(text('kind')||'note') as NonNullable<Measurement['kind']>,value:typeof data.value==='number'?data.value:null,secondary_value:typeof data.secondary_value==='number'?data.secondary_value:null,unit:(data.unit??null) as Exclude<Measurement['unit'],undefined>}} onChange={value=>{setData(previous=>({...previous,...value}));setDirty(true);}}/>{textField('description','Describe how you feel (required)','描述您的感受（必填）')}{dateFields}{medSelect('medication_id',named(view.visible_fields.medications),'Linked medicine (optional)','关联药物（可选）')}<label className="field">{say('Severity (optional)','\u4e25\u91cd\u7a0b\u5ea6\uff08\u53ef\u9009\uff09')}<select value={text('severity')} onChange={event=>change('severity',event.target.value||null)}><option value="">{t('None')}</option>{['mild','moderate','severe'].map(value=><option key={value} value={value}>{t(value)}</option>)}</select></label>{textField('notes','Notes (optional)','\u5907\u6ce8\uff08\u53ef\u9009\uff09')}</>:null}
  {stock?<><label className="field">{say('Stock change','库存变动')}<select value={text('kind')||'count'} onChange={event=>change('kind',event.target.value)}>{['count','refill','adjustment','lost','discarded','damaged'].map(kind=><option key={kind} value={kind}>{t(kind)}</option>)}</select></label>{numberField('quantity','Quantity','数量')}<label className="field">{say('Stock unit','库存单位')}<select value={text('unit')||'tablet'} onChange={event=>change('unit',event.target.value)}>{['tablet','capsule'].map(unit=><option key={unit} value={unit}>{t(unit)}</option>)}</select></label>{numberField('low_threshold','Low-stock threshold','库存偏低阈值')}{textField('note','Your note','您的备注',500)}<p>{say('Inventory estimates are not a physical stock check. Count the units you actually have.','库存估算不等于实物盘点，请清点实际持有的数量。')}</p></>:null}
  {barrier?<><label className="field">{say('Reported difficulty','自述困难')}<select value={text('category')||'scheduling'} onChange={event=>change('category',event.target.value)}>{['forgetfulness','running_out','side_effect_concern','scheduling','unclear_instructions','complexity','unsure_taken','other','prefer_not_to_say'].map(kind=><option value={kind} key={kind}>{t(kind)}</option>)}</select></label>{dateFields}{medSelect('regimen_id',named(view.visible_fields.regimens),'Linked medication plan (optional)','关联用药计划（可选）')}{textField('description','Your description','您的描述')}{textField('chosen_action','Chosen support action','选择的支持措施',500)}</>:null}
  {adding||editing?<><label className="field">{say('Title (required)','事项名称（必填）')}<input maxLength={160} value={text('title')} onChange={event=>change('title',event.target.value)}/></label><label className="field">{say('Follow-up type','跟进类型')}<select value={text('category')||'medication_review'} onChange={event=>change('category',event.target.value)}>{['medication_review','medication_follow_up','refill','monitoring','adherence','symptom_follow_up','expiry_storage'].map(category=><option key={category} value={category}>{t(category)}</option>)}</select></label>{dateFields}{adding||editing?medSelect('regimen_id',named(view.visible_fields.regimens),'Linked medication plan (optional)','关联用药计划（可选）'):null}{numberField('reminder_minutes','Advance reminder (minutes; blank means none)','\u63d0\u524d\u63d0\u9192\uff08\u5206\u949f\uff0c\u7559\u7a7a\u4e3a\u4e0d\u63d0\u9192\uff09')}{adding?<p>{say('No reminder is scheduled unless you choose one in the app.','未选择提醒时，不安排提醒。')}</p>:null}{textField('notes','Notes (optional)','备注（可选）')}</>:capability.startsWith('followup.')?<>{capability==='followup.defer'?dateFields:null}{textField('notes','Notes (optional)','备注（可选）')}</>:null}
  {observation&&text('severity')==='severe'?<p role="alert">{t('Seek prompt professional help for severe symptoms. For a life-threatening emergency, call your local emergency service (995 in Singapore). Do not wait for the app.')}</p>:null}
  {error?<FollowUpError error={error}/>:null}<button type="submit">{say('Apply care details','使用关怀资料')}</button><button type="button" onClick={()=>{setData(initial);setDate(parts.date);setTime(parts.time);setError(null);setDirty(false);}}>{say('Undo changes','撤回修改')}</button>
 </fieldset></form>;
}
