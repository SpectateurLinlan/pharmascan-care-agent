import {useEffect,useRef,useState} from 'react';
import type {JsonValue,WorkflowEventHandler,WorkflowView} from '../api/assistantWorkflows';
import {useLanguage} from '../language';
import {MedicationDate} from './MedicationInputs';

export const recordReadCapabilities=['medication.today','medication.due','medication.status','medication.history','medication.source.view','medication.instructions','record.catalogue','record.history','record.summary','record.visit.prepare'] as const;
function object(value:JsonValue|undefined):Record<string,JsonValue>{return value&&typeof value==='object'&&!Array.isArray(value)?value:{};}
function rows(value:JsonValue|undefined){return Array.isArray(value)?value.map(object):[];}
function text(value:JsonValue|undefined){return typeof value==='string'||typeof value==='number'?String(value):'';}
function fromView(view:WorkflowView){const fields=view.input_fields??{};return {range:text(fields.range_kind)||'30',start:text(fields.start),end:text(fields.end),day:text(fields.day),period:text(fields.period)||'week',medication:text(fields.medication_id),plan:text(fields.regimen_id)};}

/** Patient-facing projections only. A query cannot create or confirm a report. */
export function AssistantRecordActions({view,busy,onEvent,onDirtyChange}:{view:WorkflowView;busy:boolean;onEvent:WorkflowEventHandler;onDirtyChange?:(dirty:boolean)=>void}){
 const {language,t,preferences}=useLanguage();const say=(en:string,zh:string)=>language==='zh'?zh:en;
 const fields=view.visible_fields,history=object(fields.history),summary=object(fields.summary),catalogue=object(fields.catalogue);
 const zone=text(fields.timezone)||preferences.timezone;
 const [filters,setFilters]=useState(()=>fromView(view)),[dirty,setDirty]=useState(false),[working,setWorking]=useState(false),[notice,setNotice]=useState(false);
 const dirtyRef=useRef(false),live=useRef(true),sending=useRef(false),callback=useRef(onDirtyChange);callback.current=onDirtyChange;
 const serverInputs=JSON.stringify(view.input_fields);
 useEffect(()=>{if(!dirtyRef.current)setFilters(fromView(view));},[serverInputs,view.revision]);
 useEffect(()=>{onDirtyChange?.(dirty);},[dirty,onDirtyChange]);
 useEffect(()=>{live.current=true;return()=>{live.current=false;callback.current?.(false);};},[]);
 const locked=busy||working||view.state==='suspended'||view.state==='cancelled';
 function when(value:JsonValue|undefined){const raw=text(value);if(!raw)return say('Not recorded','未记录');if(/^\d{4}-\d{2}-\d{2}$/.test(raw))return raw;
  return Number.isFinite(Date.parse(raw))?new Date(raw).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:zone}):say('Date unavailable','日期不可用');}
 function label(value:JsonValue|undefined){const key=text(value);const labels:Record<string,[string,string]>={
  reported_taken:['Patient reported taken','患者自述已服用'],reported_not_taken:['Patient reported not taken','患者自述未服用'],unsure:['Patient is unsure','患者不确定'],
  pending:['Needs a patient report','待患者自述'],upcoming:['Upcoming recorded time','即将到达登记时间'],unrecorded:['No patient report','没有患者自述'],recorded:['Patient report recorded','已记录患者自述'],
  as_needed:['Only when needed','按需服用'],not_scheduled:['No scheduled time today','今天没有登记时间'],unavailable:['Check original instructions','请核查原始说明'],
  active:['Active','已启用'],ended:['Ended','已结束'],superseded:['Replaced','已替换'],user_reviewed:['Patient reviewed','患者已核对'],professional_verified:['Professionally verified','专业人员已核对'],
  unreviewed:['Not reviewed','尚未核对'],user_manual:['Manual entry','手动录入'],pharmacy_label:['Pharmacy label','药房标签'],prescription:['Prescription','处方'],package:['Packaging','包装'],
 };return labels[key]?.[language==='zh'?1:0]??(key?t(key):say('No patient report','没有患者自述'));}
 function fieldName(value:JsonValue|undefined){const names:Record<string,string>={medication_name:'Medication name',dose_amount:'Amount per dose',dose_unit:'Dose unit',frequency_rule:'Schedule',is_prn:'As needed',route:'Route',food_instruction:'Other recorded instructions',course_start_date:'Course start date',course_end_date:'Course end date',strength:'Product strength',form:'Dosage form'};return t(names[text(value)]??say('Recorded field','登记字段'));}
 function fieldValue(field:Record<string,JsonValue>){const value=field.field_value;
  if(typeof value==='boolean')return value?say('Yes','是'):say('No','否');
  if(field.field_name==='frequency_rule'&&value&&typeof value==='object'){
   const rule=object(value),kind=text(rule.kind),times=Array.isArray(rule.local_times)?rule.local_times.map(text).join(', '):'';
   return `${kind==='daily'?say('Daily','每日'):kind==='weekly'?say('Weekly','每周'):kind==='interval'?`${say('Hours between doses','每隔几小时')}: ${text(rule.every_hours)}`:say('Recorded schedule','登记安排')} ${times}`;
  }
  if(value===null||value===undefined)return say('Not recorded','未记录');
  return typeof value==='object'?JSON.stringify(value):field.field_name==='dose_unit'?t(text(value)):text(value);
 }
 function change(key:keyof typeof filters,value:string){dirtyRef.current=true;setDirty(true);setNotice(false);setFilters(old=>({...old,[key]:value,...(key==='medication'?{plan:''}:{}),...(old.range==='plan'&&(key==='medication'||key==='plan'&&!value)?{range:'30'}:{})}));}
 async function query(values:Record<string,JsonValue>){
  if(locked||sending.current)return;sending.current=true;setWorking(true);setNotice(false);
  try{const result=await onEvent({event_id:crypto.randomUUID(),expected_revision:view.revision,kind:'provide_fields',values});
   if(!live.current)return;if(result&&result.task_id===view.task_id&&result.revision>view.revision){dirtyRef.current=false;setDirty(false);setFilters(fromView(result));}else setNotice(true);
  }catch{if(live.current)setNotice(true);}finally{sending.current=false;if(live.current)setWorking(false);}
 }
 const historical=view.capability_id==='record.history'||view.capability_id==='medication.history';
 const status=view.capability_id==='medication.status',summarizing=view.capability_id==='record.summary'||view.capability_id==='record.visit.prepare';
 const scope=(start:JsonValue|undefined,end:JsonValue|undefined)=><p>{say('Query window','查询范围')}: {when(start)} – {when(end)} ({zone})</p>;
 const filterChoices=object(fields.history_filters);
 return <div className="assistant-record-results">
  {fields.medication_name?<h3>{text(fields.medication_name)}</h3>:null}
  {historical||status||summarizing?<form aria-label={say('Record filters','记录筛选')} onSubmit={event=>{event.preventDefault();void query(historical?{medication_id:filters.medication||null,regimen_id:filters.plan||null,range_kind:filters.range,start:filters.range==='custom'?filters.start:null,end:filters.range==='custom'?filters.end:null,cursor:null}:status?{day:filters.day||null,cursor:null}:{period:filters.period,regimen_id:null,page:0});}}>
   <fieldset disabled={locked}>
    <legend>{say('Query options','查询选项')}</legend>
    {historical?<>
     {rows(filterChoices.medications).length?<label>{say('Medication','药物')}<select value={filters.medication} onChange={event=>change('medication',event.target.value)}><option value="">{say('All recorded medicines','所有已登记药物')}</option>{rows(filterChoices.medications).map(row=><option key={text(row.id)} value={text(row.id)}>{text(row.display_name)}</option>)}</select></label>:null}
     {rows(filterChoices.plans).length?<label>{say('Recorded plan','已登记计划')}<select value={filters.plan} onChange={event=>change('plan',event.target.value)}><option value="">{say('All recorded plans','所有已登记计划')}</option>{rows(filterChoices.plans).filter(row=>!filters.medication||row.medication_id===filters.medication).map(row=><option key={text(row.id)} value={text(row.id)}>{text(row.display_name)} · {label(row.state)} · {text(row.version)}</option>)}</select></label>:null}
     <label>{say('History range','历史范围')}<select value={filters.range} onChange={event=>change('range',event.target.value)}>{[['7',say('Last 7 days','最近7天')],['30',say('Last 30 days','最近30天')],['90',say('Last 90 days','最近90天')],['all',say('All stored records','所有已存记录')],['custom',say('Custom dates','自选日期')],...(filters.plan?[['plan',say('Selected course','所选疗程')]]:[])].map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
     {filters.range==='custom'?<><MedicationDate label={say('Start date','开始日期')} value={filters.start} onChange={value=>change('start',value)}/><MedicationDate label={say('End date','结束日期')} value={filters.end} min={filters.start} onChange={value=>change('end',value)}/></>:null}
    </>:status?<MedicationDate label={say('Record date','记录日期')} value={filters.day} onChange={value=>change('day',value)}/>:<label>{say('Summary period','统计范围')}<select value={filters.period} onChange={event=>change('period',event.target.value)}><option value="week">{say('Calendar week','日历周')}</option><option value="month">{say('Calendar month','日历月')}</option><option value="course">{say('Selected course','所选疗程')}</option></select></label>}
    <button type="submit" disabled={locked||!dirty}>{say('Apply record filters','应用记录筛选')}</button>
    {dirty?<button type="button" disabled={locked} onClick={()=>{dirtyRef.current=false;setDirty(false);setFilters(fromView(view));setNotice(false);}}>{say('Undo unsent filters','撤回尚未提交的筛选')}</button>:null}
   </fieldset>
  </form>:null}
  {notice?<p role="status">{say('The query did not finish. Your filters are still here.','查询尚未完成，筛选条件仍保留在这里。')}</p>:null}
  {fields.today?<>
   <p>{say('Recorded date','登记日期')}: {text(object(fields.today).local_date)} ({zone})</p>
   {rows(object(fields.today).plans).map(row=><article key={text(row.regimen_id)}><h4>{text(row.medication_name)}</h4><p>{text(row.dose_amount)||say('Not recorded','未记录')} {t(text(row.dose_unit))} · v{text(row.version)}</p><p>{label(row.state)}</p>{Array.isArray(row.scheduled_times)&&row.scheduled_times.length?<p>{say('Recorded times','\u767b\u8bb0\u65f6\u95f4')}: {row.scheduled_times.map(when).join('; ')}</p>:null}{row.next_due_at?<p>{say('Next recorded time','下个登记时间')}: {when(row.next_due_at)}</p>:null}{Array.isArray(row.unrecorded_times)&&row.unrecorded_times.length?<p>{say('Times without a patient report','尚无患者自述的时间')}: {row.unrecorded_times.map(when).join('; ')}</p>:null}</article>)}
   {!rows(object(fields.today).plans).length?<p>{say('No matching recorded times were found.','没有找到符合条件的登记时间。')}</p>:null}
   <p>{say('Recorded times and patient reports are separate. A missing report does not establish whether medicine was taken.','登记时间与患者自述分别展示。没有自述不能确定是否已服药。')}</p>
  </>:null}
  {fields.history?<>
   {scope(history.window_start,history.window_end)}
   <p>{say('Only stored records are shown. Missing records do not establish whether medicine was taken.','仅显示已存记录，缺少记录不能确定是否已服药。')}</p>
   {rows(history.entries).map(row=><article key={text(row.id)}><h4>{text(row.display_name)}</h4><p>{when(row.due_at??row.event_time)}</p><p>{label(row.reported===true?row.intake_status:undefined)}</p>{row.reported_late===true?<p>{say('Patient report added later','患者稍后补记')}</p>:null}</article>)}
   {!rows(history.entries).length?<p>{say('No stored records in this query window.','本次查询范围内没有已存记录。')}</p>:null}
   {typeof history.next_cursor==='string'?<button disabled={locked||dirty} onClick={()=>void query({cursor:history.next_cursor!})}>{say('More stored records','更多已存记录')}</button>:null}
  </>:null}
  {fields.catalogue?<>{rows(catalogue.medications).map(med=><article key={text(med.id)}><h4>{text(med.display_name)}</h4>{rows(catalogue.plans).filter(plan=>plan.medication_id===med.id).map(plan=><p key={text(plan.id)}>{label(plan.state)} · {text(plan.dose_amount)} {t(text(plan.dose_unit))}{plan.is_prn?` · ${say('Only when needed','按需服用')}`:''}</p>)}</article>)}{!rows(catalogue.medications).length?<p>{say('No recorded medicines found.','没有已登记的药物。')}</p>:null}</>:null}
  {fields.summary?<>
   <p>{summary.period==='week'?say('Calendar week','日历周'):summary.period==='month'?say('Calendar month','日历月'):say('Selected course','所选疗程')}</p>
   {scope(summary.window_start,summary.window_end)}
   <dl><dt>{say('Patient reported taken','患者自述已服用')}</dt><dd>{text(summary.reported_taken)}</dd><dt>{say('Patient reported not taken','患者自述未服用')}</dt><dd>{text(summary.reported_not_taken)}</dd><dt>{say('Patient is unsure','患者不确定')}</dt><dd>{text(summary.unsure)}</dd></dl>
   {rows(summary.medications).map(row=><article key={text(row.regimen_id)}><h4>{text(row.name)}</h4><p>{label(row.state)} · v{text(row.version)} · {text(row.dose_amount)} {t(text(row.dose_unit))}</p><p>{say('Stored scheduled records','已存计划记录')}: {text(row.recorded_occurrences)}; {say('Without a patient report','尚无患者自述')}: {text(row.without_report)}</p></article>)}
   <p>{t(text(summary.coverage_note))}</p>
   {Array.isArray(summary.questions)&&summary.questions.length?<><h4>{say('Questions to discuss at your visit','复诊时可讨论的问题')}</h4><ul>{summary.questions.map((question,index)=><li key={index}>{t(text(question))}</li>)}</ul></>:null}
  </>:null}
  {Array.isArray(fields.sources)?<>{rows(fields.sources).map(source=><article key={text(source.source_id)}><h4>{label(source.source_kind)}</h4><p>{label(source.review_status)}{source.reviewed_at?` · ${when(source.reviewed_at)}`:''}</p><dl>{rows(source.fields).map((field,index)=><div key={index}><dt>{fieldName(field.field_name)}</dt><dd>{fieldValue(field)}</dd></div>)}</dl></article>)}{!fields.sources.length?<p>{say('No recorded source was found.','没有找到已登记来源。')}</p>:null}</>:null}
  {fields.understanding?<p>{text(object(fields.understanding).patient_safe_summary)}</p>:null}
 </div>;
}
