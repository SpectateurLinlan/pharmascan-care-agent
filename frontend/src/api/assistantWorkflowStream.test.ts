// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import * as stream from './assistantWorkflowStream';
import type {WorkflowMessageRequest} from './assistantWorkflows';
import {accessToken} from './auth';

vi.mock('./auth',()=>({accessToken:vi.fn().mockResolvedValue('DEMO-token')}));
afterEach(()=>{vi.unstubAllGlobals();vi.clearAllMocks();vi.useRealTimers();});
const run='00000000-0000-4000-8000-000000000001';
const input={text:'DEMO',workspace_id:run,client_turn_id:run,session_id:null,slots:{}} satisfies WorkflowMessageRequest;
const event=(sequence:number,kind:string,status='running')=>`event: progress\ndata: ${JSON.stringify({sequence,run_id:run,kind,status,action_key:null})}\n\n`;
const answer={reply:{message:'DEMO 布洛芬',session_id:run,mode:'rules'},workflow:null,explanations:[]};
const result=()=>`event: result\ndata: ${JSON.stringify({run_id:run,result:answer})}\n\n`;

it('bounds an authentication wait before the initial stream request',async()=>{
 vi.useFakeTimers();vi.mocked(accessToken).mockImplementationOnce(()=>new Promise<string|null>(()=>{}));
 const fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);
 let settled=false;const pending=stream.sendWorkflowStream(input,run,{});
 void pending.catch(()=>{settled=true;});
 await vi.advanceTimersByTimeAsync(60_001);
 expect(settled).toBe(true);await expect(pending).rejects.toBeInstanceOf(stream.WorkflowStreamError);
 expect(fetcher).not.toHaveBeenCalled();
},2000);

it.each(['headers','body'])('bounds a stalled reconciliation GET %s without another message POST',async phase=>{
 vi.useFakeTimers();let entered!:()=>void;
 const statusStarted=new Promise<void>(resolve=>{entered=resolve;});
 const cancelled=vi.fn();
 const fetcher=vi.fn().mockImplementation((_path,init)=>{
  if(init.method==='POST')return Promise.resolve(new Response(event(1,'run_started'),{headers:{'Content-Type':'text/event-stream'}}));
  entered();return phase==='headers'?new Promise(()=>{}):Promise.resolve(new Response(new ReadableStream({start(){},cancel:cancelled})));
 });vi.stubGlobal('fetch',fetcher);
 let settled=false;const pending=stream.sendWorkflowStream(input,run,{});
 void pending.catch(()=>{settled=true;});await statusStarted;
 await vi.advanceTimersByTimeAsync(60_001);
 expect(settled).toBe(true);
 await expect(pending).rejects.toBeInstanceOf(stream.WorkflowStreamError);
 expect(fetcher.mock.calls.filter(([,init])=>init.method==='POST')).toHaveLength(1);
 expect(fetcher.mock.calls.filter(([,init])=>init.method==='GET')).toHaveLength(1);
 if(phase==='body')expect(cancelled).toHaveBeenCalledOnce();
},2000);

it('provides an authenticated bounded stream client',()=>{
 expect(typeof stream.sendWorkflowStream).toBe('function');
});

it('reads split UTF-8 ordered events and a complete result with one bearer POST',async()=>{
 const bytes=new TextEncoder().encode(event(1,'run_started')+event(2,'run_completed','completed')+result());
 const fetcher=vi.fn().mockResolvedValue(new Response(new ReadableStream({start(controller){
  for(const byte of bytes)controller.enqueue(new Uint8Array([byte]));controller.close();
 }}),{headers:{'Content-Type':'text/event-stream'}}));vi.stubGlobal('fetch',fetcher);
 const events:unknown[]=[];
 expect(await stream.sendWorkflowStream(input,run,{onEvent:value=>events.push(value)})).toEqual(answer);
 expect(events).toHaveLength(2);expect(fetcher).toHaveBeenCalledTimes(1);
 expect(fetcher.mock.calls[0]![1].method).toBe('POST');
 expect(fetcher.mock.calls[0]![1].headers.Authorization).toBe('Bearer DEMO-token');
 expect(fetcher.mock.calls[0]![0]).not.toContain('DEMO-token');
});

it.each(['gap','duplicate','disconnect','cancelled','wrong-run','duplicate-result'])('rejects %s without a second message POST',async failure=>{
 let body=event(1,'run_started');
 if(failure==='gap')body+=event(3,'step_started');
 if(failure==='duplicate')body+=event(1,'step_started');
 if(failure==='cancelled')body+=event(2,'run_cancelled','cancelled');
 if(failure==='wrong-run')body=body.replace(run,'foreign');
 if(failure==='duplicate-result')body+=event(2,'run_completed','completed')+result()+result();
 const fetcher=vi.fn().mockImplementation((_path,init)=>Promise.resolve(init.method==='POST'
  ?new Response(body,{headers:{'Content-Type':'text/event-stream'}})
  :new Response(JSON.stringify({status:'failed',metadata:{run_id:run},events:[]}))));vi.stubGlobal('fetch',fetcher);
 await expect(stream.sendWorkflowStream(input,run,{})).rejects.toBeInstanceOf(stream.WorkflowStreamError);
 expect(fetcher.mock.calls.filter(([,init])=>init.method==='POST')).toHaveLength(1);
 expect(fetcher.mock.calls.filter(([,init])=>init.method==='GET').length).toBeLessThanOrEqual(1);
});

it('aborts the body reader after headers without resending or leaking a reader',async()=>{
 const cancelled=vi.fn();let started!:()=>void;
 const entered=new Promise<void>(resolve=>{started=resolve;});
 const fetcher=vi.fn().mockResolvedValue(new Response(new ReadableStream({start(controller){controller.enqueue(new TextEncoder().encode(event(1,'run_started')));},cancel:cancelled}),{headers:{'Content-Type':'text/event-stream'}}));vi.stubGlobal('fetch',fetcher);
 const controller=new AbortController();
 const pending=stream.sendWorkflowStream(input,run,{signal:controller.signal,onEvent:()=>started()});
 await entered;controller.abort();
 await expect(pending).rejects.toBeInstanceOf(stream.WorkflowStreamError);
 expect(cancelled).toHaveBeenCalledOnce();expect(fetcher).toHaveBeenCalledOnce();
});

it('ends a stalled response at the client limit without a retry POST',async()=>{
 vi.useFakeTimers();
 const cancelled=vi.fn();let started!:()=>void;
 const entered=new Promise<void>(resolve=>{started=resolve;});
 const fetcher=vi.fn().mockResolvedValue(new Response(new ReadableStream({start(controller){controller.enqueue(new TextEncoder().encode(event(1,'run_started')));},cancel:cancelled}),{headers:{'Content-Type':'text/event-stream'}}));vi.stubGlobal('fetch',fetcher);
 const pending=stream.sendWorkflowStream(input,run,{onEvent:()=>started()});
 const outcome=expect(pending).rejects.toBeInstanceOf(stream.WorkflowStreamError);
 await entered;await vi.advanceTimersByTimeAsync(60_000);await outcome;
 expect(cancelled).toHaveBeenCalledOnce();expect(fetcher).toHaveBeenCalledOnce();
},2000);
