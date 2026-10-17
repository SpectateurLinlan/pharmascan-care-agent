/** BROWSER E2E + real current Application API, isolated LOCAL memory persistence. */
import {test,expect} from '@playwright/test';
import {mkdirSync,readFileSync} from 'node:fs';

test.skip(process.env.RUN_MEDITHREAD_RC!=='1','Requires isolated RC servers; no production credentials');

test('current enrollment contract, independent confirmation, saved chat and responsive product surfaces',async({page})=>{
 page.setDefaultTimeout(12000);
 const artifacts='../outputs/medithread-rc/browser';mkdirSync(artifacts,{recursive:true});
 const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
 await page.route('**/*',route=>['localhost','127.0.0.1'].includes(new URL(route.request().url()).hostname)?route.continue():route.abort());
 await page.goto('/');await expect(page).toHaveTitle(/MediThread/);
 const next=page.getByRole('button',{name:'Next',exact:true});await expect(next).toBeVisible();
 await page.mouse.click(4,4);await expect(next).toBeVisible();
 await next.hover();await page.screenshot({path:`${artifacts}/guide-hover-390.png`});
 await next.click();await expect(page.getByRole('button',{name:'Previous',exact:true})).toBeVisible();
 await page.reload();await expect(page.getByRole('button',{name:'Previous',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Skip for now',exact:true}).click();
 await page.locator('[data-guide="medicines"]').click();
 await page.getByRole('button',{name:/Add medication$/}).click();
 await page.getByRole('button',{name:/^Add manually/}).click();
 await page.getByLabel('Medication name',{exact:true}).fill('DEMO Metformin 500 mg tablet');
 await page.getByLabel('Dose amount',{exact:true}).fill('1');
 await page.getByRole('button',{name:'Review and add',exact:true}).click();
 await page.getByRole('checkbox',{name:'I have checked these details against my original instructions.'}).check();
 const draftRequest=page.waitForRequest(request=>request.method()==='POST'&&new URL(request.url()).pathname==='/api/medications/drafts');
 const draftResponse=page.waitForResponse(response=>response.request().method()==='POST'&&new URL(response.url()).pathname==='/api/medications/drafts');
 await page.getByRole('button',{name:'Add this medication',exact:true}).click();
 const nativeBody=(await draftRequest).postDataJSON() as Record<string,unknown>;
 expect(nativeBody).toHaveProperty('frequency_days_of_week');expect(nativeBody).toHaveProperty('dose_basis');
 expect((await draftResponse).status()).toBe(200);
 const confirmation=page.getByRole('dialog',{name:'Please check this before I save it'});await expect(confirmation).toBeVisible();
 const clientId=await page.evaluate(()=>localStorage.getItem('pharmascan.client_id'));
 const q=`?client_id=${clientId}`;
 expect((await (await page.request.get('/api/me/medications'+q)).json()).item_count).toBe(0);
 const activated=page.waitForResponse(response=>response.request().method()==='POST'&&new URL(response.url()).pathname==='/api/medications/activate');
 await confirmation.getByRole('button',{name:'Yes, save this medication'}).click();expect((await activated).status()).toBe(200);
 const later=page.getByRole('button',{name:'Later',exact:true});if(await later.isVisible())await later.click();
 await page.locator('[data-guide="today"]').click();
 await expect(page.getByText('DEMO Metformin 500 mg tablet').first()).toBeVisible();
 await page.getByLabel('Review your message before sending').focus();
 const assistant=page.locator('.conversation-workspace');await expect(assistant).toBeVisible();
 await assistant.getByText('Saved conversations',{exact:true}).click();
 const toggle=assistant.getByRole('checkbox',{name:'Save new conversations on this account'});
 const preference=page.waitForResponse(response=>response.request().method()==='PUT'&&response.url().includes('/api/me/preferences'));
 await toggle.click();expect((await preference).status()).toBe(200);await expect(toggle).toBeChecked();
 await assistant.getByLabel('Review your message before sending').fill('DEMO show my medication plan');
 const reply=page.waitForResponse(response=>response.request().method()==='POST'&&response.url().includes('/api/agent/messages'));
 await assistant.getByRole('button',{name:'Send',exact:true}).click();expect((await reply).status()).toBe(200);
 await expect.poll(async()=> (await (await page.request.get('/api/agent/history'+q)).json()).entries.length).toBe(1);
 await page.reload();await page.getByLabel('Review your message before sending').focus();
 await assistant.getByText('Saved conversations',{exact:true}).click();await expect(toggle).toBeChecked();
 await expect(assistant.locator('.conversation-history').getByText('DEMO show my medication plan',{exact:true})).toBeVisible();
 await page.screenshot({path:`${artifacts}/saved-history-390.png`});
 await assistant.getByRole('button',{name:'Back'}).click();
 for(const width of [390,430,768,1280]){
  await page.setViewportSize({width,height:1000});
  for(const tab of ['today','medicines','records','me']){
   await page.locator(`[data-guide="${tab}"]`).click();
   await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),{timeout:2000,message:JSON.stringify(await page.evaluate(()=>Array.from(document.querySelectorAll('body *')).filter(el=>el.getBoundingClientRect().right>innerWidth+1).slice(-8).map(el=>({tag:el.tagName,cls:el.className,width:el.getBoundingClientRect().width,text:el.textContent?.slice(0,45)}))))}).toBe(true);
   await page.screenshot({path:`${artifacts}/${tab}-en-${width}.png`});
  }
 }
 expect((await page.request.put('/api/me/preferences'+q,{data:{preferred_language:'zh',text_scale_percent:150}})).status()).toBe(200);
 await page.reload();
 for(const width of [390,430,768,1280]){
  await page.setViewportSize({width,height:1000});
  for(const tab of ['today','medicines','records','me']){
   await page.locator(`[data-guide="${tab}"]`).click();
   await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),{timeout:2000,message:JSON.stringify(await page.evaluate(()=>Array.from(document.querySelectorAll('body *')).filter(el=>el.getBoundingClientRect().right>innerWidth+1).slice(-8).map(el=>({tag:el.tagName,cls:el.className,width:el.getBoundingClientRect().width,text:el.textContent?.slice(0,45)}))))}).toBe(true);
   await page.screenshot({path:`${artifacts}/${tab}-zh-150-${width}.png`});
  }
 }
 expect(errors).toEqual([]);
});

test('Scenario D review uses five-day Application API records and exports patient questions',async({page})=>{
 page.setDefaultTimeout(12000);
 const artifacts='../outputs/medithread-rc/browser';mkdirSync(artifacts,{recursive:true});
 await page.addInitScript(()=>localStorage.setItem('pharmascan.client_id','DEMO-release-D'));
 await page.goto('http://127.0.0.1:5178');
 await page.getByRole('button',{name:'Skip for now',exact:true}).click();
 await page.locator('[data-guide="records"]').click();
 await page.getByRole('button',{name:/Medication review preparation/}).click();
 await page.getByLabel('Observation window').selectOption('7');
 await expect(page.locator('.health-trend')).toBeVisible();
 await expect(page.getByText(/Patient reported taken: 2/)).toBeVisible();
 await expect(page.getByText(/DEMO work schedule made reporting difficult/)).toBeVisible();
 await page.getByLabel('Your additional questions (included in export)').fill('DEMO ask my pharmacist about reporting difficulties.');
 const downloading=page.waitForEvent('download');await page.getByRole('button',{name:'Export medication review'}).click();
 const download=await downloading;expect(download.suggestedFilename()).toBe('medithread-medication-review.txt');
 await download.saveAs(`${artifacts}/medication-review.txt`);
 const text=readFileSync(`${artifacts}/medication-review.txt`,'utf8');
 for(const expected of ['MediThread','Patient reported taken: 2','Patient reported not taken: 1','Patient is unsure: 1','unrecorded is not missed','DEMO ask my pharmacist about reporting difficulties.'])expect(text).toContain(expected);
 await page.screenshot({path:`${artifacts}/review-five-day-390.png`,fullPage:true});
 await page.reload();await page.locator('[data-guide="records"]').click();
 await page.getByRole('button',{name:/Medication review preparation/}).click();
 await expect(page.locator('.health-trend')).toBeVisible();
});
