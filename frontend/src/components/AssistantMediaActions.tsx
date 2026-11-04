import {useEffect,useRef,useState} from 'react';
import {api} from '../api/client';
import type {JsonValue,WorkflowEventHandler,WorkflowView} from '../api/assistantWorkflows';
import {workflowChoice} from '../assistantWorkflowActions';
import {useLanguage} from '../language';
import './AssistantMediaActions.css';

const record=(value:JsonValue|undefined):Record<string,JsonValue>=>value&&typeof value==='object'&&!Array.isArray(value)?value:{};

/** Original bytes are fetched only by the patient, never by task preparation. */
export function AssistantMediaActions({view,busy,onEvent}:{view:WorkflowView;busy:boolean;onEvent:WorkflowEventHandler}){
 const {language,t}=useLanguage(),say=(en:string,zh:string)=>language==='zh'?zh:en;
 const [url,setUrl]=useState(''),[loading,setLoading]=useState(false),[error,setError]=useState<'original'|'query'|null>(null);
 const active=useRef(true),pending=useRef(false),objectUrl=useRef('');
 useEffect(()=>{active.current=true;return()=>{active.current=false;if(objectUrl.current)URL.revokeObjectURL(objectUrl.current);};},[]);
 const photo=record(view.visible_fields.photo),file=record(view.visible_fields.file);
 const rows=Array.isArray(view.visible_fields.records)?view.visible_fields.records.map(record):[];
 const isPhoto=view.capability_id==='gallery.photo.view',isGallery=view.capability_id==='gallery.list';
 const download=view.capability_id==='library.pdf.download';
 const target=isPhoto?photo:file;
 const galleryStatus=(status:JsonValue|undefined)=>t(status==='current'?'Current':status==='upcoming'?'Upcoming':status==='historical'?'Past':'Unfinished');
 const page=Number(view.visible_fields.page??0),pages=Number(view.visible_fields.page_count??1);
 async function load(){
  if(pending.current||busy||typeof target.id!=='string')return;
  pending.current=true;setLoading(true);setError(null);
  try{
   const blob=isPhoto?await api.referencePhoto(String(target.id)):await api.libraryPdf(String(target.id),download?'attachment':'inline');
   if(!active.current)return;
   const next=URL.createObjectURL(blob);if(objectUrl.current)URL.revokeObjectURL(objectUrl.current);
   objectUrl.current=next;setUrl(next);
  }catch{if(active.current)setError('original');}finally{pending.current=false;if(active.current)setLoading(false);}
 }
 async function dispatch(event:Parameters<WorkflowEventHandler>[0]){
  setError(null);try{await onEvent(event);}catch{if(active.current)setError('query');}
 }
 const choices=view.actions.filter(action=>action.kind==='choice'&&['media.medication','media.image','media.file'].includes(action.action_id));
 const pageTo=(next:number)=>dispatch({event_id:crypto.randomUUID(),expected_revision:view.revision,kind:'provide_fields',values:{page:next}});
 return <div className="assistant-media">
  {view.visible_fields.medication_name?<h3>{String(view.visible_fields.medication_name)}</h3>:null}
  {choices.map((action,index)=>action.kind==='choice'?<div className="actions" key={index}>{action.options.map(option=><button type="button" key={option.value} disabled={busy||loading} onClick={()=>void dispatch(workflowChoice(view,action,option.value))}>{say('Select','选择')}: {option.label_text}</button>)}</div>:null)}
  {!choices.length&&view.visible_fields.total!==undefined?<>
   {rows.length?<ul>{rows.map((row,index)=><li key={String(row.id??row.medication_id??index)}>
    <strong>{String(row.name??row.display_title??'')}</strong>
    {isGallery?<p>{say('Photos','照片')}: {String(row.photo_count??0)} · {galleryStatus(row.status)}</p>:<><p>{String(row.original_filename??'')}</p><p>{String(row.description??'')}</p><p>{String(row.byte_size??0)} {say('bytes','字节')}</p></>}
   </li>)}</ul>:<p>{say(isGallery?'No photos are recorded in this view.':'No PDF documents are recorded for this medication.',isGallery?'此视图中没有已记录的照片。':'这项药物尚未保存 PDF 文件。')}</p>}
  </>:null}
  {target.id?<>
   <h3>{String(isPhoto?photo.source_description:file.display_title)}</h3>
   {!isPhoto?<><p>{String(file.original_filename??'')}</p><p>{String(file.description??'')}</p><p>{String(file.byte_size??0)} {say('bytes','字节')}</p></>:<p>{say('A saved photo does not verify medication identity, safe dosage or ingestion.','已保存照片不代表已确认药物身份、安全剂量或实际服药。')}</p>}
   {!url?<button type="button" disabled={busy||loading} onClick={()=>void load()}>{loading?say('Loading original...','正在加载原件...'):isPhoto?say('View original photo','查看原始照片'):download?say('Prepare download','准备下载'):say('Preview PDF','预览 PDF')}</button>:<>
    {isPhoto?<img className="photo-preview" src={url} alt={String(photo.source_description??say('Original photo','原始照片'))}/>:!download?<iframe title={say('PDF preview','PDF 预览')} src={url} className="assistant-media__preview"/>:null}
    {!isPhoto?<a className="button-like" href={url} download={String(file.original_filename)}>{say('Download original','下载原件')}</a>:null}
   </>}
  </>:null}
  {!isGallery&&!isPhoto?<p>{say('This PDF is stored as a document. Its medication instructions have not been extracted or reviewed here.','PDF 仅作为文件保存，此处尚未提取或核对其中的用药指示。')}</p>:null}
  {view.visible_fields.total!==undefined?<p>{say('Recorded entries','已记录条目')}: {String(view.visible_fields.total)} · {page+1}/{pages}</p>:null}
  {page>0?<button type="button" disabled={busy||loading} onClick={()=>void pageTo(page-1)}>{say('Previous page','上一页')}</button>:null}
  {page+1<pages?<button type="button" disabled={busy||loading} onClick={()=>void pageTo(page+1)}>{say('Next page','下一页')}</button>:null}
  {error?<p role="alert">{error==='original'?say('The original could not be loaded. Your selection is still here. Try again.','暂时无法加载原件，当前选择仍保留，请重试。'):say('The query did not finish. Your selection is still here. Try again.','本次查询未完成，当前选择仍保留，请重试。')}</p>:null}
 </div>;
}
