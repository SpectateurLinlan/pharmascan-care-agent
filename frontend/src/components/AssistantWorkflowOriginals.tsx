import {useEffect,useRef,useState} from 'react';
import {workflowApi,type OriginalView,type WorkflowView} from '../api/assistantWorkflows';
import type {WorkflowFile} from '../assistantWorkflowState';
import {useLanguage} from '../language';

/** Authenticated, page-owned original viewer. No persisted URL or public storage key. */
export function AssistantWorkflowOriginals({view,files,busy,consent,onConsent,onView}:{
 view:WorkflowView;files:WorkflowFile[];busy:boolean;consent:boolean;onConsent:(allowed:boolean)=>void;onView:(view:WorkflowView)=>void;
}){
 const {language}=useLanguage();const say=(en:string,zh:string)=>language==='zh'?zh:en;
 const [rows,setRows]=useState<OriginalView[]>([]),[images,setImages]=useState<Record<string,string>>({});
 const [loading,setLoading]=useState(false),[working,setWorking]=useState(false),[failed,setFailed]=useState(false),[notice,setNotice]=useState('');
 const live=useRef(true),urls=useRef(new Set<string>()),pending=useRef(false);
 const [retryFiles,setRetryFiles]=useState<Record<string,File>>({});
 const ephemeral=view.save_mode==='ephemeral',pdf=view.capability_id==='library.pdf.add';
 useEffect(()=>{live.current=true;const ownedUrls=urls.current;return()=>{live.current=false;for(const url of ownedUrls)URL.revokeObjectURL(url);ownedUrls.clear();};},[]);
 useEffect(()=>{
  let current=true;
  if(ephemeral){setRows([]);setImages({});for(const url of urls.current)URL.revokeObjectURL(url);urls.current.clear();return;}
  setLoading(true);setFailed(false);
  void workflowApi.originals(view.task_id).then(result=>{if(current)setRows(result);}).catch(()=>{if(current)setFailed(true);}).finally(()=>{if(current)setLoading(false);});
  return()=>{current=false;};
 },[view.task_id,view.revision,view.state,ephemeral]);
 async function refresh(){
  let latest=await workflowApi.view(view.task_id);
  if(latest.save_mode==='ephemeral'&&Object.keys(view.visible_fields).length)latest=await workflowApi.preview(view.task_id,{capability_id:view.capability_id,fields:view.visible_fields});
  if(live.current)onView(latest);
  const originals=latest.save_mode==='allowed'?await workflowApi.originals(view.task_id):[];
  if(live.current)setRows(originals);
  return latest;
 }
 async function run(action:()=>Promise<void>){
  if(pending.current)return;pending.current=true;setWorking(true);setNotice('');
  try{await action();}catch{if(live.current)setNotice(say('The result could not be confirmed. Check status before retrying.','暂时无法确认结果，请先核查状态再重试。'));}
  finally{pending.current=false;if(live.current)setWorking(false);}
 }
 async function show(row:OriginalView){
  await run(async()=>{const blob=await workflowApi.originalBlob(view.task_id,row.id);if(!live.current)return;
   const url=URL.createObjectURL(blob);urls.current.add(url);setImages(old=>{const previous=old[row.id];if(previous){URL.revokeObjectURL(previous);urls.current.delete(previous);}return {...old,[row.id]:url};});});
 }
 async function process(row:OriginalView){
  await run(async()=>{
   const latest=await workflowApi.view(view.task_id);if(!live.current)return;
   const result=row.state==='reserved'||latest.state==='outcome_unknown'?await workflowApi.recoverOriginal(view.task_id,row.id,latest.revision):await workflowApi.previewOriginal(view.task_id,row.id,latest.revision,consent,crypto.randomUUID());
   if(!live.current)return;onView(result.workflow);setRows(old=>old.map(item=>item.id===row.id?result.attachment:item));
   setNotice(say('Original status updated. Review the details before continuing.','已更新原图状态，请核对资料后继续。'));
  });
 }
 async function retryFile(row:OriginalView){
  const file=retryFiles[row.id];if(!file)return;
  await run(async()=>{const latest=await workflowApi.view(view.task_id);if(!live.current)return;
   const result=await workflowApi.retryOriginal(view.task_id,row.id,file,latest.revision,consent);
   if(!live.current)return;onView(result.workflow);setRows(old=>old.map(item=>item.id===row.id?result.attachment:item));
   setRetryFiles(old=>{const next={...old};delete next[row.id];return next;});
   setNotice(say('Original status updated. Review the details before continuing.','已更新原图状态，请核对资料后继续。'));
  });
 }
 const locked=busy||working;
 return <section aria-label={pdf?say('Task PDF originals','办理 PDF 原文件'):say('Task photos','办理照片')}>
  {files.filter(file=>ephemeral||!file.attachment_id).map(file=><div key={file.upload_id}><p>{file.file.name}</p><p>{ephemeral?say('Page copy only. Refreshing loses this photo.','仅在当前页面保留，刷新后会丢失此照片。'):say('Page copy retained while saving is checked.','核查保存结果期间，页面仍保留此照片。')}</p></div>)}
  {loading?<p role="status">{say('Loading originals...','正在读取原图……')}</p>:null}
  {failed?<p role="status">{say('Could not load original status.','暂时无法读取原图状态。')}</p>:null}
  {rows.some(row=>row.extraction_status!=='not_requested')?<label><input type="checkbox" checked={consent} disabled={locked} onChange={event=>onConsent(event.target.checked)}/>{say('Allow recognition of saved photos','允许识别已保存的照片')}</label>:null}
  {rows.map((row,index)=><div key={row.id}>
   <p>{row.content_type==='application/pdf'?say(`Original PDF ${index+1}`,`原始 PDF ${index+1}`):say(`Original ${index+1}`,`原图 ${index+1}`)} · {row.state==='saved'?say('Saved','已保存'):say('Save outcome needs checking','需核查保存结果')}</p>
   <button disabled={locked||row.state!=='saved'} onClick={()=>void show(row)}>{row.content_type==='application/pdf'?say(`View original PDF ${index+1}`,`查看原始 PDF ${index+1}`):say(`View original ${index+1}`,`查看原图 ${index+1}`)}</button>
   {images[row.id]?row.content_type==='application/pdf'?<div className="actions"><a href={images[row.id]} target="_blank" rel="noopener noreferrer">{say('Open original PDF','打开原始 PDF')}</a><a href={images[row.id]} download={String(view.input_fields?.filename??'original.pdf')}>{say('Download original PDF','下载原始 PDF')}</a></div>:<img src={images[row.id]} alt={say(`Saved original ${index+1}`,`已保存原图 ${index+1}`)} style={{maxWidth:'100%',maxHeight:320,objectFit:'contain'}}/>:null}
   {row.reason==='provider_unavailable'?<p>{say('Photo recognition is unavailable. The original is still saved.','暂时无法使用图片识别服务，原图仍已保存。')}</p>:row.reason==='extraction_rejected'?<p>{say('The photo could not be read. The original is still saved.','暂时无法读取照片资料，原图仍已保存。')}</p>:null}
   {row.extraction_status==='interrupted'?<p>{say('The previous recognition result is unavailable. You can explicitly retry recognition.','上次识别结果不可用，您可以明确选择再次识别。')}</p>:null}
   {row.extraction_status==='not_requested'&&row.state==='saved'?<p>{row.content_type==='application/pdf'?say('This original PDF has not been read or used to change instructions.','此原始 PDF 未被读取或用于更改用药说明。'):view.capability_id==='source.preview'?say('Saving this original did not extract source text.','保存此原图未提取来源文字。'):view.capability_id==='image.compare'?say('Saving this original did not run a photo check.','保存此原图未启动照片比对。'):say('No medication recognition was requested for this gallery original.','此图库原图未请求进行药物识别。')}</p>:row.state==='reserved'||row.extraction_status!=='succeeded'?<button disabled={locked||(row.state==='saved'&&!consent&&view.state!=='outcome_unknown')} onClick={()=>void process(row)}>{row.state==='reserved'?pdf?say('Check PDF original save result','核查 PDF 原文件保存结果'):say('Check original save result','核查原图保存结果'):view.state==='outcome_unknown'?say('Check recognition result','核查识别结果'):row.extraction_status==='consent_required'?say('Recognize saved photo','识别已保存照片'):say('Retry recognition','重试识别')}</button>:<p>{say('Recognition completed. Details still need review.','识别已完成，资料仍需核对。')}</p>}
   {row.state==='reserved'?<div><p>{say('If saving was interrupted, choose the same original file to retry.','如果保存中断，请选择同一原始文件重试。')}</p><label>{say(`Original file ${index+1}`,`原始文件 ${index+1}`)}<input type="file" accept={row.content_type==='application/pdf'?'application/pdf,.pdf':'image/png,image/jpeg'} disabled={locked} onChange={event=>{const file=event.currentTarget.files?.[0];if(file){if(row.content_type==='application/pdf'?file.size>10*1024*1024||!file.name.toLowerCase().endsWith('.pdf')||Boolean(file.type&&file.type!=='application/pdf'):file.size>8_000_000||!['image/png','image/jpeg'].includes(file.type))setNotice(row.content_type==='application/pdf'?say('Choose a PDF no larger than 10 MB.','请选择不大于 10 MB 的 PDF。'):say('Choose a PNG or JPEG smaller than 8 MB.','请选择小于 8 MB 的 PNG 或 JPEG 图片。'));else setRetryFiles(old=>({...old,[row.id]:row.content_type==='application/pdf'&&!file.type?new File([file],file.name,{type:'application/pdf'}):file}));}event.currentTarget.value='';}}/></label>{retryFiles[row.id]?<p>{retryFiles[row.id]?.name}</p>:null}<button disabled={locked||!retryFiles[row.id]} onClick={()=>void retryFile(row)}>{pdf?say(`Retry saving original PDF ${index+1}`,`重试保存原始 PDF ${index+1}`):say(`Retry saving original ${index+1}`,`重试保存原图 ${index+1}`)}</button></div>:null}
  </div>)}
  {view.cleanup_pending||view.storage_state==='cleanup_pending'?<button disabled={locked} onClick={()=>void run(async()=>{await workflowApi.retryCleanup(view.task_id);await refresh();if(live.current)setNotice(say('Cleanup status checked.','已核查清理状态。'));})}>{say('Retry original cleanup','重试清理原图')}</button>:null}
  {failed||notice||files.some(file=>!file.attachment_id)?<button disabled={locked||loading} onClick={()=>void run(async()=>{await refresh();if(live.current){setFailed(false);setNotice(say('Original status checked.','已核查原图状态。'));}})}>{say('Check original status','核查原图状态')}</button>:null}
  {notice?<p role="status">{notice}</p>:null}
 </section>;
}
