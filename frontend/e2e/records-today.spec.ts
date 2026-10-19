/** Actual App -> local FastAPI with synthetic owned records, no production. */
import {expect,test} from '@playwright/test';
import {mockPatientApp} from './polish-a1-fixture';

test('real history filters work and the timed attention list ages into unrecorded without an intake write',async({page,baseURL})=>{
 test.setTimeout(60000);expect(new URL(baseURL!).port).toBe('5193');
 const {errors}=await mockPatientApp(page,true,{token:'DEMO.correctness02-synthetic-token',owner:'de020000-0000-4000-8000-000000000001'});
 await page.route(url=>new URL(url).pathname.startsWith('/api/'),route=>route.continue());
 await page.clock.install({time:new Date('2026-10-18T01:00:00Z')});
 await page.goto('/');await expect(page.getByText('2 medication plans',{exact:true})).toBeVisible();
 await expect(page.locator('.today-prn summary')).toContainText('As-needed medicines');
 const advance=await page.request.post('/api/demo-only/advance-clock');expect(advance.ok()).toBe(true);expect((await advance.json() as {dose_event_count:number}).dose_event_count).toBe(3);await page.clock.fastForward(15001);
 await expect(page.getByText('2 medication plans',{exact:true})).toHaveCount(0);await expect(page.locator('.today-unrecorded summary')).toContainText('1');
 await page.locator('.today-unrecorded summary').click();await expect(page.locator('.today-unrecorded')).toContainText('Unrecorded does not mean missed.');
 await page.setViewportSize({width:390,height:844});await page.locator('.today-unrecorded').scrollIntoViewIfNeeded();await page.screenshot({path:'../outputs/today-attention-mobile.png'});
 await page.locator('[data-guide="records"]').click();await expect(page.getByRole('heading',{name:'My medication records'})).toBeVisible();
 await expect(page.getByRole('heading',{name:'Current medicines'})).toHaveCount(0);await expect(page.getByText(/still shown above/)).toHaveCount(0);
 await expect(page.getByText(/Displayed records/)).toBeVisible();await page.getByLabel('Search medicines',{exact:true}).fill('Amlodipine');
 await page.getByLabel('Medicine',{exact:true}).selectOption({label:'DEMO Amlodipine'});await expect(page.getByText(/Displayed records/)).toBeVisible();
 expect(await page.getByLabel('Medication plan',{exact:true}).locator('option').count()).toBe(4);
 for(const width of [390,1280]){await page.setViewportSize({width,height:900});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  const rects=await page.locator('.record-history__filters > .field').evaluateAll(elements=>elements.map(element=>{const r=element.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom};}));
  for(let i=0;i<rects.length;i++)for(let j=i+1;j<rects.length;j++){const a=rects[i]!,b=rects[j]!;expect(a.right<=b.left||b.right<=a.left||a.bottom<=b.top||b.bottom<=a.top).toBe(true);}
  await page.locator('.record-history').scrollIntoViewIfNeeded();await page.screenshot({path:`../outputs/records-fixed-${width}.png`});}
 await page.request.put('/api/me/preferences',{headers:{Authorization:'Bearer DEMO.correctness02-synthetic-token'},data:{preferred_language:'zh',text_scale_percent:150}});await page.reload();
 await expect(page.getByRole('heading',{name:'我的用药记录'})).toBeVisible();await expect(page.getByText(/已显示记录/)).toBeVisible();await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.locator('.record-history__filters').scrollIntoViewIfNeeded();await page.screenshot({path:'../outputs/records-fixed-zh150.png'});
 expect(errors).toEqual([]);
});

test('captures final records filter alignment on the actual route',async({page,baseURL})=>{
 test.setTimeout(45000);expect(new URL(baseURL!).port).toBe('5193');
 await mockPatientApp(page,true,{token:'DEMO.correctness02-synthetic-token',owner:'de020000-0000-4000-8000-000000000001'});
 await page.route(url=>new URL(url).pathname.startsWith('/api/'),route=>route.continue());
 const headers={Authorization:'Bearer DEMO.correctness02-synthetic-token'};
 await page.request.put('/api/me/preferences',{headers,data:{preferred_language:'en',text_scale_percent:100}});
 await page.goto('/');await page.locator('[data-guide="records"]').click();await expect(page.getByText(/Displayed records/)).toBeVisible();
 const position=async()=>{await page.locator('.record-history__filters').evaluate(element=>{const header=document.querySelector('header')?.getBoundingClientRect().bottom??80;window.scrollTo({top:window.scrollY+element.getBoundingClientRect().top-header-16,behavior:'instant'});});};
 for(const width of [1280,390]){await page.setViewportSize({width,height:900});await position();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:`../outputs/records-fixed-${width}.png`});}
 await page.request.put('/api/me/preferences',{headers,data:{preferred_language:'zh',text_scale_percent:150}});await page.reload();await expect(page.getByText(/已显示记录/)).toBeVisible();await page.setViewportSize({width:390,height:844});await position();await page.screenshot({path:'../outputs/records-fixed-zh150.png'});
 await page.getByLabel('日期范围',{exact:true}).scrollIntoViewIfNeeded();await page.screenshot({path:'../outputs/records-fixed-zh150-date.png'});
});
