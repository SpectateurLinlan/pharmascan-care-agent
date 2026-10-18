/** Real App and browser layout; synthetic authenticated HTTP only, no live writes. */
import {test,expect,chromium,type Page} from '@playwright/test';
import type {MedicationSummary} from '../src/api/client';
async function mockPatientApp(page:Page,historyEnabled=true){
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
  else if(path==='/api/agent/conversations')body={entries:[],next_before:null};
  else if(path.endsWith('/history'))body={entries:[],next_before:null};
  else if(path==='/api/reminders/push/config')body={available:false,public_key:null,test_available:false};
  else if(path==='/api/speech/capabilities')body={cloud_tts_allowed:false};
  await route.fulfill({json:body});
 });
 return {errors,writes,prefs,getSourceReads:()=>sourceReads,setMedications:(rows:MedicationSummary[])=>{patientMedications=rows;}};
}

test('source-only count, supplement cancellation and assistant alignment stay consistent',async({page})=>{
 test.setTimeout(90000);page.setDefaultTimeout(8000);
 const {errors,writes,getSourceReads}=await mockPatientApp(page);
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
  await page.locator('[data-guide="me"]').click();await page.locator('.settings-shortcut').click();await page.locator('#text-size').focus();await page.keyboard.press('End');
  await expect(page.locator('#text-size')).toHaveValue('150');await page.locator('.language-shortcut').click();await page.locator('.language-menu__list [role=menuitemradio]').nth(1).click();
 }
 for(const width of [390,430,1280,1600,1920]){
  await page.setViewportSize({width,height:950});await page.locator('[data-guide="me"]').click();
  const assistantEntry=width>=1024?page.locator('[data-guide="assistant"]'):page.locator('.assistant-header-shortcut');
  await expect(assistantEntry).toBeVisible();await expect(page.locator('.assistant-launcher')).toHaveCount(0);
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  const logo=page.locator('.brand-mark');await expect(logo).toBeVisible();expect(await logo.evaluate((el:HTMLImageElement)=>el.complete&&el.naturalWidth>0)).toBe(true);
  await expect(logo).toHaveAttribute('src','/branding/medithread-192.png');
  await assistantEntry.click();
  const workspace=page.locator('.conversation-workspace');await expect(workspace).toBeVisible();
  const panel=workspace.locator('.conversation-scroll'),composer=workspace.locator('.composer-row');
  const a=(await panel.boundingBox())!,b=(await composer.boundingBox())!;
  expect(Math.abs(a.x-b.x)).toBeLessThan(2);expect(Math.abs(a.width-b.width)).toBeLessThan(2);
  await expect(workspace.locator('.composer-send')).toBeInViewport();
  if(width===1600)await page.screenshot({path:`../outputs/ux-consistency-desktop-${scale}.png`});
  await workspace.locator('.conversation-toolbar .conversation-actions button').last().click();
 }
 }
 const manifest=await (await page.request.get('/manifest.webmanifest')).json();
 for(const icon of manifest.icons){const response=await page.request.get(icon.src);expect(response.status()).toBe(200);expect(response.headers()['content-type']).toContain('image/png');}
 expect((await page.request.get('/branding/medithread-32.png')).status()).toBe(200);
 expect((await page.request.get('/branding/medithread-180.png')).status()).toBe(200);
 expect(getSourceReads()).toBeGreaterThan(0);expect(errors).toEqual([]);
});

test('Me categories and Records summary/actions use the intended responsive hierarchy',async({page})=>{
 const {errors}=await mockPatientApp(page);await page.goto('/e2e/patient-feedback.html?shell=1');
 await page.locator('[data-guide="me"]').click();
 await expect(page.locator('.me-category')).toHaveCount(3);await expect(page.locator('.me-app-info .ui-row')).toHaveCount(3);
 for(const width of [390,430,768,1024,1280,1600]){
  await page.setViewportSize({width,height:900});
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  const cards=await page.locator('.me-category').evaluateAll(rows=>rows.map(row=>{const box=row.getBoundingClientRect();return{x:box.x,y:box.y,width:box.width,height:box.height};}));
  expect(cards.every(card=>card.width>0&&card.height>0)).toBe(true);
  if(width>=1280)expect(new Set(cards.map(card=>Math.round(card.y))).size).toBe(1);
  else expect(new Set(cards.map(card=>Math.round(card.y))).size).toBe(3);
 }
 await page.locator('[data-guide="records"]').click();
 await expect(page.locator('.records-summary-actions button')).toHaveCount(3);
 await expect(page.locator('.records-navigation-group .ui-row')).toHaveCount(4);
 for(const width of [390,430,768,1024,1280,1600]){
  await page.setViewportSize({width,height:900});
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  const layout=await page.evaluate(()=>{
   const group=document.querySelector('.records-navigation-group')!,rows=[...group.querySelectorAll('.ui-row')],buttons=[...document.querySelectorAll('.records-summary-actions button')];
   return {wide:group.getBoundingClientRect().width>=608,rowLines:new Set(rows.map(row=>Math.round(row.getBoundingClientRect().y))).size,buttonLines:new Set(buttons.map(button=>Math.round(button.getBoundingClientRect().y))).size};
  });
  expect(layout.rowLines).toBe(layout.wide?2:4);expect(layout.buttonLines).toBe(layout.wide?1:3);
 }
 for(const [label,route] of [['This week','#summary-week'],['This month','#summary-month'],['By medication plan','#summary-course']] as const){
  const routePage=await page.context().newPage();await mockPatientApp(routePage);await routePage.goto('/e2e/patient-feedback.html?shell=1');
  await routePage.locator('[data-guide="records"]').click();await routePage.getByRole('button',{name:label,exact:true}).click();
  await expect.poll(()=>routePage.evaluate(()=>location.hash)).toBe(route);await routePage.close();
 }
 for(const [label,route] of [['My health notes','#health-notes'],['Medication difficulties','#adherence-barriers'],['Medication follow-ups','#care-tasks'],['Medication review preparation','#medication-review']] as const){
  const routePage=await page.context().newPage();await mockPatientApp(routePage);await routePage.goto('/e2e/patient-feedback.html?shell=1');
  await routePage.locator('[data-guide="records"]').click();await routePage.getByRole('button',{name:new RegExp(label)}).click();
  await expect.poll(()=>routePage.evaluate(()=>location.hash)).toBe(route);await routePage.close();
 }
 expect(errors).toEqual([]);
});

test('patient record labels preserve plan identity and remain usable across languages and text sizes',async({context})=>{
 const plans=['DEMO-old','DEMO-current','DEMO-separate-course'].map((id,index)=>({regimen_id:id,medication_id:'DEMO-med',display_name:'DEMO very long medication product name with documented strength 5 mg and extended release formulation',version_no:index+1,state:index===1?'active':'ended',effective_from:`2026-${index===2?'08':'10'}-0${index+1}T00:00:00Z`,effective_to:null,course_start_date:index===2?'2026-08-01':'2026-10-01',course_end_date:null,dose_amount:1,dose_unit:'tablet',food_instruction:null,is_prn:false,local_times:['08:00']}));
 for(const language of ['en','zh'] as const)for(const scale of [100,150]){
  const page=await context.newPage();const {prefs,errors}=await mockPatientApp(page);prefs.preferred_language=language;prefs.text_scale_percent=scale;
  const queries:string[]=[];
  await page.route(url=>new URL(url).pathname==='/api/me/regimens',route=>route.fulfill({json:plans}));
  await page.route(url=>new URL(url).pathname==='/api/me/dose-history',route=>{
   expect(route.request().headers().authorization).toBe('Bearer DEMO.synthetic-session-token');queries.push(new URL(route.request().url()).searchParams.get('regimen_id')!);
   return route.fulfill({json:{item_count:4,note:'demo_only',entries:['reported_taken','reported_not_taken','unsure',null].map((status,index)=>({occurrence_id:`DEMO-dose-${index}`,due_at:'2026-10-02T00:00:00Z',event_time:status?'2026-10-02T00:10:00Z':null,intake_status:status,visual_status:null,reported:status!==null}))}});
  });
  await page.goto('/e2e/patient-feedback.html?shell=1');await page.locator('[data-guide="records"]').click();
  const select=page.locator('#history-medication');await expect(select.locator('option')).toHaveCount(3);
  await expect(page.locator('.history li')).toHaveCount(4);
  await expect(page.locator('.history')).toContainText(language==='zh'?'这次用药还没有记录服用情况。':'This dose has no record of whether you took it yet.');
  for(const plan of plans){await select.selectOption(plan.regimen_id);await expect.poll(()=>queries.at(-1)).toBe(plan.regimen_id);}
  for(const width of [390,430,768,1024,1280,1600]){
   await page.setViewportSize({width,height:950});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
   await expect(select).toBeVisible();const box=(await select.boundingBox())!;expect(box.x).toBeGreaterThanOrEqual(0);expect(box.x+box.width).toBeLessThanOrEqual(width);
   if((width===390&&language==='zh'&&scale===150)||(width===1600&&language==='en'&&scale===100))await page.screenshot({path:`../outputs/record-semantics-${width}-${language}-${scale}.png`,fullPage:true});
  }
  await page.locator('.records-navigation-group .ui-row').first().click();
  await expect(page.locator('#health-description')).toBeVisible();await expect(page.getByLabel(language==='zh'?'程度':'Severity')).toBeVisible();
  await page.setViewportSize({width:390,height:950});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.getByRole('button',{name:language==='zh'?'记录健康感受':'Record how you feel',exact:true}).click();await expect(page.locator('#health-description')).toBeFocused();
  await page.locator('[data-guide="records"]').click();await page.locator('.records-navigation-group .ui-row').nth(2).click();
  const add=page.getByRole('button',{name:language==='zh'?'添加用药跟进':'Add medication follow-up',exact:true});await add.click();
  await expect(page.locator('#follow-up-form')).toBeVisible();await page.locator('#follow-up-form').getByRole('button',{name:language==='zh'?'取消':'Cancel',exact:true}).click();await expect(page.locator('#follow-up-form')).toHaveCount(0);
  expect(errors).toEqual([]);await page.close();
 }
});

test('photo evidence stays separate from patient bubbles and persisted history in EN and ZH',async({context})=>{
 for(const language of ['en','zh'] as const){
  const page=await context.newPage();const {prefs,errors}=await mockPatientApp(page);prefs.preferred_language=language;
  const question=language==='zh'?'请帮我核对这张药房标签。':'Please review this pharmacy label.';
  let stored='';
  await page.route(url=>new URL(url).pathname==='/api/sources/check-input',route=>route.fulfill({json:{image_type:'printed',checked:true,abstained:false,suggested_workflow:'source_review',message:'DEMO internal route'}}));
  await page.route(url=>new URL(url).pathname==='/api/sources/preview',route=>route.fulfill({json:{source_document_id:'DEMO-preview',source_kind:'pharmacy_label',provider:'SIMULATED',extraction_model:'SIMULATED',review_required:true,note:'DEMO only',candidates:[{product:{name:'DEMO source medicine',strength:'5 mg',source_lines:['DEMO_PRIVATE_OCR_MARKER']},regimen_evidence:{directions:{value:'DEMO only',line:'DEMO_PRIVATE_OCR_MARKER'},dose_amount:null,frequency:null,administration_times:null,duration:null},review_status:'extracted',can_activate_regimen:false}]}}));
  await page.route(url=>new URL(url).pathname==='/api/agent/messages',async route=>{
   expect(route.request().headers().authorization).toBe('Bearer DEMO.synthetic-session-token');
   const payload=route.request().postDataJSON();expect(payload.text).toBe(question);
   expect(payload.photo_context.products[0].printed_directions).toBe('DEMO_PRIVATE_OCR_MARKER');
   stored=question+'\n'+(language==='zh'?'已发送照片':'Photo attached');
   await route.fulfill({json:{message:'DEMO source review response',intent:'clarification',mode:'gemini',session_id:'DEMO-session',session_state:'idle',requires_confirmation:false,tool_traces:[],history_saved:true}});
  });
  await page.route(url=>new URL(url).pathname==='/api/agent/history',route=>route.fulfill({json:{entries:stored?[{id:'DEMO-history-photo',user_text:stored,assistant_text:'DEMO source review response',created_at:'2026-10-17T08:00:00Z'}]:[],next_before:null}}));
  await page.goto('/e2e/patient-feedback.html?shell=1');
  await page.getByRole('textbox').fill(question);
  await page.getByLabel(language==='zh'?'选择照片':'Choose a photo',{exact:true}).setInputFiles({name:'DEMO-photo.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6Fo8AAAAASUVORK5CYII=','base64')});
  await page.locator('.photo-consent input').check();await page.locator('.composer-send').click();
  await expect(page.locator('.turn .user-message')).toContainText(question);await expect(page.locator('.turn .user-message')).not.toContainText('DEMO_PRIVATE_OCR_MARKER');
  await page.locator('.assistant-header-shortcut').click();
  const historyToggle=page.locator('.conversation-brand button');if(await historyToggle.getAttribute('aria-expanded')==='false')await historyToggle.click();
  await expect(page.locator('.history-entry')).toContainText(question);await expect(page.locator('.history-entry')).not.toContainText('DEMO_PRIVATE_OCR_MARKER');
  await page.locator('.history-entry').click();await expect(page.locator('.selected-history .user-message')).toHaveText(stored);
  expect(errors).toEqual([]);await page.close();
 }
});

test('settings ownership, persisted reminder preferences and viewport launcher geometry',async({page})=>{
 test.setTimeout(90000);page.setDefaultTimeout(8000);
 const {errors,prefs}=await mockPatientApp(page);
 await page.route(url=>new URL(url).pathname==='/api/reminders/plan',async route=>{
  expect(route.request().headers().authorization).toBe('Bearer DEMO.synthetic-session-token');
  await route.fulfill({json:Array.from({length:5},(_,index)=>({occurrence_id:`DEMO-${index}`,regimen_id:'DEMO-regimen',rule_id:'DEMO-rule',medication_name:`DEMO scheduled ${index}`,due_at:'2099-10-17T08:00:00Z',remind_at:'2099-10-17T08:00:00Z',slot:'08:00'}))});
 });
 await page.goto('/e2e/patient-feedback.html?shell=1');
 await page.locator('[data-guide="me"]').click();
 await expect(page.locator('#text-size')).toHaveCount(0);
 await page.locator('#main-content').getByRole('button',{name:'Language and speech'}).click();
 await expect(page.getByRole('heading',{name:'Language and speech'})).toBeVisible();
 await expect(page.locator('#settings-language')).toBeVisible();await expect(page.locator('#text-size')).toHaveCount(0);
 await page.locator('.back-button').click();await page.locator('#main-content').getByRole('button',{name:/Text size/}).click();
 await expect(page.getByRole('heading',{level:1,name:'Text size'})).toBeVisible();
 await expect(page.locator('#text-size')).toBeVisible();await expect(page.locator('#settings-language')).toHaveCount(0);
 await page.locator('.back-button').click();await page.locator('#main-content').getByRole('button',{name:/Assistant and conversation saving/}).click();
 await expect(page.getByRole('heading',{name:'Assistant and conversation saving'})).toBeVisible();
 await expect(page.getByLabel('Save new conversations')).toBeVisible();
 await page.locator('.back-button').click();await page.locator('#main-content').getByRole('button',{name:/Privacy controls/}).click();
 await expect(page.getByRole('heading',{name:'Privacy controls'})).toBeVisible();
 await expect(page.getByRole('button',{name:'Save new conversations'})).toHaveCount(0);
 await page.locator('.back-button').click();
 await page.getByRole('button',{name:/Medication reminders/}).click();
 await expect(page.getByRole('heading',{name:'Medication reminders and notifications'})).toBeVisible();
 await expect(page.getByLabel('Enable medication reminders')).not.toBeChecked();
 await page.getByLabel('Enable medication reminders').check();
 await page.getByLabel('Reminder lead minutes').fill('15');
 await expect.poll(()=>prefs.reminder_lead_minutes).toBe(15);
 await expect(page.locator('#upcoming-reminder-list li')).toHaveCount(3);
 await page.getByRole('button',{name:'View all upcoming reminders'}).click();
 await expect(page.locator('#upcoming-reminder-list li')).toHaveCount(5);
 await page.locator('.settings-shortcut').click();
 await expect(page.getByRole('heading',{name:'Usage preferences',exact:true})).toBeVisible();
 await expect(page.getByLabel('Enable medication reminders')).toHaveCount(0);
 await expect(page.locator('#upcoming-reminder-list')).toHaveCount(0);
 await page.locator('.back-button').click();
 await expect(page.getByLabel('Enable medication reminders')).toBeChecked();
 await expect(page.getByLabel('Reminder lead minutes')).toHaveValue('15');
 await page.reload();
 await expect(page.getByLabel('Enable medication reminders')).toBeChecked();
 await expect(page.getByLabel('Reminder lead minutes')).toHaveValue('15');
 for(const language of ['en','zh'])for(const scale of [100,150]){
 await page.locator('.settings-shortcut').click();
 await page.locator('#text-size').focus();await page.keyboard.press(scale===150?'End':'Home');
 await expect.poll(()=>prefs.text_scale_percent).toBe(scale);
 await page.locator('.language-shortcut').click();
 await page.locator('.language-menu__list [role=menuitemradio]').nth(language==='en'?0:1).click();
 await page.setViewportSize({width:1024,height:950});await page.locator('[data-guide=me]').click();await page.locator('.notification-shortcut').click();
 await page.locator('.notification-shortcut').click();
 for(const width of [390,430,768,1024,1280,1600,1920]){
  await page.setViewportSize({width,height:950});
  const body=(await page.locator('.app-main').boundingBox())!,back=(await page.locator('.back-button').boundingBox())!;
  const headerStyle=await page.locator('.app-header').evaluate(el=>({left:getComputedStyle(el).left,width:getComputedStyle(el).width,padding:getComputedStyle(el).paddingInlineStart,rail:getComputedStyle(document.documentElement).getPropertyValue('--rail-width'),max:getComputedStyle(document.documentElement).getPropertyValue('--content-max'),font:getComputedStyle(document.documentElement).fontSize}));
  expect(Math.abs(body.x-back.x),JSON.stringify({width,body,back,headerStyle})).toBeLessThan(2);
  const assistantEntry=width>=1024?page.locator('[data-guide="assistant"]'):page.locator('.assistant-header-shortcut');
  await expect(assistantEntry).toBeVisible();await assistantEntry.click();
  const workspace=page.locator('.conversation-workspace');await expect(workspace).toBeVisible();
  const shell=(await workspace.boundingBox())!,composer=(await workspace.locator('.composer-row').boundingBox())!;
  expect(composer.x).toBeGreaterThanOrEqual(shell.x);expect(composer.x+composer.width).toBeLessThanOrEqual(shell.x+shell.width+1);
  await expect(workspace.locator('.composer-send')).toBeInViewport();
  await workspace.locator('.conversation-toolbar .conversation-actions button').last().click();
  await expect.poll(()=>page.evaluate(()=>location.hash)).toBe('#reminder-settings');
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  if([390,1600].includes(width)&&scale===100&&language==='en')await page.screenshot({path:`../outputs/settings-cleanup-${width}.png`});
 }
 }
 await page.setViewportSize({width:768,height:430});
 await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await expect(page.locator('.assistant-header-shortcut')).toBeVisible();
 // Existing critical forms remain free of duplicate floating launchers.
 await page.locator('[data-guide="medicines"]').click();
 await page.locator('.app-main').locator('.ui-screen--medicines .primary').click();
 await expect(page.locator('.assistant-launcher')).toHaveCount(0);
 expect(errors).toEqual([]);
});

test('real Chrome browser zoom keeps the Assistant workspace and shared header usable',async({},testInfo)=>{
 test.setTimeout(45000);
 // A disposable persistent profile enables Chrome's own browser zoom API.
 // This is browser zoom, not CSS zoom, DPR emulation or pinch scaling.
 const context=await chromium.launchPersistentContext('',{...testInfo.project.use.launchOptions,headless:true,viewport:null,args:['--window-size=1280,950']});
 try{
  const page=await context.newPage();await mockPatientApp(page);
  await page.goto('http://127.0.0.1:5174/e2e/patient-feedback.html?shell=1');
  await page.locator('[data-guide="me"]').click();
  const baseline=await page.evaluate(()=>({width:innerWidth,dpr:devicePixelRatio}));
  const settings=await context.newPage();await settings.goto('chrome://settings/appearance');
  for(const zoom of [1,1.25,1.5]){
   await settings.evaluate(value=>{const chrome=(window as unknown as {chrome:{settingsPrivate:{setDefaultZoom:(zoom:number)=>void}}}).chrome;chrome.settingsPrivate.setDefaultZoom(value);},zoom);
   await expect.poll(()=>page.evaluate(()=>devicePixelRatio)).toBeCloseTo(baseline.dpr*zoom,2);
   const width=await page.evaluate(()=>innerWidth);expect(Math.abs(width-baseline.width/zoom)).toBeLessThan(2);
   const main=(await page.locator('.app-main').boundingBox())!,brand=(await page.locator('.brand').boundingBox())!;
   expect(Math.abs(main.x-brand.x)).toBeLessThan(2);
   await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
   const assistant=page.locator('[data-guide="assistant"]');await assistant.focus();await page.keyboard.press('Enter');
   const workspace=page.locator('.conversation-workspace');await expect(workspace.locator('.composer-send')).toBeInViewport();
   await workspace.locator('.conversation-toolbar .conversation-actions button').last().click();
  }
 }finally{await context.close();}
});

test('reminder dialog stays capped on desktop and scrolls its own content on short screens',async({page})=>{
 test.setTimeout(45000);page.setDefaultTimeout(8000);
 const {errors,prefs}=await mockPatientApp(page);
 prefs.text_scale_percent=150;prefs.preferred_language='zh';
 let alertEnabled=false,alertReads=0;const snoozes:Array<{occurrence_id:string;minutes:number}>=[];
 await page.route(url=>new URL(url).pathname==='/api/reminders/alerts',async route=>{
  alertReads++;
  await route.fulfill({json:alertEnabled?[{key:'DEMO-reminder-key',occurrence_id:'DEMO-occurrence',regimen_id:'DEMO-regimen',medication_name:'DEMO Metformin',dose_amount:500,dose_unit:'mg',food_instruction:'after food',due_at:'2026-10-17T08:00:00Z',remind_at:'2026-10-17T08:00:00Z'}]:[]});
 });
 await page.route(url=>new URL(url).pathname==='/api/reminders',async route=>{
  if(route.request().method()!=='POST'){await route.fallback();return;}
  const body=route.request().postDataJSON() as {occurrence_id:string;minutes:number};snoozes.push(body);
  await route.fulfill({json:{occurrence_id:body.occurrence_id,patient_id:'DEMO-patient',remind_at:'2026-10-17T08:30:00Z',demo_only:true}});
 });
 await page.goto('/e2e/patient-feedback.html?shell=1');
 await expect.poll(()=>alertReads,{timeout:10000}).toBeGreaterThan(0);
 await page.waitForTimeout(50);alertEnabled=true;
 await page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));
 const dialog=page.locator('.reminder-dialog');await expect(dialog).toBeVisible();
 await expect(dialog).toContainText('DEMO Metformin');
 for(const width of [390,430,768,1024,1280,1600,1920]){
  await page.setViewportSize({width,height:950});
  const box=(await dialog.boundingBox())!;
  expect(box.width).toBeLessThanOrEqual(600);
  expect(box.x).toBeGreaterThanOrEqual(0);expect(box.x+box.width).toBeLessThanOrEqual(width);
  if(width<700)expect(box.width).toBeGreaterThan(width-64);
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 }
 await page.setViewportSize({width:390,height:480});
 const shortBox=(await dialog.boundingBox())!;
 expect(shortBox.height).toBeLessThan(480);
 expect(await dialog.evaluate(el=>el.scrollHeight>el.clientHeight)).toBe(true);
 await page.locator('.reminder-dialog .actions button:nth-child(2)').click();
 await expect(dialog).toHaveCount(0);
 expect(snoozes).toEqual([{occurrence_id:'DEMO-occurrence',minutes:30}]);
 expect(errors).toEqual([]);
});

test('Today tasks reuse one conversation and root pages adapt to landscape and enlarged text',async({page})=>{
 test.setTimeout(90000);page.setDefaultTimeout(8000);
 const {errors}=await mockPatientApp(page);let sends=0;
 await page.route(url=>new URL(url).pathname==='/api/agent/messages',async route=>{
  expect(route.request().headers().authorization).toBe('Bearer DEMO.synthetic-session-token');
  expect(route.request().postDataJSON().text).toContain('current medications');sends++;
  await route.fulfill({json:{message:'SIMULATED patient record response',intent:'clarification',session_id:'DEMO-session',session_state:'idle',requires_confirmation:false,tool_traces:[],mode:'rules'}});
 });
 await page.goto('/e2e/patient-feedback.html?shell=1');
 const entry=page.locator('.today-assistant');await expect(entry.getByRole('heading',{name:'MediThread Assistant'})).toBeVisible();
 await expect(entry.getByRole('button',{name:/Understand medicines|Review my records|Prepare for a visit|View today’s medication/})).toHaveCount(4);
 await entry.getByRole('button',{name:'View today’s medication',exact:true}).click();await expect(page.locator('#today-medication')).toBeInViewport();
 const tasks=[['Understand medicines','current medications'],['Review my records','past 7 days'],['Prepare for a visit','pharmacist or doctor']];
 for(const [label,prompt] of tasks){
  await entry.getByRole('button',{name:label,exact:true}).click();
  await expect(entry.getByRole('textbox')).toHaveValue(new RegExp(prompt));
  expect(sends).toBe(0);await entry.getByRole('textbox').fill('');
 }
 await entry.getByRole('button',{name:'Understand medicines',exact:true}).click();
 await entry.getByRole('button',{name:'Send',exact:true}).click();
 await expect(entry.locator('.turn')).toHaveCount(1);expect(sends).toBe(1);
 await entry.locator('.today-assistant__expand').click();const workspace=page.locator('.conversation-workspace');await expect(workspace.locator('.turn')).toHaveCount(1);
 await workspace.getByRole('textbox').fill('DEMO unsent question');await workspace.getByRole('button',{name:'Back'}).click();
 await page.locator('[data-guide="medicines"]').click();await page.locator('[data-guide="today"]').click();
 await expect(entry.locator('details.recent-chat')).not.toHaveAttribute('open','');
 await expect(entry.getByRole('textbox')).toHaveValue('DEMO unsent question');
 await expect(entry.getByRole('button',{name:'Understand medicines',exact:true})).toBeDisabled();
 await entry.getByRole('textbox').focus();await expect(workspace).toHaveCount(0);await entry.locator('.today-assistant__expand').click();await expect(workspace.locator('.turn')).toHaveCount(1);
 await workspace.getByRole('textbox').fill('');await workspace.getByRole('button',{name:'Back'}).click();
 for(const language of ['en','zh']){
 for(const scale of [100,150]){
  await page.locator('[data-guide="me"]').click();await page.locator('.settings-shortcut').click();await page.locator('#text-size').focus();await page.keyboard.press(scale===150?'End':'Home');
  await expect(page.locator('#text-size')).toHaveValue(String(scale));await page.locator('.language-shortcut').click();await page.locator('.language-menu__list [role=menuitemradio]').nth(language==='en'?0:1).click();
  for(const width of [390,430,768,1024,1280,1600,1920]){
   await page.setViewportSize({width,height:950});
   for(const tab of ['today','medicines','records','me']){
    await page.locator(`[data-guide="${tab}"]`).click();
    await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await expect(page.locator('.composer-row:visible')).toHaveCount(tab==='today'?1:0);await expect(page.locator('.assistant-launcher')).toHaveCount(0);
    await expect(width>=1024?page.locator('[data-guide="assistant"]'):page.locator('.assistant-header-shortcut')).toBeVisible();
    if(width>=1024){const main=(await page.locator('.app-main').boundingBox())!,brand=(await page.locator('.brand').boundingBox())!;expect(Math.abs(main.x-brand.x)).toBeLessThan(2);if(width>=1600&&scale===100)expect(main.width).toBeLessThanOrEqual(1280);}
    if(tab==='today'){
     const grid=page.locator('.today-panels');await expect(grid).toBeVisible();
     expect((await entry.boundingBox())!.width).toBeCloseTo((await page.locator('.app-main').boundingBox())!.width,0);
     expect(await entry.locator('.composer-row').evaluate(el=>getComputedStyle(el).position)).toBe('relative');
    }
    if(tab==='today'){
     await expect(entry).toBeVisible();
     await expect(page.locator('.today-panels > *')).toHaveCount(2);
    }
    if(width===1600&&scale===100&&language==='en')await page.screenshot({path:`../outputs/agentic-landscape-${tab}.png`});
   }
  }
 }
 }
 await page.setViewportSize({width:768,height:430});await page.locator('[data-guide="today"]').click();
 await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await entry.getByRole('textbox').focus();await expect(page.getByRole('dialog')).toHaveCount(0);await entry.locator('.today-assistant__expand').click();await expect(page.locator('.conversation-workspace .composer-send')).toBeInViewport();
 expect(sends).toBe(1);expect(errors).toEqual([]);
});

test('Medicines shortcuts reflow and every current plan remains visible for empty and long lists',async({page})=>{
 test.setTimeout(120000);page.setDefaultTimeout(8000);
 const {errors,prefs,setMedications}=await mockPatientApp(page);
 const widths=[390,430,768,1024,1280,1600,1920];let previousHeights=new Map<number,number>();
 for(const language of ['en','zh']){
  prefs.preferred_language=language;
  for(const count of [0,1,2,5,10]){
   setMedications(Array.from({length:count},(_,index):MedicationSummary=>({medication_id:`DEMO-med-${index}`,regimen_id:`DEMO-regimen-${index}`,display_name:`DEMO Medicine ${index+1}`,is_prn:false,version_no:1,identity_status:'unverified',source_backed:true,dose_amount:500,dose_unit:'mg',frequency_rule:{kind:'daily',local_times:['08:00'],days_of_week:[]},food_instruction:null,course_start_date:'2026-10-14',course_end_date:'2099-10-20'})));
   await page.goto('/e2e/patient-feedback.html?shell=1');await page.locator('[data-guide="medicines"]').click();
   const screen=page.locator('.ui-screen--medicines'),list=page.locator('.medicines-courses'),shortcuts=page.locator('.medicine-shortcuts');
   await expect(screen.locator('.medicines-courses h2').first()).toBeVisible();
   await expect(page.locator('.medicines-courses .ui-row')).toHaveCount(count);
   if(count===0)await expect(page.locator('.medicines-courses .ui-empty')).toBeVisible();
   else for(let index=1;index<=count;index++)await expect(page.getByRole('button',{name:new RegExp(`DEMO Medicine ${index}(?!\\d)`)})).toBeVisible();
   await expect(shortcuts.getByRole('button')).toHaveCount(3);
   for(const width of widths){
    await page.setViewportSize({width,height:900});
    const [mainBox,screenBox,listBox,shortcutBox]=await Promise.all([page.locator('.app-main').boundingBox(),screen.boundingBox(),list.boundingBox(),shortcuts.boundingBox()]);
    expect(screenBox).not.toBeNull();expect(listBox).not.toBeNull();expect(shortcutBox).not.toBeNull();
    expect(Math.abs(listBox!.width-screenBox!.width)).toBeLessThan(2);expect(Math.abs(shortcutBox!.width-screenBox!.width)).toBeLessThan(2);
    const layout=await shortcuts.evaluate(el=>({columns:getComputedStyle(el).gridTemplateColumns.split(' ').length,scrollWidth:el.scrollWidth,clientWidth:el.clientWidth}));
    const rem=await page.evaluate(()=>parseFloat(getComputedStyle(document.documentElement).fontSize));
    expect(layout.columns).toBe(mainBox!.width>=64*rem?3:mainBox!.width>=38*rem?2:1);
    expect(layout.scrollWidth).toBeLessThanOrEqual(layout.clientWidth);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    const natural=await list.evaluate(el=>({height:el.getBoundingClientRect().height,scrollHeight:el.scrollHeight,clientHeight:el.clientHeight,maxHeight:getComputedStyle(el).maxHeight,overflow:getComputedStyle(el).overflowY}));
    expect(natural.scrollHeight).toBeLessThanOrEqual(natural.clientHeight+1);expect(natural.maxHeight).toBe('none');expect(natural.overflow).not.toBe('auto');
    if(width>=900){const header=await screen.locator('.ui-screen__head').boundingBox(),action=await screen.locator('.ui-actions').boundingBox();expect(Math.abs(header!.y-action!.y)).toBeLessThan(2);}
    if(width===1280){const key=language==='en'?count:count+100;previousHeights.set(key,natural.height);}
   }
  }
 }
 for(const languageOffset of [0,100])expect(previousHeights.get(languageOffset+10)!).toBeGreaterThan(previousHeights.get(languageOffset+5)!);
 expect(errors).toEqual([]);
});

test('inline send, shared avatar, opt-in saved exchanges and explicit clear keep separate semantics',async({page})=>{
 test.setTimeout(90000);page.setDefaultTimeout(8000);
 const {errors,prefs}=await mockPatientApp(page,false);let sends=0,clears=0,newSessions=0;
 let saved:Array<{id:string;user_text:string;assistant_text:string;created_at:string}>=[];
 await page.route(url=>new URL(url).pathname==='/api/agent/messages',async route=>{
  expect(route.request().headers().authorization).toBe('Bearer DEMO.synthetic-session-token');sends++;
  const body=route.request().postDataJSON(),answer=`SIMULATED answer ${sends}`;
  if(prefs.conversation_history_enabled)saved.push({id:`DEMO-saved-${sends}`,user_text:body.text,assistant_text:answer,created_at:new Date().toISOString()});
  await route.fulfill({json:{message:answer,intent:'clarification',session_id:body.session_id??'DEMO-session',session_state:'idle',requires_confirmation:false,tool_traces:[],mode:'rules'}});
 });
 await page.route(url=>new URL(url).pathname==='/api/agent/history',async route=>{
  expect(route.request().headers().authorization).toBe('Bearer DEMO.synthetic-session-token');
  if(route.request().method()==='DELETE'){expect(route.request().postDataJSON()).toEqual({confirmed:true});clears++;saved=[];await route.fulfill({json:{cleared:true}});return;}
  await route.fulfill({json:{entries:saved,next_before:null}});
 });
 await page.goto('/e2e/patient-feedback.html?shell=1');
 const entry=page.locator('.today-assistant');await expect(entry).toBeVisible();
 const welcome=(await page.locator('.welcome').boundingBox())!,hero=(await entry.boundingBox())!;expect(welcome.y+welcome.height).toBeLessThanOrEqual(hero.y);
 await entry.getByRole('textbox').click();await entry.getByRole('textbox').fill('DEMO unsaved exchange');await expect(page.getByRole('dialog')).toHaveCount(0);
 await expect(page.locator('.assistant-launcher')).toHaveCount(0);expect(sends).toBe(0);
 await entry.getByRole('button',{name:'Send',exact:true}).click();await expect(entry.getByText('SIMULATED answer 1')).toBeVisible();
 await expect(entry.getByLabel('Save new conversations')).toHaveCount(0);expect(saved).toHaveLength(0);
 await entry.locator('.today-assistant__expand').click();const workspace=page.locator('.conversation-workspace');
 await workspace.getByRole('textbox').fill('DEMO keep this draft');await workspace.getByRole('button',{name:'Conversation history'}).click();
 await expect(workspace.getByText('Saving is off. No saved messages are available.')).toBeVisible();
 await workspace.getByRole('button',{name:'Back to current conversation'}).click();await expect(workspace.getByRole('textbox')).toHaveValue('DEMO keep this draft');
 await workspace.locator('.conversation-toolbar .conversation-actions button').last().click();await page.locator('[data-guide="records"]').click();await page.locator('.assistant-header-shortcut').click();
 await expect(workspace.getByRole('textbox')).toHaveValue('DEMO keep this draft');await expect(workspace.getByText('SIMULATED answer 1')).toBeVisible();
 await workspace.locator('.conversation-toolbar .conversation-actions button').last().click();await page.locator('[data-guide="me"]').click();await page.getByRole('button',{name:/Assistant and conversation saving/}).click();
 const save=page.getByRole('checkbox',{name:/Save new conversations/});await expect(save).not.toBeChecked();const preferenceSaved=page.waitForResponse(response=>response.request().method()==='PUT'&&new URL(response.url()).pathname==='/api/me/preferences');await save.click();expect((await preferenceSaved).status()).toBe(200);await expect(save).toBeChecked();
 await page.locator('[data-guide="today"]').click();await entry.getByRole('textbox').fill('DEMO saved exchange');await entry.getByRole('button',{name:'Send',exact:true}).click();await expect(entry.getByText('SIMULATED answer 2')).toBeVisible();expect(saved).toHaveLength(1);
 await entry.locator('.today-assistant__expand').click();await workspace.getByRole('textbox').fill('DEMO current draft');await workspace.getByRole('button',{name:'Conversation history'}).click();
 await expect(workspace.locator('.history-date-group h3')).toHaveText('Today');await workspace.locator('.history-entry').click();
 await expect(workspace.locator('.history-message')).toContainText('SIMULATED answer 2');expect(sends).toBe(2);
 await workspace.getByRole('button',{name:'Back to current conversation'}).click();await expect(workspace.getByRole('textbox')).toHaveValue('DEMO current draft');
 await page.route(url=>new URL(url).pathname==='/api/demo/start',async route=>{expect(route.request().postDataJSON().session_id).toBeNull();newSessions++;await route.fulfill({json:{session_id:'DEMO-fresh-session',patient_id:'d00d0000-0000-4000-8000-000000000001',demo_only:true,note:'SIMULATED',seeded_medication_count:0}});});
 await workspace.getByRole('button',{name:'New conversation'}).click();await expect(workspace.locator('.turn')).toHaveCount(0);await expect(workspace.getByRole('textbox')).toHaveValue('DEMO current draft');expect(newSessions).toBe(1);expect(saved).toHaveLength(1);
 await workspace.locator('.conversation-toolbar .conversation-actions button').last().click();await page.locator('[data-guide="me"]').click();await page.getByRole('button',{name:/Assistant and conversation saving/}).click();
 await page.getByRole('button',{name:'Clear saved conversations',exact:true}).click();expect(clears).toBe(0);await page.getByRole('button',{name:'Cancel',exact:true}).click();expect(saved).toHaveLength(1);
 await page.getByRole('button',{name:'Clear saved conversations',exact:true}).click();await page.getByRole('button',{name:'Confirm clear',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);expect(clears).toBe(1);expect(saved).toHaveLength(0);
 await page.locator('[data-guide="today"]').click();await expect(entry.getByRole('textbox')).toHaveValue('DEMO current draft');await expect(page.locator('.assistant-launcher')).toHaveCount(0);
 expect(errors).toEqual([]);
});
