/** Actual React App and local FastAPI; DEMO_ONLY records, synthetic Auth only. */
import {test,expect} from '@playwright/test';
import {mockPatientApp} from './polish-a1-fixture';
const id=(n:number)=>`de000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
test('owned medication history: real queries, filters, pagination and responsive rendering',async({page,baseURL})=>{
 test.setTimeout(120000);expect(new URL(baseURL!).origin).toBe('http://127.0.0.1:5182');
 const {errors}=await mockPatientApp(page);
 await page.route(url=>new URL(url).pathname.startsWith('/api/'),route=>route.continue());
 const headers={Authorization:'Bearer DEMO.synthetic-session-token'};
 expect((await page.request.put('/api/me/preferences',{headers,data:{preferred_language:'en',text_scale_percent:100,reminders_enabled:false}})).ok()).toBe(true);
 await page.goto('/');await page.locator('[data-guide="records"]').click();
 const summaryCard=page.locator('.records-summary--highlight');await expect(summaryCard).toBeVisible();
 await expect(page.locator('.records-pending-disclosure')).not.toHaveAttribute('open','');
 expect(await summaryCard.evaluate(node=>{const children=[...node.parentElement!.children];return children.indexOf(node)<children.findIndex(child=>child.classList.contains('records-pending-disclosure'));})).toBe(true);
 await expect(summaryCard.getByRole('button',{name:'This week'})).toBeVisible();
 await page.getByRole('button',{name:/My medication records/}).click();
 const medicine=page.getByLabel('Medicine',{exact:true}),plan=page.getByLabel('Medication plan',{exact:true}),range=page.getByLabel('Date range',{exact:true});
 const rows=page.locator('.record-history .history li'),more=page.getByRole('button',{name:'Load more records',exact:true});
 await expect(medicine).toHaveValue('');await expect(plan).toHaveValue('');await expect(range).toHaveValue('30');await expect(rows).toHaveCount(5);
 for(const count of [10,15,20,25,30,35,38]){await more.click();await expect(rows).toHaveCount(count);}await expect(more).toHaveCount(0);
 const labels=await medicine.locator('option').allTextContents();expect(labels.filter(x=>x.includes('Amlodipine'))).toHaveLength(1);expect(new Set(labels).size).toBe(labels.length);
 const search=page.getByRole('searchbox',{name:'Search medicines'});await search.fill('AMLODIPINE');await expect(medicine.locator('option')).toHaveCount(2);
 expect((await medicine.locator('option').allTextContents()).some(label=>label.includes('00000101')||label.includes('Registration:'))).toBe(false);
 await medicine.focus();await medicine.press('Home');await medicine.press('ArrowDown');await expect(medicine).toHaveValue('demo amlodipine');await expect(rows).toHaveCount(5);await expect(plan).toHaveValue('');
 await page.getByRole('button',{name:'Clear search'}).click();await expect(medicine.locator('option')).toHaveCount(4);
 await medicine.selectOption('demo amlodipine');await expect(rows).toHaveCount(5);
 expect(await plan.locator('option').evaluateAll(options=>options.map(o=>(o as HTMLOptionElement).value))).toEqual(['',id(3),id(4),id(2),id(1)]);
 await plan.selectOption(id(1));await expect(rows).toHaveCount(0);await range.selectOption('plan');await expect(rows).toHaveCount(5);
 for(const count of [10,15,20]){await more.click();await expect(rows).toHaveCount(count);}await expect(more).toHaveCount(0);
 await plan.selectOption(id(3));await range.selectOption('custom');await page.getByLabel('Start date',{exact:true}).fill('2026-10-17');await page.getByLabel('End date',{exact:true}).fill('2026-10-17');await expect(rows).toHaveCount(5);
 for(const count of [10,15,19]){await more.click();await expect(rows).toHaveCount(count);}await expect(more).toHaveCount(0);
 const times=await rows.locator('p').allTextContents();const localTime=await page.evaluate(()=>new Date('2026-10-16T16:18:00Z').toLocaleString('en-SG',{timeZone:'Asia/Singapore'}));expect(times[0]).toContain(localTime);
 await range.selectOption('7');
 for(const [med,count] of [['demo metformin',5],['demo medicine e',6],['demo amlodipine',21]] as const){
  await medicine.selectOption(med);await expect(rows).toHaveCount(Math.min(5,count));
  for(let n=5;n<count;n+=5){await more.click();await expect(rows).toHaveCount(Math.min(n+5,count));}await expect(more).toHaveCount(0);
 }
 await medicine.selectOption('');await range.selectOption('all');await expect(rows).toHaveCount(5);
 for(let n=5;n<58;n+=5){await more.click();await expect(rows).toHaveCount(Math.min(n+5,58));}await expect(more).toHaveCount(0);
 for(const [language,scale] of [['en',100],['zh',150]] as const){
  expect((await page.request.put('/api/me/preferences',{headers,data:{preferred_language:language,text_scale_percent:scale}})).ok()).toBe(true);
  await page.goto('/');await page.locator('[data-guide="records"]').click();
  await expect(page.getByRole('button',{name:'本周'})).toBeVisible();await expect(page.getByRole('button',{name:'本月'})).toBeVisible();await expect(page.getByRole('button',{name:'按用药计划'})).toBeVisible();
  await page.getByRole('button',{name:/我的用药记录/}).click();await expect(rows).toHaveCount(5);
  for(const width of [390,430,768,1024,1280,1600,1920]){await page.setViewportSize({width,height:1000});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
   if([390,1280].includes(width))await page.screenshot({path:`../outputs/records-name-group-${language}-${scale}-${width}.png`,fullPage:true});
  }
 }
 expect(errors).toEqual([]);
});
