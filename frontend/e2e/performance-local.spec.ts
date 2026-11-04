import {expect,test} from '@playwright/test';
import {mkdirSync,writeFileSync} from 'node:fs';
import path from 'node:path';

// Real local FastAPI + in-memory synthetic fixture, never hosted patient data.
// Start create_review_test_app as documented in frontend/README.md; use a Vite
// server with empty Supabase Auth variables and that API as VITE_API_TARGET.
test('language renders before a slow preference response without business refetches',async({page,baseURL})=>{
 test.skip(process.env.RUN_PERFORMANCE_LOCAL!=='1','Explicit local synthetic performance run only');
 expect(baseURL).toMatch(/^http:\/\/(127\.0\.0\.1|localhost):/);
 const health=await (await page.request.get('/api/health')).json();
 expect(health.database).toBe('simulated_in_memory');
 const session=await (await page.request.post('/api/demo/start',{data:{client_id:'DEMO-release-D'}})).json();
 await page.addInitScript(owner=>{
  localStorage.setItem('pharmascan.client_id','DEMO-release-D');
  localStorage.setItem(`pharmascan.quick-start.v5:${owner}`,JSON.stringify({version:5,status:'skipped',step:0}));
 },session.patient_id);
 let releaseSchedule!:()=>void;
 const scheduleGate=new Promise<void>(resolve=>{releaseSchedule=resolve;});
 await page.route('**/api/me/today-attention*',async route=>{
  const response=await route.fetch();await scheduleGate;await route.fulfill({response});
 });
 try{
  await page.goto('/');
  await expect(page.locator('.today-unrecorded__count')).toBeVisible();
  await expect(page.getByText('Loading your reviewed schedule…')).toBeVisible();
 }finally{releaseSchedule();}
 await expect(page.locator('.medicine-current')).toBeVisible();
 await expect(page.locator('.care-summary__counts')).toBeVisible();
 const draft=page.locator('[data-guide="assistant-composer"] input:not([type="file"])').first();await draft.fill('DEMO unsent draft');
 await page.waitForTimeout(300);
 const business:string[]=[];
 page.on('request',request=>{if(/\/api\/(reminders\/alerts|doses\/due|me\/(dose-follow-ups|today-attention|care-tasks\/refresh))/.test(request.url()))business.push(new URL(request.url()).pathname);});
 let savesFinished=0;
 await page.route('**/api/me/preferences*',async route=>{
  if(route.request().method()!=='PUT'){await route.continue();return;}
  const response=await route.fetch();await new Promise(resolve=>setTimeout(resolve,800));
  await route.fulfill({response});savesFinished++;
 });
 for(let index=0;index<2;index++){
  const before=await page.locator('.greeting').textContent();
  await page.locator('.language-shortcut').click();
  await expect(page.locator('.greeting')).not.toHaveText(before??'');
  expect(savesFinished).toBe(index);
  await expect(draft).toHaveValue('DEMO unsent draft');
  await expect(page.locator('.language-shortcut')).toBeEnabled();
 }
 expect(business).toEqual([]);
});

test('assistant startup samples separate cached and fresh browser contexts',async({browser,request,baseURL})=>{
 test.skip(process.env.RUN_ASSISTANT_STARTUP!=='1','Explicit local synthetic startup measurement only');
 test.setTimeout(180000);
 expect(new URL(baseURL!).origin).toBe('http://127.0.0.1:5173');
 const health=await (await request.get('/api/health')).json();expect(health.database).toBe('simulated_in_memory');
 const session=await (await request.post('/api/demo/start',{data:{client_id:'DEMO-startup'}})).json();
 const active=await (await request.get('/api/me/medications?client_id=DEMO-startup')).json();expect(active.medications).toHaveLength(3);
 await request.put('/api/me/preferences?client_id=DEMO-startup',{data:{voice_enabled:false,tts_autoplay:false,reminders_enabled:false,preferred_language:'en'}});
 const samples:Array<{cache:string;viewport:string;backend:string;cpu:string;shell_ms:number|null;essential_ms:number|null;onboarding_blocked:boolean}>=[];
 for(const viewport of [{width:390,height:844},{width:1280,height:900}]){
  for(const cache of ['normal-cache','cold-browser'] as const){
   let shared:Awaited<ReturnType<typeof browser.newContext>>|null=null;
   async function context(){
    const value=await browser.newContext({viewport});
    await value.addInitScript(({cache,owner})=>{
     localStorage.setItem('pharmascan.client_id','DEMO-startup');
     localStorage.setItem(`pharmascan.quick-start.v5:${owner}`,JSON.stringify({version:5,status:'skipped',step:0}));
     sessionStorage.setItem('medithread.performance.v2.enabled',cache);
    },{cache,owner:session.patient_id});
    return value;
   }
   if(cache==='normal-cache'){
    shared=await context();const warmup=await shared.newPage();await warmup.goto('/');
    await warmup.waitForFunction(()=>document.querySelector('[data-today-dose-state="ready"]'),undefined,{timeout:15000});await warmup.close();
   }
   for(let index=0;index<5;index++){
    const current=shared??await context();const page=await current.newPage();
    const cdp=await current.newCDPSession(page);await cdp.send('Emulation.setCPUThrottlingRate',{rate:1});
    await page.goto('/');
    await page.waitForFunction(()=>{
     const summary=window.medithreadWorkflows?.summary() as {captures:Array<{checkpoints:Array<{kind:string}>}>}|undefined;
     return summary?.captures.at(-1)?.checkpoints.some(row=>row.kind==='today_essential_ready');
    },undefined,{timeout:15000}).catch(()=>undefined);
    const timing=await page.evaluate(()=>{
     const summary=window.medithreadWorkflows?.summary() as {captures:Array<{checkpoints:Array<{kind:string;at:number}>}>}|undefined;
     const checkpoints=summary?.captures.at(-1)?.checkpoints??[];
     return {shell_ms:checkpoints.find(row=>row.kind==='app_shell_visible')?.at??null,
      essential_ms:checkpoints.find(row=>row.kind==='today_essential_ready')?.at??null,
      onboarding_blocked:Boolean(document.querySelector('[aria-modal="true"]'))};
    });
    samples.push({cache,viewport:`${viewport.width}x${viewport.height}`,backend:'running_memory_process',cpu:'CDP_rate_1',...timing});
    await page.close();if(!shared)await current.close();
   }
   await shared?.close();
  }
 }
 const output=path.resolve('../outputs/assistant-startup');mkdirSync(output,{recursive:true});
 writeFileSync(path.join(output,'samples.json'),JSON.stringify(samples,null,2));
 expect(samples).toHaveLength(20);expect(samples.every(row=>row.shell_ms!==null&&row.essential_ms!==null&&!row.onboarding_blocked)).toBe(true);
});

test('assistant startup shell remains visible with delayed health and onboarding blocks readiness',async({page,request,baseURL})=>{
 test.skip(process.env.RUN_ASSISTANT_STARTUP!=='1','Explicit local synthetic startup measurement only');
 expect(new URL(baseURL!).origin).toBe('http://127.0.0.1:5173');
 const session=await (await request.post('/api/demo/start',{data:{client_id:'DEMO-startup'}})).json();
 await page.addInitScript(owner=>{localStorage.setItem('pharmascan.client_id','DEMO-startup');sessionStorage.setItem('medithread.performance.v2.enabled','cold-browser');localStorage.removeItem(`pharmascan.quick-start.v5:${owner}`);},session.patient_id);
 let release!:()=>void;const pending=new Promise<void>(resolve=>{release=resolve;});
 await page.route('**/api/health',async route=>{const response=await route.fetch();await pending;await route.fulfill({response});});
 let releaseSession!:()=>void;const pendingSession=new Promise<void>(resolve=>{releaseSession=resolve;});
 await page.route('**/api/demo/start',async route=>{const response=await route.fetch();await pendingSession;await route.fulfill({response});});
 try{
 try{
  await page.goto('/');
  await expect(page.getByRole('heading',{name:'Welcome to MediThread',exact:true})).toBeVisible();
  await expect(page.getByRole('navigation',{name:'Main navigation'})).toBeVisible();
  await expect(page.locator('[data-today-dose-state="ready"]')).toHaveCount(0);
 }finally{release();}
 await expect(page.locator('[aria-modal="true"]').first()).toBeVisible();
 await page.waitForFunction(()=>window.medithreadWorkflows?.enabled);
 const summary=await page.evaluate(()=>window.medithreadWorkflows!.summary()) as {captures:Array<{checkpoints:Array<{kind:string}>}>};
 expect(summary.captures.at(-1)!.checkpoints.some(row=>row.kind==='app_shell_visible')).toBe(true);
 expect(summary.captures.at(-1)!.checkpoints.some(row=>row.kind==='today_essential_ready')).toBe(false);
 }finally{releaseSession();}
});
