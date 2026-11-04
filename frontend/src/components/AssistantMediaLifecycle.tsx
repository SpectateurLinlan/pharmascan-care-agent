import {useEffect,useRef,useState} from 'react';
import {api,type GalleryImage,type MedicationLibraryPdf} from '../api/client';
import type {JsonValue,WorkflowEventHandler,WorkflowView} from '../api/assistantWorkflows';
import {workflowChoice} from '../assistantWorkflowActions';
import {useLanguage} from '../language';
import {BottomSheet} from './BottomSheet';
import {PhotoMetadataFields,PdfMetadataFields} from './MediaMetadataFields';
import './AssistantMediaActions.css';

const record=(value:JsonValue|undefined):Record<string,JsonValue>=>value&&typeof value==='object'&&!Array.isArray(value)?value:{};

export function AssistantMediaLifecycle({view,busy,onEvent,onDirtyChange,onClinicalChanged}:{
 view:WorkflowView;busy:boolean;onEvent:WorkflowEventHandler;onDirtyChange?:(dirty:boolean)=>void;onClinicalChanged?:(()=>void)|undefined;
}){
 const {language,t}=useLanguage(),say=(en:string,zh:string)=>language==='zh'?zh:en;
 const capability=view.capability_id,photo=capability.startsWith('gallery.'),editing=capability.endsWith('edit');
 const review=record(view.visible_fields.media_review),payload=record(review.payload);
 const target=record(view.visible_fields.media_target??review.target),inputs=view.input_fields??{};
 const [open,setOpen]=useState(false),[working,setWorking]=useState(false),[uncertain,setUncertain]=useState(false),[error,setError]=useState(false),[dirty,setDirty]=useState(false);
 const [kind,setKind]=useState((inputs.image_kind??target.image_kind??'package') as GalleryImage['image_kind']);
 const [description,setDescription]=useState(String(inputs.source_description??inputs.description??target.source_description??target.description??''));
 const [title,setTitle]=useState(String(inputs.title??target.display_title??''));
 const [category,setCategory]=useState((inputs.category??target.category??'other') as MedicationLibraryPdf['category']);
 const pending=useRef(false),callback=useRef(onDirtyChange);callback.current=onDirtyChange;
 useEffect(()=>{callback.current?.(open||working||dirty);return()=>callback.current?.(false);},[open,working,dirty]);
 const choice=view.actions.find(action=>action.kind==='choice'&&['media.medication','media.photo_target','media.pdf_target'].includes(action.action_id));
 const cleanupReview=view.state==='outcome_unknown'&&view.storage_state==='cleanup_pending'&&view.result_ref?.kind==='file'
  &&capability.endsWith('delete')&&review.cleanup_retry===true;
 const bound=view.save_mode==='allowed'&&(view.state==='awaiting_confirmation'&&view.result_ref?.kind==='media_review'||cleanupReview)
  &&view.actions.some(action=>action.kind==='existing_review'&&action.component_key==='existing_media_management'&&action.owned_ref.id===view.result_ref?.id&&action.expected_version===view.result_ref.version);
 const fields=photo?{image_kind:kind,source_description:description}:{title,category,description};
 async function event(kind:Parameters<WorkflowEventHandler>[0]['kind'],values:Record<string,JsonValue>={}){
  const result=await onEvent({event_id:crypto.randomUUID(),expected_revision:view.revision,kind,values});
  if(!result||result.task_id!==view.task_id||result.revision<view.revision||(kind!=='report_business_result'&&result.revision===view.revision))throw new Error('Check the current media task.');
  return result;
 }
 async function dispatch(kind:Parameters<WorkflowEventHandler>[0]['kind'],values:Record<string,JsonValue>={}){
  setError(false);try{await event(kind,values);setDirty(false);}catch{setError(true);}
 }
 async function checkResult(){
  const next=await event('report_business_result');setOpen(false);
  if(next.state==='completed'){setUncertain(false);onClinicalChanged?.();}
 }
 async function confirm(){
  if(!bound||pending.current||uncertain||typeof review.target_id!=='string')return;
  pending.current=true;setWorking(true);setError(false);
  const binding={task_id:view.task_id,expected_revision:view.revision},id=review.target_id;
  try{
   if(capability==='gallery.photo.retire')await api.retireReference(id,binding);
   else if(photo)await api.manageReference(id,payload as unknown as Parameters<typeof api.manageReference>[1],binding);
   else if(capability==='library.pdf.delete')await api.deleteLibraryPdf(id,binding);
   else await api.updateLibraryPdf(id,payload as unknown as Parameters<typeof api.updateLibraryPdf>[1],binding);
   await checkResult();
  }catch{setError(true);setUncertain(true);}finally{pending.current=false;setWorking(false);}
 }
 const consequence=capability.endsWith('edit')?say('File information will change. Medication instructions and past records will be preserved.','将修改文件信息，用药说明和历史记录会保留。')
  :capability==='gallery.photo.remove'?say('The photo will leave the gallery. The original evidence file will be preserved.','照片将移出图库，原始证据文件会保留。')
  :capability==='gallery.photo.retire'?say('The photo will stop being used for comparison. The photo and medication records will be preserved.','将停用此照片的比对资格，照片和药物记录会保留。')
  :say('This private file will be deleted. Linked source and medication history remain protected.','将删除此私有文件，关联的来源及用药历史仍受保护。');
 const confirmLabel=editing?say('Save changes','保存更改'):capability==='gallery.photo.remove'?say('Remove photo','移出照片'):capability==='gallery.photo.retire'?say('Stop comparison','停用比对'):photo?say('Delete photo','删除照片'):say('Delete file','删除文件');
 const photoNames:Record<string,string>={loose_pill:'Loose pill',blister:'Blister',package:'Packaging',source:'Other or unknown'};
 const documentNames:Record<string,string>={prescription:'Prescription',pharmacy_document:'Pharmacy document',medication_instructions:'Medication instructions',other:'Other document'};
 if(view.state==='completed')return view.visible_fields.actual_result_available===false?<p>{say('This action was saved earlier. Its current file details cannot be checked right now.','此操作此前已保存，当前暂时无法核查文件详情。')}</p>:view.visible_fields.historical_result?null:<p>{say('The actual file result was checked.','已核查实际文件操作结果。')}</p>;
 if(view.state==='suspended'||view.state==='cancelled')return null;
 const notice=error?<p role="alert">{uncertain?say('The result is unknown. Your reviewed details are retained. Check the file result before trying again.','操作结果尚未确认，已保留核对资料，请先核查结果再重试。'):say('This request did not finish. Your entered details are still here. Try again.','本次请求未完成，已保留输入资料，请重试。')}</p>:null;
 if(view.result_ref?.kind==='media_review'&&(!bound||view.prompt_key==='assistant.media.check_result'))return <div className="assistant-media"><button disabled={busy||working} onClick={()=>void checkResult().catch(()=>setError(true))}>{say('Check file result','核查文件结果')}</button>{notice}</div>;
 if(bound)return <div className="assistant-media"><button disabled={busy} onClick={()=>setOpen(true)}>{say('Review file action','核对文件操作')}</button>
  {editing?<button disabled={busy||working||uncertain} onClick={()=>void dispatch('provide_fields',photo?{image_kind:inputs.image_kind??null,source_description:inputs.source_description??null}:{title:inputs.title??null,category:inputs.category??null,description:inputs.description??null})}>{say('Edit file details','编辑文件资料')}</button>:null}
  {open?<BottomSheet title={say('Review file action','核对文件操作')} busy={working} onCancel={()=>setOpen(false)}>
   <p>{String(review.medication_name??'')}</p><p>{String(target.source_description??target.display_title??'')}</p><p>{say('File version','文件版本')}: {String(target.version)}</p><p>{consequence}</p>
   {editing?<dl>{photo?<><dt>{t('Photo content')}</dt><dd>{t(photoNames[String(payload.image_kind)]??'Other or unknown')}</dd><dt>{t('Photo description and source')}</dt><dd>{String(payload.source_description)}</dd></>:<><dt>{t('File title')}</dt><dd>{String(payload.title)}</dd><dt>{t('Document category')}</dt><dd>{t(documentNames[String(payload.category)]??'Other document')}</dd><dt>{t('Description (optional)')}</dt><dd>{String(payload.description)}</dd></>}</dl>:null}
   {review.cleanup_retry?<p>{say('The record was marked deleted. Retry the remaining private-file cleanup.','记录已标记删除，请重试剩余的私有文件清理。')}</p>:null}
   {notice}{uncertain?<button disabled={working} onClick={()=>void checkResult().catch(()=>setError(true))}>{say('Check file result','核查文件结果')}</button>:null}
   <div className="actions"><button className="primary" disabled={working||uncertain} onClick={()=>void confirm()}>{confirmLabel}</button><button disabled={working} onClick={()=>setOpen(false)}>{t('Cancel')}</button></div>
  </BottomSheet>:notice}
 </div>;
 const pages=Number(view.visible_fields.page_count??1),page=Number(view.visible_fields.page??0);
 return <div className="assistant-media">
  {choice?.kind==='choice'?<div className="actions">{choice.options.map(option=><button key={option.value} disabled={busy} onClick={()=>{const selected=workflowChoice(view,choice,option.value);void dispatch(selected.kind,selected.values);}}>{say('Select','选择')}: {option.label_text}</button>)}</div>:null}
  {!target.id&&view.missing_fields.length&&!choice?<p>{say('There are no matching files to select.','暂无可选择的相关文件。')}</p>:null}
  {target.id?<><h3>{String(view.visible_fields.medication_name??'')}</h3><p>{String(target.source_description??target.display_title??'')}</p><p>{consequence}</p>
   {editing?<><div className="assistant-media">{photo?<PhotoMetadataFields t={t} disabled={busy} kind={kind} description={description} onKind={value=>{setKind(value);setDirty(true);}} onDescription={value=>{setDescription(value);setDirty(true);}}/>:<PdfMetadataFields t={t} disabled={busy} title={title} category={category} description={description} onTitle={value=>{setTitle(value);setDirty(true);}} onCategory={value=>{setCategory(value);setDirty(true);}} onDescription={value=>{setDescription(value);setDirty(true);}}/>}</div>
    <button disabled={busy||!(photo?description.trim():title.trim())} onClick={()=>void dispatch('provide_fields',fields)}>{say('Apply file details','使用文件资料')}</button>
   </>:null}
   {view.state==='ready_for_review'&&view.save_mode==='allowed'?<button disabled={busy||dirty} onClick={()=>void dispatch('prepare_confirmation')}>{say('Prepare file review','准备文件核对')}</button>:null}
  </>:null}
  {page>0?<button disabled={busy} onClick={()=>void dispatch('provide_fields',{page:page-1})}>{say('Previous page','上一页')}</button>:null}
  {page+1<pages?<button disabled={busy} onClick={()=>void dispatch('provide_fields',{page:page+1})}>{say('Next page','下一页')}</button>:null}{notice}
 </div>;
}
