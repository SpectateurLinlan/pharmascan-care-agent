// @vitest-environment jsdom
// @vitest-environment-options {"url":"http://localhost:5173"}
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {installWorkflowDiagnostics} from './workflowDiagnostics';
import {classifyResource,performanceEvent,performanceFlag,performanceStore,workflowFromHash} from './workflowPerformanceContract';
import {api} from './client';
vi.mock('./auth',()=>({accessToken:vi.fn().mockResolvedValue('PRIVATE_TOKEN'),existingAccessToken:vi.fn()}));
let dispose=()=>{};
const callbacks=new Map<string,(entries:PerformanceEntry[])=>void>();
beforeEach(()=>{
 sessionStorage.clear();callbacks.clear();
 vi.stubGlobal('PerformanceObserver',class{
  constructor(private callback:(list:{getEntries:()=>PerformanceEntry[]})=>void){}
  observe({type}:{type:string}){callbacks.set(type,entries=>this.callback({getEntries:()=>entries}));}
  disconnect(){}
 });
 vi.stubGlobal('fetch',vi.fn());
 dispose=installWorkflowDiagnostics(window);
});
afterEach(()=>{dispose();vi.useRealTimers();vi.restoreAllMocks();vi.unstubAllGlobals();sessionStorage.clear();document.body.innerHTML='';});
const report=()=>window.medithreadWorkflows!.summary() as {captures:Array<{resources:Array<Record<string,unknown>>;api:Array<Record<string,unknown>>}>};

it('retains only allowlisted numeric critical Data API operation timings',()=>{
 window.medithreadWorkflows!.start();
 callbacks.get('resource')!([{name:'http://localhost:5173/api/me/today-attention',startTime:10,responseEnd:112,duration:102,requestStart:11,responseStart:110,transferSize:1200,encodedBodySize:1000,decodedBodySize:1000,serverTiming:[
  {name:'db_regimen_versions_read_batch',duration:90,description:'calls=1;max_ms=90.00;bytes=1000'},
  {name:'db_PRIVATE_read_one',duration:1,description:'PRIVATE_TOKEN'},
  {name:'db_dose_rules_read_regimen',duration:1,description:'calls=1;max_ms=1;bytes=4;PRIVATE_ID'},
 ]} as unknown as PerformanceEntry]);
 const result=report().captures.at(-1)!.resources.at(-1)!.server_timing;
 expect(result).toEqual({db_regimen_versions_read_batch:{duration:90,calls:1,max_ms:90,bytes:1000}});
 expect(JSON.stringify(report())).not.toContain('PRIVATE');
});

it('records essential Today readiness only after actual schedule and selected dose are ready',async()=>{
 vi.useFakeTimers();
 window.history.replaceState({},'','#today');
 document.body.innerHTML='<main id="main-content" data-load-state="ready"><section class="today-attention" data-today-schedule-state="ready" data-today-needs-dose="true"><div class="today-overview"><div data-today-dose-state="loading"></div></div></section></main>';
 window.medithreadWorkflows!.start();
 const checkpoints=()=>((window.medithreadWorkflows!.summary() as {captures:Array<{checkpoints:Array<{kind:string}>}>}).captures.at(-1)!.checkpoints);
 await vi.advanceTimersByTimeAsync(50);
 expect(checkpoints().some(row=>row.kind==='today_essential_ready')).toBe(false);
 document.querySelector('[data-today-dose-state]')!.setAttribute('data-today-dose-state','error');
 await vi.advanceTimersByTimeAsync(50);
 expect(checkpoints().some(row=>row.kind==='today_essential_ready')).toBe(false);
 const dialog=document.createElement('div');dialog.setAttribute('aria-modal','true');document.body.append(dialog);
 document.querySelector('[data-today-dose-state]')!.setAttribute('data-today-dose-state','ready');
 await vi.advanceTimersByTimeAsync(50);
 expect(checkpoints().some(row=>row.kind==='today_essential_ready')).toBe(false);
 dialog.remove();await vi.advanceTimersByTimeAsync(50);
 expect(checkpoints().filter(row=>row.kind==='today_essential_ready')).toHaveLength(1);
});

it('does nothing until opted in and sends no diagnostic requests',()=>{
 expect(window.medithreadWorkflows?.enabled).toBe(false);expect(callbacks.size).toBe(0);
 window.medithreadWorkflows!.start();expect(fetch).not.toHaveBeenCalled();
 expect(sessionStorage.getItem(performanceFlag)).toBe('normal-cache');
});

it('keeps sanitized network timing across reinstallation/reload and removes no unrelated storage',()=>{
 sessionStorage.setItem('existing-auth-session','PRIVATE_TOKEN');window.medithreadWorkflows!.start('cache-disabled');
 callbacks.get('resource')!([{name:'http://localhost:5173/api/evidence/images/PRIVATE_ID?token=PRIVATE_TOKEN',startTime:10,responseEnd:112,duration:102,requestStart:11,responseStart:110,transferSize:1200,encodedBodySize:1000,decodedBodySize:1000,serverTiming:[{name:'data',duration:90},{name:'PRIVATE',description:'PRIVATE'}]} as unknown as PerformanceEntry]);
 dispose();dispose=installWorkflowDiagnostics(window);
 const summary=report();expect(summary.captures).toHaveLength(2);
 expect(summary.captures[0]!.resources[0]).toMatchObject({endpoint:'/api/evidence/images/:id',ttfb:99,download:2,server_timing:{data:90}});
 expect(JSON.stringify(summary)).not.toContain('PRIVATE');expect(sessionStorage.getItem(performanceStore)).not.toContain('PRIVATE');
 window.medithreadWorkflows!.stop();expect(sessionStorage.getItem(performanceFlag)).toBeNull();expect(sessionStorage.getItem('existing-auth-session')).toBe('PRIVATE_TOKEN');
});

it('captures a failed bootstrap HTTP operation without exporting its private error body',async()=>{
 window.medithreadWorkflows!.start();
 vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({code:'VALIDATION_ERROR',message:'PRIVATE records',rule_id:null}),{status:422}));
 await expect(api.startDemo()).rejects.toThrow();
 const entries=report().captures[0]!.api;
 expect(entries).toEqual(expect.arrayContaining([expect.objectContaining({endpoint:'/api/demo/start',kind:'response',status:422,error:'VALIDATION_ERROR'})]));
 expect(JSON.stringify(report())).not.toContain('PRIVATE');expect(fetch).toHaveBeenCalledOnce();
});

it('rejects untrusted event and persisted strings rather than exporting them',()=>{
 window.medithreadWorkflows!.start();
 window.dispatchEvent(new CustomEvent(performanceEvent,{detail:{kind:'response',id:1,endpoint:'/api/me/caregivers',start:1,end:2,error:'PRIVATE_NAME',method:'PRIVATE',notes:'PRIVATE_BODY'}}));
 expect(JSON.stringify(report())).not.toContain('PRIVATE');
 dispose();sessionStorage.setItem(performanceStore,JSON.stringify([{version:2,navigation:{},resources:[{endpoint:'PRIVATE_URL'}],api:[],images:[],checkpoints:[],longtasks:[],secret:'PRIVATE_TOKEN'}]));
 dispose=installWorkflowDiagnostics(window);expect(JSON.stringify(report())).not.toContain('PRIVATE');
});

it('classifies actual route shapes while removing identifiers, signed URLs and arbitrary queries',()=>{
 expect(classifyResource('/api/me/inventory/PRIVATE','http://localhost:5173')).toBe('/api/me/inventory/:id');
 expect(classifyResource('https://PRIVATE.supabase.co/storage/v1/object/sign/PRIVATE?token=PRIVATE','http://localhost:5173')).toBe('storage:object');
 expect(classifyResource('/api/evidence/gallery/PRIVATE/files','http://localhost:5173')).toBe('/api/evidence/gallery/:id/files');
 expect(workflowFromHash('#gallery?medication=PRIVATE')).toBe('photos');expect(workflowFromHash('#caregivers')).toBe('contacts');
});

it('records a JSON processing failure without exporting malformed response content',async()=>{
 window.medithreadWorkflows!.start();vi.mocked(fetch).mockResolvedValue(new Response('PRIVATE_NOT_JSON',{status:200}));
 await expect(api.startDemo()).rejects.toThrow();
 const failures=window.medithreadWorkflows!.failures();
 expect(JSON.stringify(failures)).toContain('JSON_FAILURE');expect(JSON.stringify(failures)).not.toContain('PRIVATE');
});

it('waits for an existing image load before decoding and exports no source or alt text',async()=>{
 vi.useFakeTimers();document.body.innerHTML='<main id="main-content" data-load-state="ready"><img class="gallery-thumbnail" loading="lazy" src="blob:http://localhost:5173/PRIVATE_IMAGE" alt="PRIVATE_MEDICATION"></main>';
 const img=document.querySelector('img')!;Object.defineProperty(img,'complete',{value:false});
 const decode=vi.fn().mockResolvedValue(undefined);Object.defineProperty(img,'decode',{value:decode});
 window.medithreadWorkflows!.start();await vi.advanceTimersByTimeAsync(50);
 expect(decode).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();
 img.dispatchEvent(new Event('load'));await vi.advanceTimersByTimeAsync(100);
 expect(decode).toHaveBeenCalledOnce();const summary=window.medithreadWorkflows!.summary();
 expect(JSON.stringify(summary)).toContain('decode_after_load_ms');expect(JSON.stringify(summary)).not.toContain('PRIVATE');
});
