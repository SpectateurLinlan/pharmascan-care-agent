/** Actual Chrome/real components; MOCK Auth/HTTP/speech, no cloud/provider calls. */
import {test,expect} from '@playwright/test';
test('account, preview consent, inline review and pinned conversation work at patient sizes',async({page})=>{
 test.setTimeout(90000);page.setDefaultTimeout(8000);const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
 let preferences={display_name:'Guest',preferred_language:'en',speech_locale:'en-SG',text_size:'standard',text_scale_percent:100,voice_enabled:true,tts_autoplay:false,conversation_history_enabled:false,reminder_lead_minutes:0,reminders_enabled:true,timezone:'Asia/Singapore'};
 let reads=0,saves=0,authSessionCalls=0,authedApiCalls=0,photoChatMessages=0;
 const demoToken='DEMO.synthetic-session-token';
 const demoUser={id:'d00d0000-0000-4000-8000-000000000001',aud:'authenticated',role:'authenticated',email:null,phone:'',app_metadata:{provider:'anonymous',providers:['anonymous']},user_metadata:{demo_only:true},is_anonymous:true,created_at:'2026-10-16T00:00:00.000Z'};
 await page.addInitScript(()=>{
  const events=new EventTarget();
  Object.defineProperty(window,'SpeechSynthesisUtterance',{value:class {onend=null;onerror=null;constructor(text:string){}}});
  Object.defineProperty(window,'speechSynthesis',{value:{
   getVoices:()=>[{lang:'en-SG',localService:true}],cancel:()=>undefined,speak:()=>undefined,
   addEventListener:events.addEventListener.bind(events),removeEventListener:events.removeEventListener.bind(events),
  }});
 });
 await page.route(url=>new URL(url).pathname.includes('/auth/v1/'),async route=>{
  const request=route.request(),path=new URL(request.url()).pathname,headers=request.headers();
  if(path.endsWith('/signup')&&request.method()==='POST'){
   expect(request.postDataJSON().data).toEqual({demo_only:true});authSessionCalls++;
   await route.fulfill({json:{access_token:demoToken,token_type:'bearer',expires_in:3600,refresh_token:'DEMO.synthetic-refresh-token',user:demoUser}});return;
  }
  if(path.endsWith('/user')&&request.method()==='GET'){
   expect(headers.authorization).toBe(`Bearer ${demoToken}`);
   await route.fulfill({json:demoUser});return;
  }
  if(path.endsWith('/user')&&request.method()==='PUT'){
   expect(headers.authorization).toBe(`Bearer ${demoToken}`);
   const user={...demoUser,email:request.postDataJSON().email};
   await route.fulfill({json:user});return;
  }
  await route.fulfill({status:404,json:{message:'Unexpected synthetic Auth request'}});
 });
 const candidate={product:{name:'DEMO Metformin',strength:'500 mg',source_lines:['DEMO label']},review_status:'extracted',can_activate_regimen:false,regimen_evidence:{directions:{value:'Take one tablet at 20:00',line:'DEMO label'},dose_amount:1,frequency:'daily',administration_times:['20:00'],duration:null}};
 const task={id:'DEMO-task',medication_id:'DEMO-med',version:1,status:'pending_information',product:{name:'DEMO Metformin',strength:'500 mg',dose_form:'tablet',formulation:null,brand:null,ingredients:[],category:'unknown',verification:'source_supplied'},source_ids:['DEMO-source'],missing:['schedule'],conflicts:[],possible_duplicate_ids:[],draft_regimen_id:null,suggested_regimen:null};
 await page.route(url=>new URL(url).pathname.startsWith('/api/'),async route=>{
  const request=route.request(),path=new URL(request.url()).pathname;let body:unknown=[];
  if(request.headers().authorization!==`Bearer ${demoToken}`)throw new Error(`Missing synthetic patient session for ${path}`);
  authedApiCalls++;
  if(path.endsWith('/preferences')){if(route.request().method()==='PUT')preferences={...preferences,...route.request().postDataJSON()};body=preferences;}
  else if(path.endsWith('/check-input'))body={image_type:'printed',checked:true,abstained:true,suggested_workflow:'source_review',message:'SIMULATED'};
  else if(path.endsWith('/preview')){reads++;body={source_document_id:'DEMO-preview',source_kind:'pharmacy_label',provider:'SIMULATED',extraction_model:'SIMULATED',candidates:[candidate],review_required:true,note:'SIMULATED'};}
  else if(path.endsWith('/sources')&&route.request().method()==='POST'){saves++;body=task;}
  else if(path.endsWith('/sources'))body=[];
  else if(path.endsWith('/usage'))body={llm_user_turns:0,model_requests:0,limit:20,usage_date:'2026-10-16',next_reset_at:'2026-10-17T00:00:00+08:00'};
  else if(path.endsWith('/recent-turns'))body=[];
  else if(path.endsWith('/history'))body={entries:[],next_before:null};
  else if(path.endsWith('/messages')){if(String(request.postDataJSON()?.text??'').includes('Patient attached a medication photo.'))photoChatMessages++;body={message:'This is a SIMULATED sourced response. '.repeat(25),intent:'clarification',session_id:'DEMO-session',session_state:'idle',requires_confirmation:false,tool_traces:[],mode:'gemini'};}
  await route.fulfill({json:body});
 });
 await page.goto('/e2e/patient-feedback.html');console.log('Fixture loaded');
 await expect(page.locator('.identity-entry')).toContainText('Guest');
 await expect(page.getByRole('button',{name:'Login or register'})).toBeVisible();
 for(const width of [390,430,768,1280]){await page.setViewportSize({width,height:900});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);}
 console.log('Me responsive checks passed');await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'Fixture Login'}).click();await page.getByLabel('Email',{exact:true}).fill('DEMO@example.test');await page.getByRole('button',{name:'Email code / Magic Link'}).click();await expect(page.getByRole('status')).toContainText('Check your email');await page.getByRole('button',{name:'Dismiss'}).click();
 console.log('Opening source flow');await page.getByRole('button',{name:'Fixture Read'}).click();
 await page.getByLabel('Take or choose a photo').setInputFiles({name:'DEMO.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6Fo8AAAAASUVORK5CYII=','base64')});
 await expect(page.getByRole('button',{name:'Read photo',exact:true})).toBeDisabled();await page.locator('.image-consent input').check();await page.getByRole('button',{name:'Read photo',exact:true}).click();await expect(page.getByRole('heading',{name:'Read from your photo'})).toBeVisible();expect(reads).toBe(1);expect(saves).toBe(0);
 await page.getByRole('button',{name:'Save source and set up plan'}).click();await expect(page.getByLabel('Dose time 1')).toBeVisible();expect(saves).toBe(1);await page.getByRole('button',{name:'Add another time'}).click();await expect(page.getByLabel('Dose time 2')).toBeVisible();
 await page.getByRole('button',{name:'Fixture Me'}).click();await page.getByRole('button',{name:'Fixture Read'}).click();await expect(page.getByLabel('Take or choose a photo')).toHaveValue('');await expect(page.locator('.image-consent input')).toBeChecked();
 console.log('Preview/save and revisit passed');await page.getByRole('button',{name:'Fixture Assistant'}).click();const dialog=page.getByRole('dialog',{name:'Medication assistant'});await expect(dialog).toBeVisible();await expect(dialog.getByLabel('Save new conversations')).toBeVisible();
 const input=dialog.getByLabel('Review your message before sending');await input.fill('DEMO medication question');await dialog.getByRole('button',{name:'Send',exact:true}).click();await expect(dialog.locator('.turn')).toHaveCount(1);
 await dialog.getByLabel('Choose a photo').setInputFiles({name:'DEMO-chat.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6Fo8AAAAASUVORK5CYII=','base64')});
 await expect(dialog.getByLabel('Photo attachment')).toBeVisible();await expect(dialog.getByRole('button',{name:'Send',exact:true})).toBeEnabled();
 await dialog.getByRole('button',{name:'Send',exact:true}).click();await expect(dialog.locator('.turn')).toHaveCount(2);await expect(dialog.locator('.chat-photo-note')).toContainText('DEMO-chat.png');expect(reads).toBe(2);expect(photoChatMessages).toBe(1);
 const playButtons=dialog.getByRole('button',{name:'Play response',exact:true});await expect(playButtons).toHaveCount(2);expect((await playButtons.nth(1).boundingBox())!.width).toBeLessThanOrEqual(50);
 await playButtons.nth(1).click();
 await expect(dialog.getByRole('button',{name:'Stop audio',exact:true})).toHaveAttribute('aria-pressed','true');
 await dialog.getByRole('button',{name:'Stop audio',exact:true}).click();
 await expect(playButtons.nth(1)).toHaveAttribute('aria-pressed','false');
 const composer=await dialog.locator('.composer-row').boundingBox(),panel=await dialog.boundingBox();expect(composer&&panel&&composer.x>=panel.x&&composer.x+composer.width<=panel.x+panel.width+1).toBe(true);
 await expect(dialog.getByRole('button',{name:'Send',exact:true})).toBeInViewport();const beforeY=(await dialog.locator('.composer-row').boundingBox())!.y;await dialog.locator('.conversation-scroll').evaluate(el=>{el.scrollTop=el.scrollHeight;});expect((await dialog.locator('.composer-row').boundingBox())!.y).toBeCloseTo(beforeY,0);await page.screenshot({path:'../outputs/patient-feedback-chat390.png'});await page.setViewportSize({width:390,height:480});await expect(dialog.getByRole('button',{name:'Send',exact:true})).toBeInViewport();await page.setViewportSize({width:390,height:844});await dialog.getByRole('button',{name:'Close conversation'}).click();
 await page.getByRole('button',{name:'Fixture Me'}).click();await page.getByRole('button',{name:'中文',exact:true}).click();await page.getByRole('button',{name:'150%',exact:true}).click();await page.setViewportSize({width:430,height:900});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:'../outputs/patient-feedback-me-zh150.png'});
 expect(authSessionCalls).toBe(1);expect(authedApiCalls).toBeGreaterThan(0);expect(photoChatMessages).toBe(1);expect(errors).toEqual([]);
});
