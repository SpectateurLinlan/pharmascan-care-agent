/** Real App and browser layout; synthetic authenticated HTTP only, no live writes. */
import {test,expect} from '@playwright/test';
test('source-only count, supplement cancellation and assistant alignment stay consistent',async({page})=>{
 test.setTimeout(90000);page.setDefaultTimeout(8000);
 const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
 const token='DEMO.synthetic-session-token',owner='d00d0000-0000-4000-8000-000000000001';
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
 const prefs={display_name:'Guest',preferred_language:'en',speech_locale:'en-SG',text_size:'standard',text_scale_percent:100,voice_enabled:false,tts_autoplay:false,conversation_history_enabled:true,reminder_lead_minutes:0,reminders_enabled:false,timezone:'Asia/Singapore'};
 await page.route(url=>new URL(url).pathname.startsWith('/api/'),async route=>{
  const request=route.request(),path=new URL(request.url()).pathname;
  expect(request.headers().authorization).toBe(`Bearer ${token}`);
  let body:unknown=[];
  if(request.method()!=='GET')writes.push(path);
  if(path==='/api/health')body={status:'ok',runtime_contract:'patient-ux-reminders-v1'};
  else if(path==='/api/demo/start')body={session_id:'DEMO-session',patient_id:owner};
  else if(path==='/api/me/preferences'){if(request.method()==='PUT')Object.assign(prefs,request.postDataJSON());body=prefs;}
  else if(path==='/api/me/medications')body={medications:[],item_count:0};
  else if(path==='/api/evidence/tasks'){sourceReads++;body=[task];}
  else if(path===`/api/evidence/tasks/${task.id}`)body=task;
  else if(path.endsWith('/usage'))body={llm_user_turns:0,model_requests:0,limit:20,usage_date:'2026-10-17',next_reset_at:'2026-10-18T00:00:00+08:00'};
  else if(path.endsWith('/history'))body={entries:[],next_before:null};
  await route.fulfill({json:body});
 });
 await page.goto('/e2e/patient-feedback.html?shell=1');
 await page.locator('[data-guide="medicines"]').click();
 await expect(page.getByRole('button',{name:/Finish medication setup/})).toContainText('1 awaiting review');
 await page.getByRole('button',{name:/Finish medication setup/}).click();
 await expect(page.getByRole('button',{name:/DEMO source medicine/})).toBeVisible();
 await expect(page.getByText('No unfinished medication setup.')).toHaveCount(0);
 await page.getByRole('button',{name:/DEMO source medicine/}).click();
 await expect(page.getByRole('heading',{name:'Supplement medication information',exact:true})).toBeVisible();
 await expect(page.getByTestId('evidence-workspace').getByLabel('Dose time 1',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Cancel supplement',exact:true}).click();
 await expect(page.getByRole('button',{name:/DEMO source medicine/})).toBeVisible();
 await page.getByRole('button',{name:/DEMO source medicine/}).click();
 await expect(page.getByTestId('evidence-workspace').getByLabel('Dose time 1',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Cancel supplement',exact:true}).click();
 // The existing App refreshes follow-ups on startup; cancellation itself must
 // never write a source, regimen, activation or deletion request.
 expect(writes.every(path=>['/api/demo/start','/api/me/care-tasks/refresh'].includes(path))).toBe(true);
 for(const scale of [100,150]){
 if(scale===150){
  await page.locator('[data-guide="me"]').click();await page.getByRole('slider',{name:'Text size'}).focus();await page.keyboard.press('End');
  await expect(page.getByRole('slider')).toHaveValue('150');await page.getByRole('button',{name:'Language and speech',exact:true}).click();await page.getByRole('menuitemradio',{name:'中文'}).click();
 }
 for(const width of [390,430,1280,1600,1920]){
  await page.setViewportSize({width,height:950});await page.locator('[data-guide="me"]').click();
  const main=page.locator('.app-main'),dock=page.locator('.companion-composer .composer-row');
  await expect(dock).toBeVisible();
  await expect.poll(async()=>{const a=(await main.boundingBox())!,b=(await dock.boundingBox())!;return Math.abs(a.x-b.x)+Math.abs(a.width-b.width);}).toBeLessThan(2);
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  const logo=page.locator('.brand-mark');await expect(logo).toBeVisible();expect(await logo.evaluate((el:HTMLImageElement)=>el.complete&&el.naturalWidth>0)).toBe(true);
  await expect(logo).toHaveAttribute('src','/branding/medithread-192.png');
  await dock.getByRole('textbox').focus();
  const dialog=page.getByRole('dialog',{name:scale===100?'Medication assistant':'用药助手'});await expect(dialog).toBeVisible();
  const panel=dialog.locator('.conversation-scroll'),composer=dialog.locator('.composer-row');
  const a=(await panel.boundingBox())!,b=(await composer.boundingBox())!;
  expect(Math.abs(a.x-b.x)).toBeLessThan(2);expect(Math.abs(a.width-b.width)).toBeLessThan(2);
  await expect(dialog.locator('.composer-send')).toBeInViewport();
  if(width===1600)await page.screenshot({path:`../outputs/ux-consistency-desktop-${scale}.png`});
  await dialog.locator('.conversation-toolbar button').click();
 }
 }
 const manifest=await (await page.request.get('/manifest.webmanifest')).json();
 for(const icon of manifest.icons){const response=await page.request.get(icon.src);expect(response.status()).toBe(200);expect(response.headers()['content-type']).toContain('image/png');}
 expect((await page.request.get('/branding/medithread-32.png')).status()).toBe(200);
 expect((await page.request.get('/branding/medithread-180.png')).status()).toBe(200);
 expect(sourceReads).toBeGreaterThan(0);expect(errors).toEqual([]);
});
