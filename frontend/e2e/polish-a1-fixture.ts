/** Real App and browser layout; synthetic authenticated HTTP only, no live writes. */
import {expect,type Page} from '@playwright/test';
import type {MedicationSummary,RegimenHistoryItem,ReviewSummary,DoseHistoryEntry} from '../src/api/client';
export async function mockPatientApp(page:Page,historyEnabled=true,identity?:{token:string;owner:string}){
 const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
 const token=identity?.token??'DEMO.synthetic-session-token',owner=identity?.owner??'d00d0000-0000-4000-8000-000000000001';
 const user={id:owner,aud:'authenticated',role:'authenticated',email:null,phone:'',app_metadata:{provider:'anonymous',providers:['anonymous']},user_metadata:{demo_only:true},is_anonymous:true,created_at:'2026-10-16T00:00:00Z'};
 await page.addInitScript(({owner})=>{localStorage.setItem(`pharmascan.quick-start.v2:${owner}`,JSON.stringify({version:2,status:'skipped',step:0}));},{owner});
 await page.route(url=>new URL(url).pathname.includes('/auth/v1/'),async route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/signup')){await route.fulfill({json:{access_token:token,token_type:'bearer',expires_in:3600,refresh_token:'DEMO.refresh',user}});return;}
  if(path.endsWith('/user')){expect(route.request().headers().authorization).toBe(`Bearer ${token}`);await route.fulfill({json:user});return;}
  throw new Error(`Unexpected synthetic Auth request: ${path}`);
 });
 const task={id:'DEMO-source-only',medication_id:'DEMO-med',version:1,status:'pending_information',product:{name:'DEMO source medicine',strength:'5 mg',dose_form:'tablet',formulation:null,brand:null,ingredients:[],category:'unknown',verification:'source_supplied'},source_ids:['DEMO-source'],missing:['schedule'],conflicts:[],possible_duplicate_ids:[],draft_regimen_id:null,suggested_regimen:null};
 let sourceReads=0;const writes:string[]=[];
 const prefs={display_name:'Guest',preferred_language:'en',speech_locale:'en-SG',text_size:'standard',text_scale_percent:100,voice_enabled:false,tts_autoplay:false,conversation_history_enabled:historyEnabled,reminder_lead_minutes:0,reminders_enabled:false,timezone:'Asia/Singapore'};
 let patientMedications:MedicationSummary[]=[];
 let plans:RegimenHistoryItem[]=[],events:DoseHistoryEntry[]=[];
 let report:ReviewSummary={period:'week',window_start:'2026-10-10T00:00:00Z',window_end:'2026-10-17T00:00:00Z',generated_at:'2026-10-17T00:00:00Z',timezone:'Asia/Singapore',medications:[],reported_taken:0,reported_not_taken:0,unsure:0,observations:[],questions:[],coverage_note:'No report is not a missed dose.'};
 const reads:string[]=[];
 await page.route(url=>new URL(url).pathname.startsWith('/api/'),async route=>{
  const request=route.request(),path=new URL(request.url()).pathname;
  expect(request.headers().authorization).toBe(`Bearer ${token}`);
  let body:unknown=[];
  if(request.method()==='GET')reads.push(request.url());
  if(request.method()!=='GET')writes.push(path);
  if(path==='/api/health')body={status:'ok',runtime_contract:'patient-ux-reminders-v1'};
  else if(path==='/api/demo/start')body={session_id:'DEMO-session',patient_id:owner};
  else if(path==='/api/me/preferences'){if(request.method()==='PUT')Object.assign(prefs,request.postDataJSON());body=prefs;}
  else if(path==='/api/me/medications')body={medications:patientMedications,item_count:patientMedications.length,note:'DEMO'};
  else if(path==='/api/me/regimens')body=plans;
  else if(path==='/api/me/medication-history/catalogue')body={medications:[...new Map(plans.map(p=>[p.medication_id,{id:p.medication_id,display_name:p.display_name,product_id:null,identity_status:'unknown'}])).values()],plans:plans.map(p=>({id:p.regimen_id,medication_id:p.medication_id,supersedes_id:null,effective_from:p.effective_from,effective_to:p.effective_to,state:p.state,dose_amount:p.dose_amount,dose_unit:p.dose_unit,strength_text:null}))};
  else if(path==='/api/me/medication-history'){
   const query=new URL(request.url()).searchParams,offset=Number(query.get('cursor')??0),plan=plans.find(p=>p.regimen_id===query.get('regimen_id'))??plans[0];
   const rows=[...events].filter(e=>e.due_at!==null).sort((a,b)=>Date.parse(b.due_at!)-Date.parse(a.due_at!)).map((e,i)=>({id:`DEMO:${e.occurrence_id??i}`,medication_id:plan?.medication_id??'DEMO-med',regimen_id:plan?.regimen_id??'DEMO-plan',display_name:plan?.display_name??'DEMO medicine',sort_time:e.due_at,due_at:e.due_at,event_id:null,event_time:null,submitted_at:null,intake_status:e.intake_status,reported:e.reported,kind:'scheduled'}));
   body={entries:rows.slice(offset,offset+5),next_cursor:rows.length>offset+5?String(offset+5):null,window_start:null,window_end:'2026-10-17T12:00:00Z',as_of:'2026-10-17T12:00:00Z',scope:'stored_records_only',missing_plan_start:false};
  }
  else if(path==='/api/me/dose-history')body={entries:events,item_count:events.length,note:'demo_only'};
  else if(path==='/api/doses/due'){const id=new URL(request.url()).searchParams.get('regimen_id');const medication=patientMedications.find(row=>row.regimen_id===id)??patientMedications[0];body={occurrence_id:'DEMO-occurrence',regimen_id:id,medication_display_name:medication?.display_name??'DEMO medicine',dose_description:'1 tablet',due_at:'2026-10-17T00:00:00Z',is_prn:false,visual_status:'not_checked',ingestion_proven:false};}
  else if(path==='/api/me/review-summary')body=report;
  else if(path==='/api/evidence/tasks'){sourceReads++;body=[task];}
  else if(path===`/api/evidence/tasks/${task.id}`)body=task;
  else if(path.endsWith('/usage'))body={llm_user_turns:0,model_requests:0,limit:20,usage_date:'2026-10-17',next_reset_at:'2026-10-18T00:00:00+08:00'};
  else if(path.endsWith('/history'))body={entries:[],next_before:null};
  else if(path==='/api/reminders/push/config')body={available:false,public_key:null,test_available:false};
  else if(path==='/api/speech/capabilities')body={cloud_tts_allowed:false};
  await route.fulfill({json:body});
 });
 return {errors,writes,reads,prefs,getSourceReads:()=>sourceReads,setMedications:(rows:MedicationSummary[])=>{patientMedications=rows;},setPlans:(rows:RegimenHistoryItem[])=>{plans=rows;},setEvents:(rows:DoseHistoryEntry[])=>{events=rows;},setReport:(value:ReviewSummary)=>{report=value;}};
}
