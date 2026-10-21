/** Closed diagnostic vocabulary. Never retain actual IDs, URLs, queries or text. */
export const performanceEvent='medithread:workflow-performance';
export const performanceFlag='medithread.performance.v2.enabled';
export const performanceStore='medithread.performance.v2.runs';
export const workflows=['today','medicines','me','contacts','medication-detail','photos','records','history','care-tasks','other'] as const;
export const errors=['AUTH_REQUIRED','VALIDATION_ERROR','PROVIDER_UNAVAILABLE','NOT_FOUND','REGIMEN_OVERLAP','POLICY_BLOCKED','INTERNAL_ERROR','SDK_UNAVAILABLE','NETWORK_FAILURE','JSON_FAILURE','other'] as const;
const fixed=[
 '/api/health','/api/demo/start','/api/me/medications','/api/me/regimens','/api/me/preferences',
 '/api/me/today-attention','/api/me/dose-follow-ups','/api/me/caregivers','/api/me/care-tasks',
 '/api/me/care-tasks/refresh','/api/me/medication-history','/api/me/medication-history/catalogue',
 '/api/me/review-summary','/api/me/medication-review','/api/me/health-observations','/api/me/adherence-barriers',
 '/api/reminders','/api/reminders/alerts','/api/reminders/plan','/api/agent/usage','/api/evidence/tasks',
 '/api/evidence/gallery','/api/medications/dose-display','/api/agent/history','/api/agent/conversations',
] as const;
const patterns:Array<[RegExp,string]>=[
 [/^\/api\/me\/inventory\/[^/]+$/,'/api/me/inventory/:id'],
 [/^\/api\/evidence\/gallery\/[^/]+\/files$/,'/api/evidence/gallery/:id/files'],
 [/^\/api\/evidence\/images\/[^/]+$/,'/api/evidence/images/:id'],
 [/^\/api\/evidence\/library-files\/[^/]+$/,'/api/evidence/library-files/:id'],
 [/^\/api\/evidence\/tasks\/[^/]+\/sources$/,'/api/evidence/tasks/:id/sources'],
 [/^\/api\/evidence\/tasks\/[^/]+$/,'/api/evidence/tasks/:id'],
 [/^\/api\/agent\/sessions\/[^/]+\/recent-turns$/,'/api/agent/sessions/:id/recent-turns'],
 [/^\/api\/agent\/conversations\/[^/]+$/,'/api/agent/conversations/:id'],
 [/^\/api\/doses\/[^/]+\/history$/,'/api/doses/:id/history'],
 [/^\/api\/me\/doses\/[^/]+\/late-reports$/,'/api/me/doses/:id/late-reports'],
 [/^\/api\/doses\/[^/]+$/,'/api/doses/:id'],
 [/^\/api\/medications\/[^/]+$/,'/api/medications/:id'],
];
export const endpointLabels=[...fixed,...patterns.map(([,label])=>label),'/api/doses/due','/api/other','auth:user','auth:token','auth:signup','storage:object','private-image:blob','asset:image','asset:script','asset:style','asset:font','asset:other','external:other'];
export function classifyResource(input:string,origin:string):string{
 try{
  const url=new URL(input,origin),path=url.pathname;
  if(url.protocol==='blob:')return 'private-image:blob';
  if(path.startsWith('/storage/v1/'))return 'storage:object';
  if(path==='/auth/v1/user')return 'auth:user';
  if(path==='/auth/v1/token')return 'auth:token';
  if(path==='/auth/v1/signup')return 'auth:signup';
  if(url.origin!==origin)return 'external:other';
  if(fixed.some(value=>value===path))return path;
  if(path==='/api/doses/due')return path;
  for(const [pattern,label] of patterns)if(pattern.test(path))return label;
  if(path.startsWith('/api/'))return '/api/other';
  if(/\.(png|jpe?g|webp|avif|gif|svg)$/i.test(path))return 'asset:image';
  if(/\.(tsx?|jsx?)$/.test(path)||path.startsWith('/@'))return 'asset:script';
  if(/\.css$/.test(path))return 'asset:style';
  if(/\.(woff2?|ttf|otf)$/.test(path))return 'asset:font';
  return 'asset:other';
 }catch{return 'external:other';}
}
export function workflowFromHash(hash:string):typeof workflows[number]{
 const route=hash.replace(/^#/,'').split('?')[0];
 if(!route||route==='today')return 'today';
 if(route==='caregivers')return 'contacts';
 if(route==='gallery'||route==='label')return 'photos';
 if(route==='medicine-detail'||route==='medication-inventory'||route==='medicine-history')return 'medication-detail';
 if(route==='medication-records')return 'history';
 return workflows.includes(route as typeof workflows[number])?route as typeof workflows[number]:'other';
}
export type ApiTiming={kind:'start'|'response'|'body';id:number;endpoint:string;method:string;start:number;end?:number;auth_ms?:number;fetch_ms?:number;status?:number|null;error?:string;dependency_status?:number;dependency_code?:string;shared?:boolean;cache_policy?:string};
let sequence=0;
export function beginApiTiming(path:string,method='GET'):ApiTiming|null{
 if(!import.meta.env.DEV||typeof window==='undefined'||!window.medithreadWorkflows?.enabled)return null;
 const timing:ApiTiming={kind:'start',id:++sequence,endpoint:classifyResource(path,location.origin),method:['GET','POST','PUT','PATCH','DELETE'].includes(method.toUpperCase())?method.toUpperCase():'other',start:performance.now()};
 emitApiTiming(timing);return timing;
}
export function emitApiTiming(timing:ApiTiming|null){
 if(timing&&import.meta.env.DEV&&typeof window!=='undefined'&&window.medithreadWorkflows?.enabled)window.dispatchEvent(new CustomEvent(performanceEvent,{detail:timing}));
}
export async function readJsonWithTiming<T>(response:Response,path:string):Promise<T>{
 const enabled=import.meta.env.DEV&&typeof window!=='undefined'&&window.medithreadWorkflows?.enabled;
 const start=enabled?performance.now():0;let error:string|undefined;
 try{return await response.json() as T;}catch(caught){error='JSON_FAILURE';throw caught;}
 finally{if(enabled)emitApiTiming({kind:'body',id:++sequence,endpoint:classifyResource(path,location.origin),method:'other',start,end:performance.now(),...(error?{error}:{})});}
}
