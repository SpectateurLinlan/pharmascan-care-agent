/** Opt-in, local-only, reload-persistent timing. Never fetches or reads response bodies. */
import {classifyResource,endpointLabels,errors,performanceEvent,performanceFlag,performanceStore,workflowFromHash,workflows,type ApiTiming} from './workflowPerformanceContract';

type Row=Record<string,unknown>;
type Capture={version:2;sequence:number;cache:string;navigation:Row;resources:Row[];api:Row[];checkpoints:Row[];longtasks:Row[];images:Row[]};
type Controller={enabled:boolean;start:(cache?:'normal-cache'|'cache-disabled'|'cold-browser')=>void;summary:()=>unknown;failures:()=>unknown;stop:()=>unknown;clear:()=>void};
declare global{interface Window{medithreadWorkflows?:Controller}}
const stages=['auth','compose','business','data','storage','cleanup','app'];
const criticalDataStages=new Set(['patient_profiles','patient_medications','regimen_versions','source_documents','dose_rules','dose_occurrences','effective_dose_events','dose_events'].flatMap(table=>['read','write'].flatMap(method=>['one','batch','regimen','medication','source','window','list'].map(shape=>`db_${table}_${method}_${shape}`))));
const codes=['PGRST100','PGRST102','PGRST116','PGRST200','PGRST202','PGRST204','PGRST205','23503','23505','22023','22P02','42P01','42703','42883','P7501','P7502','P7504','unknown'];
const vocabulary=new Set([...endpointLabels,...workflows,...errors,...codes,'normal-cache','cache-disabled','cold-browser','navigate','reload','back_forward','prerender','GET','POST','PUT','PATCH','DELETE','other','start','response','body','loading','ready','error','unavailable','unknown','route_enter','content_candidate','today_essential_ready','bootstrap_error','language_interaction','language_visible','image_error','no-store','no-cache','private','public','unspecified']);
const keys=new Set(['version','sequence','cache','navigation','resources','api','checkpoints','longtasks','images','endpoint','workflow','resource','id','shared','method','kind','start','end','duration','auth_ms','fetch_ms','status','error','dependency_status','dependency_code','transfer','encoded','decoded','ttfb','pre_request','download','server_timing','data_calls','storage_calls','cache_policy',...stages,...criticalDataStages,'calls','max_ms','bytes','type','dom_interactive','dom_loaded','load_end','response_start','response_end','fetch_start','worker_start','boot_ms','state','at','visit','load_ms','decode_after_load_ms','post_decode_frames_ms','failed','unobservable','observed_ms','storage_available','dropped','candidate_ms','language_ms']);
function sanitize(value:unknown,depth=0):unknown{
 if(depth>8)return null;
 if(value===null||typeof value==='boolean')return value;
 if(typeof value==='number')return Number.isFinite(value)&&value>=0&&value<1e12?Math.round(value*100)/100:null;
 if(typeof value==='string')return vocabulary.has(value)?value:null;
 if(Array.isArray(value))return value.slice(-300).map(item=>sanitize(item,depth+1));
 if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).filter(([key])=>keys.has(key)).map(([key,item])=>[key,sanitize(item,depth+1)]));
 return null;
}

export function installWorkflowDiagnostics(target:Window){
 if(!['http://localhost:5173','http://127.0.0.1:5173'].includes(target.location.origin)||target.medithreadWorkflows)return ()=>undefined;
 let captures:Capture[]=[],storageAvailable=true,dropped=0,flush:number|undefined;
 try{const saved:unknown=JSON.parse(target.sessionStorage.getItem(performanceStore)??'[]');if(Array.isArray(saved))captures=(sanitize(saved) as Capture[]).filter(run=>run?.version===2&&Array.isArray(run.api)&&Array.isArray(run.resources)&&Array.isArray(run.images)&&Array.isArray(run.checkpoints)&&Array.isArray(run.longtasks)&&!!run.navigation).slice(-5);}catch{storageAvailable=false;}
 let run:Capture|null=null,cleanup:(()=>void)|null=null;
 const persist=()=>{if(!storageAvailable)return;try{target.sessionStorage.setItem(performanceStore,JSON.stringify(sanitize(captures)));}catch{storageAvailable=false;}};
 const queueSave=()=>{if(flush===undefined)flush=target.setTimeout(()=>{flush=undefined;persist();},500);};
 const push=(rows:Row[],row:Row)=>{rows.push(sanitize(row) as Row);if(rows.length>300){rows.shift();dropped++;}queueSave();};
 const navigation=()=>{
  const entry=target.performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming|undefined;
  if(!run)return;
  run.navigation=sanitize(entry?{type:entry.type,start:entry.startTime,duration:entry.duration,response_start:entry.responseStart,response_end:entry.responseEnd,fetch_start:entry.fetchStart,worker_start:entry.workerStart,dom_interactive:entry.domInteractive,dom_loaded:entry.domContentLoadedEventEnd,load_end:entry.loadEventEnd,transfer:entry.transferSize,encoded:entry.encodedBodySize,decoded:entry.decodedBodySize}:{} ) as Row;
 };
 function activate(cache:string){
  if(cleanup)return;
  controller.enabled=true;
  run={version:2,sequence:Math.max(0,...captures.map(item=>Number(item.sequence)||0))+1,cache,navigation:{boot_ms:target.performance.now()},resources:[],api:[],checkpoints:[],longtasks:[],images:[]};
  captures.push(run);captures=captures.slice(-6);const capture=run;
  const observers:PerformanceObserver[]=[];const pending=new Map<number,string>(),identities=new Map<string,number>();
  let essentialReady=false;
  let visit=0,route=workflowFromHash(target.location.hash),entered=target.performance.now(),candidate=false,frame=0,previousHash:string|null=null;
  let languageClick:number|null=null,previousLanguage:string|null=null;
  const identity=(raw:string)=>{try{const url=new URL(raw,target.location.origin);if(url.protocol==='data:')return 0;if(url.pathname.startsWith('/storage/v1/'))url.search='';const key=url.href;let id=identities.get(key);if(id===undefined){id=identities.size+1;if(identities.size<1500)identities.set(key,id);}return id;}catch{return 0;}};
  const observe=(type:string,callback:(entries:PerformanceEntry[])=>void)=>{
   try{const observer=new PerformanceObserver(list=>callback(list.getEntries()));observer.observe({type,buffered:true});observers.push(observer);}catch{/* Unsupported browser metric remains absent. */}
  };
  observe('resource',entries=>{
   for(const raw of entries){const entry=raw as PerformanceResourceTiming;const server:Row={};
    for(const stage of entry.serverTiming??[]){if(stages.includes(stage.name))server[stage.name]=stage.duration;if(['data_calls','storage_calls'].includes(stage.name)&&/^\d{1,6}$/.test(stage.description))server[stage.name]=Number(stage.description);
     if(criticalDataStages.has(stage.name)){const values=/^calls=(\d{1,6});max_ms=(\d+(?:\.\d+)?);bytes=(\d{1,12})$/.exec(stage.description);if(values)server[stage.name]={duration:stage.duration,calls:Number(values[1]),max_ms:Number(values[2]),bytes:Number(values[3])};}
    }
    const status=(entry as PerformanceResourceTiming&{responseStatus?:number}).responseStatus;
    push(capture.resources,{endpoint:classifyResource(entry.name,target.location.origin),resource:identity(entry.name),workflow:route,start:entry.startTime,end:entry.responseEnd,duration:entry.duration,status:status&&status>0?status:null,transfer:entry.transferSize,encoded:entry.encodedBodySize,decoded:entry.decodedBodySize,ttfb:entry.requestStart>0?entry.responseStart-entry.requestStart:null,pre_request:entry.requestStart>0?entry.requestStart-entry.startTime:null,download:entry.responseStart>0?entry.responseEnd-entry.responseStart:null,unobservable:entry.responseStart===0,server_timing:server});
   }
  });
  observe('longtask',entries=>{for(const entry of entries)push(capture.longtasks,{start:entry.startTime,duration:entry.duration,workflow:route});});
  const api=(event:Event)=>{
   const detail=(event as CustomEvent<ApiTiming>).detail;if(!detail||!Number.isFinite(detail.id)||!endpointLabels.includes(detail.endpoint)||!['start','response','body'].includes(detail.kind))return;
   push(capture.api,{...detail,workflow:route});
   if(detail.kind==='start')pending.set(detail.id,detail.endpoint);else if(detail.kind==='response')pending.delete(detail.id);
   schedule();
  };
  const selectors:Record<string,string>={today:'.today-attention .medicine-current, .today-schedule-empty, .today-confirmation-card .today-unrecorded__count',medicines:'.medicine-shortcuts',me:'.ui-screen--me',contacts:'.care-contacts-screen','medication-detail':'.medication-detail-section',photos:'.personal-gallery',records:'.records-medication-history-card',history:'.record-history','care-tasks':'.care-task-page, .care-calendar, .care-list-view'};
  const relevant:Record<string,string[]>={today:['/api/demo/start','/api/me/medications','/api/me/regimens','/api/me/preferences','/api/me/today-attention','/api/me/dose-follow-ups'],contacts:['/api/me/caregivers'],'medication-detail':['/api/me/medication-history','/api/evidence/gallery','/api/me/inventory/:id'],photos:['/api/evidence/gallery','/api/evidence/gallery/:id/files'],history:['/api/me/medication-history','/api/me/medication-history/catalogue'],'care-tasks':['/api/me/care-tasks','/api/me/care-tasks/refresh']};
  const privateImages=new WeakSet<HTMLImageElement>();const listeners:Array<()=>void>=[];
  function scanImages(){
   for(const img of target.document.querySelectorAll<HTMLImageElement>('img.gallery-thumbnail')){
    if(privateImages.has(img))continue;privateImages.add(img);
    const started=target.performance.now();let finished=false;
    const loaded=()=>{if(finished||!controller.enabled)return;finished=true;const at=target.performance.now();const row:Row={workflow:route,start:started,load_ms:at-started,resource:identity(img.currentSrc||img.src),failed:false};
     // Only decode already-loaded images: never force a lazy image to download.
     const decoded=typeof img.decode==='function'?img.decode():Promise.resolve();
     void decoded.then(()=>{if(!controller.enabled)return;row.decode_after_load_ms=target.performance.now()-at;const frameStart=target.performance.now();target.requestAnimationFrame(()=>target.requestAnimationFrame(()=>{if(controller.enabled){row.post_decode_frames_ms=target.performance.now()-frameStart;push(capture.images,row);}}));}).catch(()=>{if(controller.enabled)push(capture.images,{...row,failed:true});});
    };
    const failed=()=>{if(!finished&&controller.enabled){finished=true;push(capture.images,{workflow:route,start:started,load_ms:target.performance.now()-started,failed:true});}};
    img.addEventListener('load',loaded,{once:true});img.addEventListener('error',failed,{once:true});listeners.push(()=>{img.removeEventListener('load',loaded);img.removeEventListener('error',failed);});
    if(img.complete&&img.naturalWidth>0)loaded();
   }
  }
  function inspect(){
   frame=0;scanImages();const main=target.document.querySelector('#main-content');const state=main?.getAttribute('data-load-state');
   if(state==='error'&&!candidate){push(capture.checkpoints,{workflow:route,kind:'bootstrap_error',at:target.performance.now(),visit});candidate=true;}
   const busy=[...pending.values()].some(endpoint=>(relevant[route]??[]).includes(endpoint));
   const failed=capture.api.some(row=>row.workflow===route&&row.kind==='response'&&Number(row.start)>=entered&&(row.error||Number(row.status)>=400));
   const selector=selectors[route];
   if(!candidate&&state==='ready'&&!busy&&!failed&&selector&&target.document.querySelector(selector)){
    push(capture.checkpoints,{workflow:route,kind:'content_candidate',at:target.performance.now(),candidate_ms:target.performance.now()-entered,visit});candidate=true;
   }
   if(!essentialReady&&route==='today'&&state==='ready'&&!target.document.querySelector('[aria-modal="true"]')){
    const schedule=target.document.querySelector('.today-attention');
    const doseCards=schedule?.querySelectorAll(':scope > .today-overview [data-today-dose-state]');
    const scheduled=schedule?.getAttribute('data-today-schedule-state')==='ready'
     &&schedule.getAttribute('data-today-needs-dose')==='true'
     &&Boolean(doseCards?.length)&&[...(doseCards??[])].every(card=>card.getAttribute('data-today-dose-state')==='ready');
    const empty=Boolean(target.document.querySelector('#today-medication [data-today-empty-state="ready"]'));
    if(scheduled||empty){essentialReady=true;push(capture.checkpoints,{workflow:route,kind:'today_essential_ready',at:target.performance.now(),visit});}
   }
   const language=target.document.querySelector('.language-shortcut')?.getAttribute('data-ui-language')??null;
   if(languageClick!==null&&language!==null&&previousLanguage!==null&&language!==previousLanguage){push(capture.checkpoints,{workflow:route,kind:'language_visible',at:target.performance.now(),language_ms:target.performance.now()-languageClick});languageClick=null;}
  }
  function schedule(){if(!frame)frame=target.requestAnimationFrame(inspect);}
  const change=()=>{if(previousHash===target.location.hash)return;previousHash=target.location.hash;route=workflowFromHash(target.location.hash);entered=target.performance.now();visit++;candidate=false;essentialReady=false;push(capture.checkpoints,{workflow:route,kind:'route_enter',at:entered,visit});schedule();};
  const click=(event:Event)=>{if(event.target instanceof Element&&event.target.closest('.language-shortcut')){languageClick=target.performance.now();previousLanguage=target.document.querySelector('.language-shortcut')?.getAttribute('data-ui-language')??null;push(capture.checkpoints,{workflow:route,kind:'language_interaction',at:languageClick});}};
  const mutations=new MutationObserver(schedule);mutations.observe(target.document.documentElement,{subtree:true,childList:true,attributes:true,attributeFilter:['data-load-state','data-ui-language','data-today-schedule-state','data-today-needs-dose','data-today-dose-state','data-today-empty-state','src','hidden']});
  const hide=()=>{navigation();persist();};
  target.addEventListener(performanceEvent,api);target.addEventListener('hashchange',change);target.addEventListener('popstate',change);target.addEventListener('pagehide',hide);target.document.addEventListener('click',click,true);
  change();navigation();queueSave();
  cleanup=()=>{controller.enabled=false;observers.forEach(observer=>observer.disconnect());mutations.disconnect();listeners.forEach(remove=>remove());target.cancelAnimationFrame(frame);target.removeEventListener(performanceEvent,api);target.removeEventListener('hashchange',change);target.removeEventListener('popstate',change);target.removeEventListener('pagehide',hide);target.document.removeEventListener('click',click,true);navigation();persist();cleanup=null;};
 }
 const controller:Controller={enabled:false,
  start(cache='normal-cache'){if(!['normal-cache','cache-disabled','cold-browser'].includes(cache))throw new Error('Use a supported cache label.');try{target.sessionStorage.setItem(performanceFlag,cache);}catch{storageAvailable=false;}activate(cache);},
  summary(){navigation();return {version:2,storage_available:storageAvailable,dropped,captures:sanitize(captures)};},
  failures(){return sanitize(captures.slice(-2).map(capture=>{const api=capture.api.filter(row=>['response','body'].includes(String(row.kind))&&(row.error||Number(row.status)>=400));const endpoints=new Set(api.map(row=>row.endpoint));return {version:2,sequence:capture.sequence,api,resources:capture.resources.filter(row=>endpoints.has(row.endpoint)),checkpoints:capture.checkpoints.filter(row=>row.kind==='bootstrap_error')};}));},
  stop(){try{target.sessionStorage.removeItem(performanceFlag);}catch{/* No unrelated storage is touched. */}cleanup?.();return controller.summary();},
  clear(){cleanup?.();captures=[];run=null;try{target.sessionStorage.removeItem(performanceStore);target.sessionStorage.removeItem(performanceFlag);}catch{storageAvailable=false;}},
 };
 target.medithreadWorkflows=controller;
 try{const flag=target.sessionStorage.getItem(performanceFlag);if(flag&&['normal-cache','cache-disabled','cold-browser'].includes(flag))activate(flag);}catch{storageAvailable=false;}
 return ()=>{cleanup?.();if(flush!==undefined)target.clearTimeout(flush);delete target.medithreadWorkflows;};
}
