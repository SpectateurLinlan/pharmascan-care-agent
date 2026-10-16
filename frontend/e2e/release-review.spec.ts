/** Scenario D browser acceptance: Application HTTP/B14 seed, LOCAL memory/time. */
import {test,expect} from '@playwright/test';
import {mkdirSync,readFileSync,writeFileSync} from 'node:fs';
import {skipInitialGuide} from './navigation-helpers';

test.skip(process.env.RUN_RELEASE_BROWSER!=='1','Requires isolated Scenario D synthetic timeline server');

test('five-day review, patient questions, export, refresh and responsive layout',async({page})=>{
 page.setDefaultTimeout(12000);
 const root='../outputs/session05/browser';mkdirSync(root,{recursive:true});
 const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
 await page.addInitScript(()=>localStorage.setItem('pharmascan.client_id','DEMO-release-D'));
 await page.goto('/');await skipInitialGuide(page);
 await page.locator('[data-guide="records"]').click();
 await page.getByRole('button',{name:/Medication review preparation/}).click();
 await page.getByLabel('Observation window').selectOption('7');
 await expect(page.locator('.health-trend')).toBeVisible();
 const response=await page.request.get('/api/me/medication-review?client_id=DEMO-release-D&days=7');
 expect(response.status()).toBe(200);const data=await response.json() as {summary:{reported_taken:number;reported_not_taken:number;unsure:number;medications:Array<{without_report:number}>}};
 expect([data.summary.reported_taken,data.summary.reported_not_taken,data.summary.unsure,data.summary.medications[0]!.without_report]).toEqual([2,1,1,1]);
 await expect(page.getByText(/DEMO work schedule made reporting difficult/).first()).toBeVisible();
 await page.getByLabel('Your additional questions (included in export)').fill('DEMO ask the pharmacist about my reporting routine.');
 const downloading=page.waitForEvent('download');await page.getByRole('button',{name:'Export medication review'}).click();
 const download=await downloading;await download.saveAs(`${root}/medication-review.txt`);
 const exported=readFileSync(`${root}/medication-review.txt`,'utf8');
 expect(exported).toContain('Patient reported taken: 2');expect(exported).toContain('Patient reported not taken: 1');
 expect(exported).toContain('Patient is unsure: 1');expect(exported).toContain('unrecorded is not missed');
 expect(exported).toContain('DEMO ask the pharmacist about my reporting routine.');
 for(const width of [390,430,1280]){await page.setViewportSize({width,height:900});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:`${root}/review-${width}.png`,fullPage:true});}
 await page.reload();await page.locator('[data-guide="records"]').click();await page.getByRole('button',{name:/Medication review preparation/}).click();
 await expect(page.locator('.health-trend')).toBeVisible();
 await page.locator('[data-guide="me"]').click();await page.getByRole('button',{name:/Accessibility/}).click();
 await page.locator('#text-size').focus();await page.locator('#text-size').press('End');await expect(page.locator('#text-size')).toHaveValue('150');
 await page.getByRole('button',{name:'Language and speech',exact:true}).click();
 const saving=page.waitForResponse(row=>row.request().method()==='PUT'&&row.url().includes('/preferences'));
 await page.getByRole('menuitemradio',{name:'中文',exact:true}).click();expect((await saving).status()).toBe(200);
 await page.locator('[data-guide="records"]').click();await page.getByRole('button',{name:/就诊与用药复查准备/}).click();
 await expect(page.locator('.health-trend')).toBeVisible();
 for(const width of [390,430,1280]){await page.setViewportSize({width,height:900});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:`${root}/review-zh-large-${width}.png`,fullPage:true});}
 expect(errors).toEqual([]);
 writeFileSync(`${root}/evidence.json`,JSON.stringify({demo_only:true,classification:'BROWSER E2E VERIFIED / LOCAL memory and injected time',counts:data.summary,page_errors:errors,export_verified:true},null,2));
});
