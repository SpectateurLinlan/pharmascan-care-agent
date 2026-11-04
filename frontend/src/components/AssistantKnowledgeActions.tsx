import {useEffect,useRef,useState,type FormEvent} from 'react';
import {workflowApi,type KnowledgeQueryResult,type WorkflowEventHandler,type WorkflowView} from '../api/assistantWorkflows';
import {useLanguage} from '../language';
import {presentExplanation} from '../assistantResponsePresentation';
import {AnswerSources} from './AnswerSources';
import {FollowUpError} from './FollowUpError';

export function AssistantKnowledgeActions({view,busy,onEvent,onDirtyChange}:{view:WorkflowView;busy:boolean;onEvent:WorkflowEventHandler;onDirtyChange?:(dirty:boolean)=>void}){
 const {language}=useLanguage(),say=(en:string,zh:string)=>language==='zh'?zh:en;
 const saved=typeof view.input_fields?.medication_name==='string'?view.input_fields.medication_name:'';
 const [name,setName]=useState(saved),[working,setWorking]=useState(false),[error,setError]=useState<unknown>(null),[answer,setAnswer]=useState<KnowledgeQueryResult|null>(null);
 const live=useRef(true),sending=useRef(false),generation=useRef(0),callback=useRef(onDirtyChange);callback.current=onDirtyChange;
 useEffect(()=>{live.current=true;return()=>{live.current=false;generation.current++;callback.current?.(false);};},[]);
 useEffect(()=>{generation.current++;sending.current=false;setWorking(false);setName(saved);setAnswer(null);setError(null);},[view.task_id,view.revision,view.save_mode,saved]);
 useEffect(()=>{callback.current?.(working||name!==saved);return()=>callback.current?.(false);},[working,name,saved]);
 const resolution=view.visible_fields.name_resolution;
 const record=resolution&&typeof resolution==='object'&&!Array.isArray(resolution)?resolution:{};
 const candidates=Array.isArray(record.candidates)?record.candidates.flatMap(row=>row&&typeof row==='object'&&!Array.isArray(row)&&typeof row.id==='string'&&typeof row.display_name==='string'?[{id:row.id,name:row.display_name}]:[]):[];
 const choose=record.status==='needs_confirmation'||record.status==='ambiguous';
 const blocked=busy||working,dirty=name!==saved;
 async function apply(event:FormEvent){
  event.preventDefault();if(blocked||sending.current||!name.trim())return;
  sending.current=true;setWorking(true);setError(null);const current=generation.current;
  try{await onEvent({event_id:crypto.randomUUID(),expected_revision:view.revision,kind:'provide_fields',values:{medication_name:name.trim()}});}
  catch(caught){if(live.current&&current===generation.current)setError(caught);}
  finally{if(live.current&&current===generation.current){sending.current=false;setWorking(false);}}
 }
 async function query(candidate?:string){
  if(blocked||dirty||sending.current||!saved)return;
  const current=generation.current;sending.current=true;setWorking(true);setError(null);setAnswer(null);
  try{const result=await workflowApi.knowledge(view.task_id,{expected_revision:view.revision,...(candidate?{candidate_id:candidate}:{}),...(view.save_mode==='ephemeral'?{ephemeral:{capability_id:view.capability_id,fields:view.input_fields??{}}}:{})});
   if(live.current&&current===generation.current)setAnswer(result);
  }catch(caught){if(live.current&&current===generation.current)setError(caught);}
  finally{if(live.current&&current===generation.current){sending.current=false;setWorking(false);}}
 }
 return <div role="region" aria-label={say('Medication knowledge query','药物知识查询')}>
  <form onSubmit={event=>void apply(event)}>
   <label className="field">{say('Medicine name','药物名称')}<input value={name} maxLength={160} disabled={blocked} onChange={event=>setName(event.target.value)} autoComplete="off"/></label>
   <button type="submit" disabled={blocked||!name.trim()||!dirty}>{say('Apply medicine name','使用此药名')}</button>
  </form>
  <p>{say('Searches public US label sources using the medicine name only. Results stay on this page; reopening this task requires another search.','仅使用药物名称查询美国公开标签资料。查询结果仅保留在当前页面，重新打开任务后需再次查询。')}</p>
  {choose?<div><p>{say('Did you mean one of these names? Choose before searching.','您指的是以下哪一种药名？请确认后查询。')}</p><div className="actions">{candidates.map(row=><button key={row.id} disabled={blocked||dirty} onClick={()=>void query(row.id)}>{say(`Use ${row.name} and search`,`确认 ${row.name} 并查询`)}</button>)}</div></div>:<button disabled={blocked||dirty||!saved} onClick={()=>void query()}>{say('Search medication knowledge','查询药物知识')}</button>}
  {working?<p role="status">{say('Reading public source information…','正在读取公开来源资料…')}</p>:null}
  {error?<FollowUpError kind="read" error={error}/>:null}
  {answer?<div aria-live="polite"><p>{answer.patient_safe_summary}</p>
   <ul>{answer.explanations.map((step,index)=><li key={index}>{presentExplanation(step,language)}</li>)}</ul>
   <AnswerSources traces={[{tool_name:'get_medication_understanding',status:'success',error_code:null,requires_confirmation:false,clarification_question:null,payload:{general_knowledge:answer.general_knowledge}}]}/>
  </div>:null}
 </div>;
}
