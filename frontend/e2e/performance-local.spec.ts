import {expect,test} from '@playwright/test';

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
