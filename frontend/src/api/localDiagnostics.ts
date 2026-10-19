/** Development-only entry captures the already-loaded app client, never a second Auth client. */
import {ApiError,DiagnosticSessionUnavailable,readDiagnosticCounts} from './client';
import {diagnosticEvent,diagnosticPaths,diagnosticFailureStage,localDiagnosticOrigin,type AuthObservation,type FailureStage} from './diagnosticContract';

type CountRow={endpoint:string;status:number|null;result:string;failure_stage:FailureStage;item_count:number|null;states:Record<string,number>|null};
export type MedicationDiagnostic={result:'complete'|'partial'|'session_unavailable'|'blocked_origin';endpoints:CountRow[];observed_requests:AuthObservation[]};
type Reader=typeof readDiagnosticCounts;
const states=['active','ended','superseded','draft','pending_clarification'];
function isObject(value:unknown):value is Record<string,unknown>{return typeof value==='object'&&value!==null&&!Array.isArray(value);}

export function createMedicationDiagnostic(read:Reader,origin:()=>string,observations:()=>AuthObservation[]){
 let pending:Promise<MedicationDiagnostic>|null=null;
 async function run():Promise<MedicationDiagnostic>{
  if(!localDiagnosticOrigin(origin()))return {result:'blocked_origin',endpoints:[],observed_requests:[]};
  const endpoints:CountRow[]=[];
  let result:MedicationDiagnostic['result']='complete';
  for(const endpoint of ['/api/me/medications','/api/me/regimens'] as const){
   const row:CountRow={endpoint,status:null,result:'unavailable',failure_stage:'unknown',item_count:null,states:null};
   try{
    const response=await read(endpoint);row.status=response.status;row.failure_stage='none';
    const data:unknown=await response.json();
    if(endpoint==='/api/me/medications'&&isObject(data)&&Number.isSafeInteger(data.item_count)&&Number(data.item_count)>=0){
     row.item_count=Number(data.item_count);row.result='ok';
    }else if(endpoint==='/api/me/regimens'&&Array.isArray(data)&&data.every(item=>isObject(item)&&typeof item.state==='string')){
     row.states={};
     for(const item of data){const state=states.includes(item.state)?item.state:'unsupported_state';row.states[state]=(row.states[state]??0)+1;}
     row.result='ok';
    }else{row.result='invalid_response';result='partial';}
   }catch(error){
    result='partial';
    if(error instanceof DiagnosticSessionUnavailable){row.result='sdk_session_unavailable';result='session_unavailable';}
    else if(error instanceof ApiError){row.status=error.status;row.failure_stage=diagnosticFailureStage(error.status,error.message);row.result=error.status===401?'authentication_rejected':error.status===503?'service_unavailable':'http_error';}
    else row.result='session_or_network_unavailable';
   }
   endpoints.push(row);
   if(result==='session_unavailable')break;
  }
  return {result,endpoints,observed_requests:observations().map(row=>({...row}))};
 }
 return ()=>pending??(pending=run().finally(()=>{pending=null;}));
}

declare global {interface Window {medithreadMedicationCounts?:()=>Promise<MedicationDiagnostic>}}
export function installLocalDiagnostics(target:Window,read:Reader=readDiagnosticCounts){
 if(!localDiagnosticOrigin(target.location.origin))return ()=>undefined;
 const observed=new Map<string,AuthObservation>();
 const listener=(event:Event)=>{
  const value:unknown=(event as CustomEvent<unknown>).detail;
  if(!isObject(value)||!diagnosticPaths.includes(value.endpoint as AuthObservation['endpoint'])||!Number.isInteger(value.status)||typeof value.authorization_attached!=='boolean')return;
  const known:FailureStage[]=['none','missing_bearer','identity_rejected','identity_service_unavailable','legacy_identity_service_failure_401','data_api_auth_rejected','unknown'];
  const failure_stage=known.includes(value.failure_stage as FailureStage)?value.failure_stage as FailureStage:'unknown';
  observed.set(String(value.endpoint),{endpoint:value.endpoint as AuthObservation['endpoint'],status:Number(value.status),authorization_attached:value.authorization_attached,failure_stage});
 };
 target.addEventListener(diagnosticEvent,listener);
 const run=createMedicationDiagnostic(read,()=>target.location.origin,()=>[...observed.values()]);
 target.medithreadMedicationCounts=run;
 return ()=>{target.removeEventListener(diagnosticEvent,listener);if(target.medithreadMedicationCounts===run)delete target.medithreadMedicationCounts;};
}
