/** A disconnect is reconciled by GET, never by repeating a message POST. */
import {authenticatedResponse} from './client';
import {abortable} from './abortable';
import {readWorkflowRun} from './assistantWorkflows';
import type {RunProgress,RunStatus,WorkflowMessageRequest,WorkflowMessageResponse} from './assistantWorkflows';

export class WorkflowStreamError extends Error {
 constructor(readonly status:RunStatus|'unknown',readonly runId:string){
  super(status==='cancelled'?'Processing stopped. Completed changes remain saved.':
   'The response connection ended. Check conversation history or saved drafts before sending again.');
 }
}
const kinds=new Set(['run_started','step_started','step_completed','step_failed','run_cancelling','run_completed','run_cancelled','run_failed']);
const statuses=new Set(['running','cancelling','completed','cancelled','failed']);
const terminal=(status:string)=>['completed','cancelled','failed'].includes(status);

export async function sendWorkflowStream(input:WorkflowMessageRequest,runId:string,options:{signal?:AbortSignal;onEvent?:(event:RunProgress)=>void}):Promise<WorkflowMessageResponse>{
 const lifetime=new AbortController();
 const abortRequest=()=>lifetime.abort();
 options.signal?.addEventListener('abort',abortRequest,{once:true});
 if(options.signal?.aborted)lifetime.abort();
 const timer=setTimeout(abortRequest,60_000);
 const signal=lifetime.signal;
 let reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
 let sequence=0,buffer='',status:RunStatus|'unknown'='unknown',result:WorkflowMessageResponse|undefined;
 const abort=()=>{void reader?.cancel().catch(()=>{});};
 const consume=(raw:string)=>{
  const lines=raw.split('\n'),kind=lines.find(line=>line.startsWith('event:'))?.slice(6).trim();
  const data=JSON.parse(lines.filter(line=>line.startsWith('data:')).map(line=>line.slice(5).trimStart()).join('\n'));
  if(!data||data.run_id!==runId)throw new Error('Invalid run');
  if(kind==='progress'){
   if(result||terminal(status)||!kinds.has(data.kind)||!statuses.has(data.status)||!Number.isInteger(data.sequence)||data.sequence!==sequence+1||sequence>=128
    ||![null,'application','model','tool'].includes(data.action_key??null)
    ||(sequence===0&&data.kind!=='run_started')
    ||(data.kind==='run_completed'&&data.status!=='completed')
    ||(data.kind==='run_cancelled'&&data.status!=='cancelled')
    ||(data.kind==='run_failed'&&data.status!=='failed'))throw new Error('Invalid progress');
   sequence=data.sequence;status=data.status;options.onEvent?.(data as RunProgress);
  }else if(kind==='result'){
   if(result||status!=='completed'||typeof data.result?.reply?.message!=='string'||typeof data.result.reply.session_id!=='string'||typeof data.result.reply.mode!=='string')throw new Error('Invalid result');
   result=data.result as WorkflowMessageResponse;
  }else throw new Error('Unknown event');
 };
 try{
  const response=await abortable(()=>authenticatedResponse('/api/agent/workflows/messages/stream',{method:'POST',body:JSON.stringify({...input,run_id:runId}),signal}),signal);
  if(!response.headers.get('content-type')?.includes('text/event-stream')||!response.body)throw new Error('Stream unavailable');
  reader=response.body.getReader();
  signal.addEventListener('abort',abort,{once:true});
  if(signal.aborted){abort();throw new Error('Aborted');}
  const decoder=new TextDecoder();
  while(true){
   const {value,done}=await reader.read();
   if(signal.aborted)throw new Error('Aborted');
   buffer+=done?decoder.decode():decoder.decode(value,{stream:true});
   buffer=buffer.replace(/\r\n/g,'\n');
   if(buffer.length>1_000_000)throw new Error('Frame too large');
   let end:number;
   while((end=buffer.indexOf('\n\n'))!==-1){const frame=buffer.slice(0,end);buffer=buffer.slice(end+2);if(frame.trim()&&!frame.startsWith(':'))consume(frame);}
   if(done)break;
  }
  if(buffer.trim()||!['completed'].includes(status)||!result)throw new Error('Incomplete result');
  return result;
 }catch{
  if(!signal.aborted&&!terminal(status)){
   try{const snapshot=await abortable(()=>readWorkflowRun(runId,signal),signal);if(statuses.has(snapshot.status))status=snapshot.status;}catch{/* Unknown remains explicit. */}
  }
  throw new WorkflowStreamError(status,runId);
 }finally{
  clearTimeout(timer);signal.removeEventListener('abort',abort);
  options.signal?.removeEventListener('abort',abortRequest);
  if(reader){await reader.cancel().catch(()=>{});reader.releaseLock();}
 }
}
