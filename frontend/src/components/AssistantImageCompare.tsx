import {useEffect,useRef,useState} from 'react';
import {workflowApi,type ComparisonResult,type WorkflowEventHandler,type WorkflowView} from '../api/assistantWorkflows';
import {useLanguage} from '../language';
import {workflowChoice} from '../assistantWorkflowActions';
import {PhotoAcquisition} from './PhotoAcquisition';
import './AssistantMediaActions.css';

const words:Record<string,[string,string]>={
 'assistant.compare.personal':['Compare with personal references','与个人参考照片比对'],
 'assistant.compare.identify':['Look for catalogue candidates','查找目录候选'],
 'assistant.compare.all':['All personal references','全部个人参考照片'],
 'no_reviewed_reference':['No reviewed personal reference establishes identity. Catalogue suggestions are only clues for checking the original label.','没有已核对的个人参考照片可用于确认身份。目录候选仅供核对原标签。'],
 'image_unclear':['The image is unclear or ambiguous. Check the original packaging or ask a pharmacist.','图片不清晰或结果存在歧义，请核对原包装或咨询药剂师。'],
 'missing_reference':['No eligible personal reference is available. A gallery photo alone does not establish a verified reference.','没有可用于比对的个人参考照片。保存到图库的照片不等于已验证的参考照片。'],
 'service_unavailable':['The photo service is unavailable. Your photo is retained; no identity conclusion was reached.','图片服务不可用，照片仍保留，尚未得出身份结论。'],
 'plan_conflict':['The visual evidence and current medication records need clarification. Check the reviewed instructions with a pharmacist.','外观信息与当前用药记录需进一步核对，请与药剂师确认已核对的用药说明。'],
 'visual_reference_only':['Similar personal visual evidence was found. This does not verify the medicine or authorize taking it.','找到了相似的个人外观参考信息，不代表已确认药物身份或可以服用。'],
};

export function AssistantImageCompare({view,busy,onEvent,onView,onDirtyChange,onOriginalUploadState}:{
 view:WorkflowView;busy:boolean;onEvent:WorkflowEventHandler;onView?:((view:WorkflowView)=>void)|undefined;
 onDirtyChange?:((dirty:boolean)=>void)|undefined;onOriginalUploadState?:((task:string,active:boolean)=>void)|undefined;
}){
 const {language}=useLanguage(),say=(en:string,zh:string)=>language==='zh'?zh:en,word=(key:string)=>words[key]?.[language==='zh'?1:0]??key;
 const [file,setFile]=useState<File|null>(null),[fileOriginal,setFileOriginal]=useState<string|null>(null),[working,setWorking]=useState(false);
 const [consent,setConsent]=useState(false),[answer,setAnswer]=useState<ComparisonResult|null>(null),[error,setError]=useState<'original'|'query'|'draft'|null>(null);
 const live=useRef(true),pending=useRef(false),uploadId=useRef<string|null>(null),current=useRef(view);current.current=view;
 const callback=useRef(onDirtyChange);callback.current=onDirtyChange;const stateCallback=useRef(onOriginalUploadState);stateCallback.current=onOriginalUploadState;
 const source=typeof view.input_fields?.source_attachment_id==='string'?view.input_fields.source_attachment_id:null;
 const intent=view.input_fields?.intent==='identify'?'identify':'personal',regimen=typeof view.input_fields?.regimen_id==='string'?view.input_fields.regimen_id:null;
 const filePending=Boolean(file&&(view.save_mode==='ephemeral'||fileOriginal===null||fileOriginal!==source));
 useEffect(()=>{live.current=true;return()=>{live.current=false;stateCallback.current?.(view.task_id,false);};},[view.task_id]);
 useEffect(()=>{setAnswer(null);setConsent(false);setError(null);if(view.save_mode==='ephemeral'){uploadId.current=null;setFileOriginal(null);}},[view.task_id,view.revision,view.save_mode]);
 useEffect(()=>{callback.current?.(working||filePending);return()=>callback.current?.(false);},[working,filePending]);
 const locked=busy||working;
 async function apply(event:Parameters<WorkflowEventHandler>[0]){
  setError(null);try{await onEvent(event);}catch{if(live.current)setError('draft');}
 }
 async function saveOriginal(){
  if(!file||!onView||view.save_mode!=='allowed'||pending.current)return;
  uploadId.current??=crypto.randomUUID();pending.current=true;setWorking(true);setError(null);stateCallback.current?.(view.task_id,true);
  try{const result=await workflowApi.uploadComparisonOriginal(view.task_id,uploadId.current,file,view.revision);
   if(!live.current||result.workflow.revision<current.current.revision)return;setFileOriginal(result.attachment.id);onView(result.workflow);
   if(result.workflow.input_fields?.source_attachment_id!==result.attachment.id)await onEvent({event_id:crypto.randomUUID(),expected_revision:result.workflow.revision,kind:'provide_fields',values:{source_attachment_id:result.attachment.id}});
  }catch{if(live.current)setError('original');}
  finally{pending.current=false;stateCallback.current?.(view.task_id,false);if(live.current)setWorking(false);}
 }
 async function query(){
  if(locked||!consent||pending.current||view.save_mode==='allowed'&&(!source||filePending)||view.save_mode==='ephemeral'&&!file)return;
  pending.current=true;setWorking(true);setError(null);setAnswer(null);const revision=view.revision,mode=view.save_mode;
  const valid=()=>live.current&&current.current.revision===revision&&current.current.save_mode===mode;
  try{let selected=fileOriginal===source&&!filePending?file:null;
   if(mode==='ephemeral')selected=file;
   if(!selected&&source){const blob=await workflowApi.originalBlob(view.task_id,source);if(!valid())return;selected=new File([blob],'saved-comparison-photo',{type:blob.type});}
   if(!selected)throw new Error('Choose the current photo');
   const result=await workflowApi.compareImage(view.task_id,selected,revision,true,mode==='ephemeral'?{intent,regimen_id:regimen}:undefined);
   if(valid())setAnswer(result);
  }catch{if(valid())setError('query');}
  finally{pending.current=false;if(live.current)setWorking(false);}
 }
 if(['cancelled','suspended','completed'].includes(view.state))return null;
 const page=Number(view.visible_fields.page??0),pages=Number(view.visible_fields.page_count??1);
 return <div className="assistant-media" role="region" aria-label={say('Photo comparison','照片比对')}>
  <div className="actions">{view.actions.flatMap(action=>action.kind==='choice'?action.options.map(option=><button key={`${action.action_id}:${option.value}`} disabled={locked} aria-pressed={action.action_id==='compare.intent'?intent===option.value:regimen===option.value||option.value==='all'&&!regimen} onClick={()=>void apply(workflowChoice(view,action,option.value))}>{option.label_text??word(option.label_key)}</button>):[])}</div>
  {view.visible_fields.selected_medication?<p>{say('Selected plan','所选计划')}: {String(view.visible_fields.selected_medication)}</p>:null}
  <PhotoAcquisition file={file} disabled={locked} onFile={selected=>{setFile(selected);setFileOriginal(null);uploadId.current=null;setConsent(false);setAnswer(null);setError(null);}}/>
  {view.save_mode==='ephemeral'?<><p>{say('The original stays on this page only. Processing results are temporary even when you save the draft.','原图仅留在当前页面。即使保存草稿，比对结果也仅在当前页面显示。')}</p><button disabled={locked} onClick={()=>void apply({event_id:crypto.randomUUID(),expected_revision:view.revision,kind:'allow_save',values:{}})}>{say('Save photo check draft','保存照片比对草稿')}</button></>:<>
   {filePending?<button disabled={locked||!onView} onClick={()=>void saveOriginal()}>{say('Save comparison original','保存比对原图')}</button>:null}
   {source&&!filePending?<p>{say('The comparison original is saved. Saving did not start processing.','比对原图已保存，保存操作未启动识别处理。')}</p>:null}
  </>}
  <p>{say('Appearance cannot confirm medication identity, dose, safe use or ingestion.','外观不能确认药物身份、剂量、安全用法或已经服药。')}</p>
  <label className="consent"><input type="checkbox" checked={consent} disabled={locked} onChange={event=>setConsent(event.target.checked)}/>{say('I allow this photo to be sent for this visual check.','我允许将此照片发送用于本次外观比对。')}</label>
  <button className="primary" disabled={locked||!consent||(view.save_mode==='allowed'?(!source||filePending):!file)} onClick={()=>void query()}>{say('Check photo','开始比对照片')}</button>
  {working?<p role="status">{say('Checking the current photo…','正在核查当前照片…')}</p>:null}
  {error?<p role="alert">{error==='original'?say('The original save is unconfirmed. Your selected file is retained; check status before retrying.','原图保存结果尚未确认，所选文件仍保留，请先核查状态再重试。'):error==='query'?say('The photo check did not finish. Your original is retained. Retry only when you choose.','照片比对未完成，原图仍保留，您可以明确选择重试。'):say('The task request did not finish. Your page photo is retained.','办理请求未完成，当前页面的照片仍保留。')}</p>:null}
  {error==='original'?<button disabled={locked} onClick={()=>void workflowApi.view(view.task_id).then(next=>{if(live.current)onView?.(next);}).catch(()=>{if(live.current)setError('original');})}>{say('Check original save status','核查原图保存状态')}</button>:null}
  {answer?<div aria-live="polite"><p>{word(answer.reason_key)}</p>{answer.selected_medication?<p>{answer.selected_medication}</p>:null}
   {answer.candidates.length?<><h3>{say('Catalogue clues to check against the label','供核对标签的目录线索')}</h3><ul>{answer.candidates.map((row,index)=><li key={index}>{`${row.name}${row.strength?` · ${row.strength}`:''} (${say('US catalogue','美国目录')})`}</li>)}</ul></>:null}
   <p>{say('This check does not record taking a dose, update a plan or create a reference photo.','本次比对不会记录服药、修改用药计划或建立参考照片。')}</p>
   <p>{say('Results stay on this page. Reopening the task requires another explicit check.','结果仅留在当前页面，重新打开办理任务后需明确发起新的比对。')}</p>
  </div>:null}
  {page>0?<button disabled={locked} onClick={()=>void apply({event_id:crypto.randomUUID(),expected_revision:view.revision,kind:'provide_fields',values:{page:page-1}})}>{say('Previous page','上一页')}</button>:null}
  {page+1<pages?<button disabled={locked} onClick={()=>void apply({event_id:crypto.randomUUID(),expected_revision:view.revision,kind:'provide_fields',values:{page:page+1}})}>{say('Next page','下一页')}</button>:null}
 </div>;
}
