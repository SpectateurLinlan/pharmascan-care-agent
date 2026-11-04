import {useEffect,useRef,useState} from 'react';
import {api,type MedicationLibraryPdf} from '../api/client';
import {workflowApi,type JsonValue,type WorkflowEventHandler,type WorkflowView} from '../api/assistantWorkflows';
import {useLanguage} from '../language';
import {workflowChoice} from '../assistantWorkflowActions';
import {PdfDocumentFields} from './MediaMetadataFields';
import {BottomSheet} from './BottomSheet';
import './AssistantMediaActions.css';

export function AssistantPdfUpload({view,busy,onEvent,onView,onDirtyChange,onClinicalChanged,onOriginalUploadState}:{
 view:WorkflowView;busy:boolean;onEvent:WorkflowEventHandler;onView?:((view:WorkflowView)=>void)|undefined;
 onDirtyChange?:((dirty:boolean)=>void)|undefined;onClinicalChanged?:(()=>void)|undefined;
 onOriginalUploadState?:((task:string,active:boolean)=>void)|undefined;
}){
 const {language,t}=useLanguage(),say=(en:string,zh:string)=>language==='zh'?zh:en;
 const [file,setFile]=useState<File|null>(null),[fileOriginal,setFileOriginal]=useState<string|null>(null);
 const [filename,setFilename]=useState(String(view.input_fields?.filename??''));
 const [category,setCategory]=useState((view.input_fields?.category??'other') as MedicationLibraryPdf['category']);
 const [description,setDescription]=useState(String(view.input_fields?.description??''));
 const [dirty,setDirty]=useState(false),[working,setWorking]=useState(false),[open,setOpen]=useState(false),[consent,setConsent]=useState(false);
 const [error,setError]=useState<'file'|'original'|'draft'|'upload'|null>(null),[uncertain,setUncertain]=useState(false);
 const uploadId=useRef<string|null>(null),live=useRef(true),pending=useRef(false),current=useRef(view);current.current=view;
 const callback=useRef(onDirtyChange);callback.current=onDirtyChange;
 const stateCallback=useRef(onOriginalUploadState);stateCallback.current=onOriginalUploadState;
 const source=typeof view.input_fields?.source_attachment_id==='string'?view.input_fields.source_attachment_id:null;
 const filePending=Boolean(file&&(view.save_mode==='ephemeral'||fileOriginal===null||fileOriginal!==source));
 useEffect(()=>{live.current=true;return()=>{live.current=false;stateCallback.current?.(view.task_id,false);};},[view.task_id]);
 useEffect(()=>{callback.current?.(dirty||working||open||filePending);return()=>callback.current?.(false);},[dirty,working,open,filePending]);
 useEffect(()=>{setOpen(false);setConsent(false);setUncertain(false);setDirty(false);setError(null);
  if(view.save_mode==='ephemeral'){uploadId.current=null;setFileOriginal(null);}
  setFilename(String(view.input_fields?.filename??''));setCategory((view.input_fields?.category??'other') as MedicationLibraryPdf['category']);setDescription(String(view.input_fields?.description??''));
 },[view.revision,view.save_mode,view.input_fields?.filename,view.input_fields?.category,view.input_fields?.description]);
 const bound=view.save_mode==='allowed'&&view.state==='awaiting_confirmation'&&view.result_ref?.kind==='media_review'
  &&view.actions.some(action=>action.kind==='existing_review'&&action.component_key==='existing_media_management'&&action.owned_ref.id===view.result_ref?.id);
 const choice=view.actions.find(action=>action.kind==='choice'&&action.action_id==='pdf.medication'),locked=busy||working;
 async function event(kind:Parameters<WorkflowEventHandler>[0]['kind'],values:Record<string,JsonValue>={},revision=view.revision){
  const result=await onEvent({event_id:crypto.randomUUID(),expected_revision:revision,kind,values});
  if(!result||result.task_id!==view.task_id||result.revision<revision||(kind!=='report_business_result'&&result.revision===revision))throw new Error('Check the current PDF draft.');return result;
 }
 async function apply(kind:Parameters<WorkflowEventHandler>[0]['kind'],values:Record<string,JsonValue>={}){
  setError(null);try{await event(kind,values);if(live.current)setDirty(false);}catch{if(live.current)setError('draft');}
 }
 async function checkOriginal(){setError(null);try{const next=await workflowApi.view(view.task_id);if(live.current)onView?.(next);}catch{if(live.current)setError('original');}}
 async function saveOriginal(){
  if(!file||!onView||view.save_mode!=='allowed'||pending.current)return;
  uploadId.current??=crypto.randomUUID();pending.current=true;setWorking(true);setError(null);stateCallback.current?.(view.task_id,true);
  try{const result=await workflowApi.uploadPdfOriginal(view.task_id,uploadId.current,file,view.revision);
   if(!live.current||result.workflow.revision<current.current.revision)return;
   setFileOriginal(result.attachment.id);onView(result.workflow);
   if(result.workflow.input_fields?.source_attachment_id!==result.attachment.id)await event('provide_fields',{source_attachment_id:result.attachment.id},result.workflow.revision);
  }catch{if(live.current)setError('original');}
  finally{pending.current=false;stateCallback.current?.(view.task_id,false);if(live.current)setWorking(false);}
 }
 async function checkResult(){const next=await event('report_business_result');if(!live.current)return;setOpen(false);if(next.state==='completed'){setFile(null);setUncertain(false);onClinicalChanged?.();}else if(next.state==='awaiting_confirmation'&&next.visible_fields.upload_attempted===false&&next.result_ref?.id===view.result_ref?.id){setUncertain(false);setError(null);}}
 async function confirm(){
  if(!bound||!consent||pending.current||uncertain||!source||typeof view.input_fields?.medication_id!=='string')return;
  pending.current=true;setWorking(true);setError(null);
  try{let original:Blob|null=fileOriginal===source?file:null;
   if(!original){original=await workflowApi.originalBlob(view.task_id,source);if(!live.current)return;}
   const pdf=new File([original],String(view.input_fields.filename),{type:'application/pdf'});
   await api.uploadLibraryPdf(view.input_fields.medication_id,pdf,view.input_fields.category as MedicationLibraryPdf['category'],String(view.input_fields.description??''),{task_id:view.task_id,expected_revision:view.revision});await checkResult();
  }catch{if(live.current){setError('upload');setUncertain(true);}}
  finally{pending.current=false;if(live.current)setWorking(false);}
 }
 const notice=error?<p role="alert">{error==='file'?say('Choose a PDF no larger than 10 MB. Your previous selection is retained.','请选择不大于 10 MB 的 PDF，之前的选择仍保留。'):error==='original'?say('The original PDF save is unconfirmed. Your selected file is still here. Check status before retrying.','原始 PDF 保存结果尚未确认，所选文件仍在当前页面，请先核查状态再重试。'):error==='upload'?say('The library result is unconfirmed. Check the result before retrying; your PDF draft is retained.','资料库保存结果尚未确认，请先核查结果再重试，PDF 草稿仍保留。'):say('The draft request did not finish. Your file and entered details are still here.','草稿请求未完成，文件和输入资料仍保留。')}</p>:null;
 if(view.state==='completed')return <p>{view.visible_fields.historical_result?say('The earlier PDF upload receipt is retained.','此前的 PDF 上传回执仍保留。'):view.visible_fields.duplicate?say('This exact PDF already existed. No second file was added; its existing details are retained.','相同 PDF 已存在，没有重复添加，保留其原有资料。'):say('The PDF was saved and its library record checked.','PDF 已保存，并已核查资料库记录。')}</p>;
 if(view.state==='suspended'||view.state==='cancelled')return null;
 if(view.result_ref?.kind==='media_review'&&(!bound||view.prompt_key==='assistant.pdf.check_result'))return <div><button disabled={locked} onClick={()=>void checkResult().catch(()=>setError('upload'))}>{say('Check PDF result','核查 PDF 结果')}</button>{notice}</div>;
 if(bound)return <div className="assistant-media"><button disabled={locked} onClick={()=>setOpen(true)}>{say('Review PDF upload','核对 PDF 上传')}</button>
  {!view.visible_fields.upload_attempted?<button disabled={locked} onClick={()=>void apply('provide_fields',{filename:view.input_fields?.filename??null,category:view.input_fields?.category??null,description:view.input_fields?.description??''})}>{say('Edit PDF details','编辑 PDF 资料')}</button>:null}
  {open?<BottomSheet title={say('Add this PDF to your medication library?','将此 PDF 添加到药物资料库？')} busy={working} onCancel={()=>setOpen(false)}>
   <p>{String(view.visible_fields.medication_name??'')}</p><p>{String(view.input_fields?.filename??'')}</p>
   <p>{t(view.input_fields?.category==='prescription'?'Prescription':view.input_fields?.category==='pharmacy_document'?'Pharmacy document':view.input_fields?.category==='medication_instructions'?'Medication instructions':'Other document')}</p>
   {view.input_fields?.description?<p>{String(view.input_fields.description)}</p>:null}
   <p>{say('This stores a patient-supplied PDF. It does not read instructions, verify the document or change a medication plan.','此操作保存患者提供的 PDF，不读取用药说明、不核实文件真实性，也不修改用药计划。')}</p>
   <label className="consent"><input type="checkbox" checked={consent} disabled={working||uncertain} onChange={event=>setConsent(event.target.checked)}/>{say('I checked the medication association and agree to store this original PDF privately.','我已核对药物关联，并同意私有保存此原始 PDF。')}</label>
   {notice}{uncertain?<button disabled={working} onClick={()=>void checkResult().catch(()=>setError('upload'))}>{say('Check PDF result','核查 PDF 结果')}</button>:null}
   <div className="actions"><button className="primary" disabled={!consent||working||uncertain} onClick={()=>void confirm()}>{say('Add PDF to library','添加 PDF 到资料库')}</button><button disabled={working} onClick={()=>setOpen(false)}>{t('Cancel')}</button></div>
  </BottomSheet>:notice}
 </div>;
 const page=Number(view.visible_fields.page??0),pages=Number(view.visible_fields.page_count??1);
 return <div className="assistant-media">
  {choice?.kind==='choice'?<div className="actions">{choice.options.map(option=><button key={option.value} disabled={locked} onClick={()=>{const selected=workflowChoice(view,choice,option.value);void apply(selected.kind,selected.values);}}>{say('Select','选择')}: {option.label_text}</button>)}</div>:null}
  {view.input_fields?.medication_id?<><h3>{String(view.visible_fields.medication_name??'')}</h3>
   <label className="field">{t('Choose a PDF file')}<input type="file" accept="application/pdf,.pdf" disabled={locked} onChange={event=>{const selected=event.currentTarget.files?.[0];event.currentTarget.value='';if(!selected)return;
    if(!selected.name.toLowerCase().endsWith('.pdf')||(selected.type&&selected.type!=='application/pdf')||selected.size>10*1024*1024||!selected.size){setError('file');return;}
    setFile(selected);setFilename(selected.name);setDirty(selected.name!==view.input_fields?.filename||dirty);setFileOriginal(null);uploadId.current=null;setError(null);
   }}/></label>{file?<p>{file.name}</p>:filename?<p>{filename}</p>:null}
   <PdfDocumentFields category={category} description={description} t={t} disabled={locked} onCategory={value=>{setCategory(value);setDirty(true);}} onDescription={value=>{setDescription(value);setDirty(true);}}/>
   <button disabled={locked||!filename} onClick={()=>void apply('provide_fields',{filename,category,description})}>{say('Apply PDF details','使用 PDF 资料')}</button>
   {view.save_mode==='ephemeral'?<><p>{say('This PDF stays on this page only. Save the draft to retain the original; adding to the library still needs separate confirmation.','此 PDF 仅留在当前页面。保存草稿后才会保留原文件，加入资料库仍需单独确认。')}</p><button disabled={locked||dirty} onClick={()=>void apply('allow_save')}>{say('Save PDF draft','保存 PDF 草稿')}</button></>:<>
    {filePending?<button disabled={locked||dirty||!onView} onClick={()=>void saveOriginal()}>{say('Save original PDF','保存原始 PDF')}</button>:null}
    {source&&!filePending?<p>{say('The original PDF is saved. No content extraction was requested.','原始 PDF 已保存，未请求内容提取。')}</p>:null}
    {view.state==='ready_for_review'?<button disabled={locked||dirty||filePending} onClick={()=>void apply('prepare_confirmation')}>{say('Prepare PDF review','准备 PDF 核对')}</button>:null}
   </>}
  </>:null}
  {page>0?<button disabled={locked} onClick={()=>void apply('provide_fields',{page:page-1})}>{say('Previous page','上一页')}</button>:null}
  {page+1<pages?<button disabled={locked} onClick={()=>void apply('provide_fields',{page:page+1})}>{say('Next page','下一页')}</button>:null}
  {error==='original'?<button disabled={locked} onClick={()=>void checkOriginal()}>{say('Check PDF original status','核查 PDF 原文件状态')}</button>:null}{notice}
 </div>;
}
