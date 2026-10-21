/** Real App and browser layout; synthetic authenticated HTTP only, no live writes. */
import {test,expect,type Page} from '@playwright/test';
import type {MedicationSummary} from '../src/api/client';
async function mockPatientApp(page:Page,historyEnabled=true){
 const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
 const token='DEMO.synthetic-session-token',owner='d00d0000-0000-4000-8000-000000000001';
 const user={id:owner,aud:'authenticated',role:'authenticated',email:null,phone:'',app_metadata:{provider:'anonymous',providers:['anonymous']},user_metadata:{demo_only:true},is_anonymous:true,created_at:'2026-10-16T00:00:00Z'};
 await page.addInitScript(({owner})=>{localStorage.setItem(`pharmascan.quick-start.v4:${owner}`,JSON.stringify({version:4,status:'skipped',step:0}));},{owner});
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
 await page.route(url=>new URL(url).pathname.startsWith('/api/'),async route=>{
  const request=route.request(),path=new URL(request.url()).pathname;
  expect(request.headers().authorization).toBe(`Bearer ${token}`);
  let body:unknown=[];
  if(request.method()!=='GET')writes.push(path);
  if(path==='/api/health')body={status:'ok',runtime_contract:'patient-ux-reminders-v1'};
  else if(path==='/api/demo/start')body={session_id:'DEMO-session',patient_id:owner};
  else if(path==='/api/me/preferences'){if(request.method()==='PUT')Object.assign(prefs,request.postDataJSON());body=prefs;}
  else if(path==='/api/me/medications')body={medications:patientMedications,item_count:patientMedications.length,note:'DEMO'};
  else if(path==='/api/evidence/tasks'){sourceReads++;body=[task];}
  else if(path===`/api/evidence/tasks/${task.id}`)body=task;
  else if(path.endsWith('/usage'))body={llm_user_turns:0,model_requests:0,limit:20,usage_date:'2026-10-17',next_reset_at:'2026-10-18T00:00:00+08:00'};
  else if(path.endsWith('/history'))body={entries:[],next_before:null};
  else if(path==='/api/reminders/push/config')body={available:false,public_key:null,test_available:false};
  else if(path==='/api/speech/capabilities')body={cloud_tts_allowed:false};
  await route.fulfill({json:body});
 });
 return {errors,writes,prefs,getSourceReads:()=>sourceReads,setMedications:(rows:MedicationSummary[])=>{patientMedications=rows;}};
}


test('Polish A grids preserve columns, compact navigation and visible form labels',async({page})=>{
 test.setTimeout(120000);const {prefs,errors}=await mockPatientApp(page);
 for(const language of ['en','zh'])for(const scale of [100,150]){
  prefs.preferred_language=language;prefs.text_scale_percent=scale;
  await page.goto('/e2e/patient-feedback.html?shell=1');
  for(const width of [390,430,768,1024,1280,1600,1920]){
   await page.setViewportSize({width,height:1000});
   await page.locator('[data-guide="me"]').click();
   await expect(page.locator('.me-category')).toHaveCount(3);
   await expect(page.locator('.me-category .ui-row__hint')).toHaveCount(0);
   await expect(page.locator('.me-app-info .ui-row')).toHaveCount(3);
   if(language==='en'&&scale===100&&[390,1600].includes(width))await page.screenshot({path:`../outputs/polish-a-me-${width}.png`});
   await page.locator('[data-guide="records"]').click();
   const columns=await page.locator('.records-navigation-group .ui-rows').evaluate(el=>getComputedStyle(el).gridTemplateColumns.split(' ').length);
   const mainWidth=await page.locator('.app-main').evaluate(el=>el.clientWidth);
   const rem=await page.evaluate(()=>parseFloat(getComputedStyle(document.documentElement).fontSize));
   expect(columns).toBe(mainWidth>=38*rem?2:1);
   await expect(page.locator('.records-summary-actions button')).toHaveCount(3);
   if(language==='en'&&scale===100&&[390,1600].includes(width))await page.screenshot({path:`../outputs/polish-a-records-${width}.png`});
   await page.locator('[data-guide="medicines"]').click();
   const shortcuts=page.locator('.medicine-shortcuts');
   const grid=await shortcuts.evaluate(el=>getComputedStyle(el).gridTemplateColumns.split(' ').length);
   const last=await shortcuts.locator('button').last().boundingBox(),outer=await shortcuts.boundingBox();
   if(grid===2)expect(Math.abs(last!.width-outer!.width)).toBeLessThan(2);
   expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
   if(language==='en'&&scale===100&&[390,1600].includes(width))await page.screenshot({path:`../outputs/polish-a-${width}.png`});
  }
 }
 expect(errors).toEqual([]);
});

test('health and follow-up forms expose fields without bypassing confirmation',async({page})=>{
 const {writes}=await mockPatientApp(page);await page.goto('/e2e/patient-feedback.html?shell=1');
 await page.locator('[data-guide="records"]').click();await page.getByRole('button',{name:/My health notes/}).click();
 await expect(page.getByRole('combobox',{name:'Severity (optional)',exact:true})).toBeVisible();
 expect(await page.getByLabel('Describe how you feel (required)').getAttribute('required')).not.toBeNull();
 await page.locator('[data-guide="records"]').click();await page.getByRole('button',{name:/Medication follow-ups/}).click();
 await page.getByRole('button',{name:'Add medication follow-up',exact:true}).click();
 await expect(page.getByLabel('Your note (optional)')).toBeVisible();
 for(const label of ['Follow-up title (required)','Date and time (required)'])expect(await page.getByLabel(label,{exact:true}).getAttribute('required')).not.toBeNull();
 await page.getByRole('button',{name:'Cancel',exact:true}).click();
 await expect(page.locator('#follow-up-form')).toHaveCount(0);
 expect(writes.every(path=>['/api/demo/start','/api/me/care-tasks/refresh'].includes(path))).toBe(true);
});
