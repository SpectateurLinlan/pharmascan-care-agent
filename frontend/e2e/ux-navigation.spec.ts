/** Real browser + local FastAPI application; in-memory synthetic records, no cloud model calls. */
import {test,expect} from '@playwright/test';
test.skip(process.env.RUN_LOCAL_UX!=='1','Requires isolated local in-memory QA servers');
test.use({hasTouch:true});
const artifactRoot=process.env.QA_BROWSER==='edge'?'../outputs/ux-integration-edge':'../outputs/ux-integration';

test('persistent controlled guide, four tabs, task back, drafts and calendar settings',async({page})=>{
 const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
 await page.goto('/');const guide=page.getByRole('dialog',{name:'Quick start guide'});await expect(guide).toBeVisible();
 await page.mouse.click(5,5);await expect(guide).toBeVisible();
 for(const selector of ['.language-shortcut','.patient-nav [data-guide="records"]','.welcome']){const box=await page.locator(selector).boundingBox();if(box)await page.mouse.click(box.x+box.width/2,box.y+box.height/2);await expect(guide).toBeVisible();expect(new URL(page.url()).hash).toBe('#today');}
 await page.touchscreen.tap(5,5);await expect(guide).toBeVisible();
 await page.locator('.language-shortcut').evaluate(button=>(button as HTMLButtonElement).focus());expect(await guide.evaluate(dialog=>dialog.contains(document.activeElement))).toBe(true);
 await page.keyboard.press('Escape');await expect(guide).toBeVisible();
 await expect(page.locator('.patient-nav button')).toHaveCount(4);
 await page.getByRole('button',{name:'Next',exact:true}).click();await expect(page.getByText('2 / 7')).toBeVisible();
 await page.reload();await expect(page.getByText('2 / 7')).toBeVisible();
 const second=await page.context().newPage();await second.goto('about:blank');await page.bringToFront();await expect(page.getByText('2 / 7')).toBeVisible();await second.close();
 for(const width of [390,430,1280]){
   await page.setViewportSize({width,height:900});const next=page.getByRole('button',{name:'Next',exact:true});await next.hover();
   const colors=await next.evaluate(button=>({background:getComputedStyle(button).backgroundColor,color:getComputedStyle(button).color}));
   expect(colors.background).not.toBe('rgb(255, 255, 255)');expect(colors.color).toBe('rgb(255, 255, 255)');
   await expect.poll(async()=>{const box=await guide.boundingBox();return Boolean(box&&box.x>=0&&box.y>=0&&box.x+box.width<=width&&box.y+box.height<=900);}).toBe(true);
   await page.screenshot({path:`${artifactRoot}/guide-hover-${width}.png`});
 }
 await page.getByRole('button',{name:'Skip for now'}).click();await page.reload();await expect(guide).toHaveCount(0);
 await page.evaluate(()=>navigator.serviceWorker.register('/sw.js').then(()=>undefined));await expect.poll(()=>page.evaluate(async()=>(await navigator.serviceWorker.ready).active?.state)).toBe('activated');
 const initialLength=await page.evaluate(()=>history.length);
 for(let i=0;i<20;i++){await page.locator(`[data-guide="${['medicines','records','me','today'][i%4]}"]`).click();await expect(page.getByRole('button',{name:'Back',exact:true})).toHaveCount(0);}
 expect(await page.evaluate(()=>history.length)).toBe(initialLength);
 await expect(page.locator('.greeting')).toContainText('Guest!');
 const input=page.getByLabel('Review your message before sending');await page.getByRole('button',{name:'Open conversation'}).click();await input.fill('DEMO unfinished chat');
await expect(input).toHaveValue('DEMO unfinished chat');
 await page.getByRole('button',{name:'Close conversation'}).click();await expect(page.locator('[data-guide="today"]')).toHaveAttribute('aria-current','page');await expect(input).toHaveValue('DEMO unfinished chat');
 await page.locator('[data-guide="medicines"]').click();await page.getByRole('button',{name:'Ask your assistant'}).click();await expect(input).toHaveValue('DEMO unfinished chat');await page.getByRole('button',{name:'Close conversation'}).click();await expect(page.getByRole('heading',{name:'My Medicines',exact:true})).toBeVisible();
 await page.getByRole('button',{name:/Add medication/}).click();await page.getByRole('button',{name:/Add manually/}).click();await page.getByLabel('Medication name',{exact:true}).fill('DEMO UX draft');
 await page.getByRole('button',{name:'Back',exact:true}).click();await page.getByRole('button',{name:/Add manually/}).click();await expect(page.getByLabel('Medication name',{exact:true})).toHaveValue('DEMO UX draft');
 await page.locator('[data-guide="me"]').click();await page.getByRole('button',{name:/Help \/ User Guide/}).click();await page.getByRole('button',{name:'Quick start guide',exact:true}).click();await expect(guide).toBeVisible();
 for(let i=0;i<6;i++)await page.getByRole('button',{name:'Next',exact:true}).click();await page.getByRole('button',{name:'Finish',exact:true}).click();
 await page.locator('[data-guide="me"]').click();await page.locator('.entry-group').getByRole('button',{name:/Medication reminders/}).click();await expect(page.getByText(/No upcoming timed reminders/)).toBeVisible();
 await expect(page.getByRole('button',{name:'Enable on this device',exact:true})).toBeDisabled();await expect(page.getByText(/Web Push is not configured/)).toBeVisible();
 for(const width of [390,430,1280]){await page.setViewportSize({width,height:900});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:`${artifactRoot}/reminder-settings-${width}.png`});}
 await page.goto('/#manual');await page.reload();await expect(page.getByRole('heading',{name:'Add a medication',exact:true})).toBeVisible();await page.getByRole('button',{name:'Back',exact:true}).click();await expect(page.getByRole('heading',{name:'Add medication',exact:true})).toBeVisible();
 expect(errors).toEqual([]);
});

test('reviewed plan automatically reminds without intake writes and exports a real calendar',async({page})=>{
 await page.goto('/');await page.getByRole('button',{name:'Skip for now'}).click();
 await page.locator('[data-guide="me"]').click();await page.locator('.entry-group').getByRole('button',{name:/Medication reminders/}).click();
 const leadSaved=page.waitForResponse(response=>response.request().method()==='PUT'&&response.url().includes('/preferences'));
 await page.getByLabel('Reminder lead minutes',{exact:true}).fill('15');expect((await leadSaved).status()).toBe(200);
 await page.locator('[data-guide="medicines"]').click();await page.getByRole('button',{name:/Add medication/}).click();await page.getByRole('button',{name:/Add manually/}).click();
 await page.getByLabel('Medication name',{exact:true}).fill('DEMO automatic reminder');await page.getByLabel('Dose amount',{exact:true}).fill('1');await page.getByLabel('Unit',{exact:true}).fill('tablet');
 const time=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Singapore',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(Date.now()+5*60000));
 await page.locator('#med-time-0').fill(time);await page.getByRole('button',{name:'Create draft',exact:true}).click();await page.getByRole('button',{name:'I have reviewed these details'}).click();await page.getByRole('button',{name:'Show me the summary to confirm'}).click();
 const activated=page.waitForResponse(response=>response.url().includes('/medications/activate'));await page.getByRole('button',{name:'Yes, save this medication'}).click();const activation=await activated;expect(activation.status()).toBe(200);const {regimen_id}=await activation.json() as {regimen_id:string};
 await page.locator('[data-guide="today"]').click();const prompt=page.getByRole('dialog',{name:'Medication reminder'});await expect(prompt).toBeVisible({timeout:35000});await expect(prompt).toContainText('DEMO automatic reminder');
 await page.screenshot({path:`${artifactRoot}/automatic-reminder-390.png`});await prompt.getByRole('button',{name:'Dismiss',exact:true}).click();
 const clientId=await page.evaluate(()=>localStorage.getItem('pharmascan.client_id'));
 const history=await page.request.get(`/api/me/dose-history?client_id=${clientId}&regimen_id=${regimen_id}`);expect(history.ok()).toBe(true);const records=await history.json() as {entries:Array<{reported:boolean}>};expect(records.entries.every(row=>!row.reported)).toBe(true);
 await page.locator('[data-guide="me"]').click();await page.locator('.entry-group').getByRole('button',{name:/Medication reminders/}).click();await expect(page.getByText(/DEMO automatic reminder/).first()).toBeVisible();
 const download=page.waitForEvent('download');await page.getByRole('button',{name:'Add to Calendar',exact:true}).click();expect((await download).suggestedFilename()).toBe('pharmascan-reminders.ics');
 const exported=await page.request.get(`/api/reminders/calendar?client_id=${clientId}`);expect(exported.ok()).toBe(true);const ics=await exported.text();expect(ics).toContain('BEGIN:VALARM');expect(ics).not.toContain('DEMO automatic reminder');
 const disabled=page.waitForResponse(response=>response.request().method()==='PUT'&&response.url().includes('/preferences'));await page.getByLabel('Enable medication reminders',{exact:true}).uncheck();expect((await disabled).status()).toBe(200);await expect(page.getByText(/No upcoming timed reminders/)).toBeVisible();
 await page.locator('[data-guide="medicines"]').click();await page.getByRole('button',{name:/DEMO automatic reminder/}).click();
 await page.getByText('Regimen history',{exact:true}).click();await page.getByRole('button',{name:'Review a new plan version',exact:true}).click();
 const editor=page.locator('[data-page="edit-medication"]');await expect(editor.getByLabel('Medication name',{exact:true})).toHaveValue('DEMO automatic reminder');
 await editor.locator('#edit-med-time-0').fill('19:00');await page.getByRole('button',{name:'Back',exact:true}).click();await expect(page.getByRole('heading',{name:'DEMO automatic reminder',exact:true})).toBeVisible();await page.getByRole('button',{name:'Review a new plan version',exact:true}).click();await expect(editor.locator('#edit-med-time-0')).toHaveValue('19:00');
 await editor.getByRole('button',{name:'Create draft',exact:true}).click();await editor.getByRole('button',{name:'I have reviewed these details'}).click();await editor.getByRole('button',{name:'Show me the summary to confirm'}).click();await editor.getByRole('button',{name:'Yes, save this medication'}).click();
 await expect(page.getByRole('heading',{name:'DEMO automatic reminder',exact:true})).toBeVisible();await page.getByRole('button',{name:'Stop this recorded plan',exact:true}).click();await page.getByRole('button',{name:'Cancel',exact:true}).click();await page.getByRole('button',{name:'Stop this recorded plan',exact:true}).click();await page.getByRole('button',{name:'Confirm stop',exact:true}).click();await expect(page.getByRole('button',{name:'Stop this recorded plan',exact:true})).toHaveCount(0);
 const versions=await (await page.request.get(`/api/me/regimens?client_id=${clientId}`)).json() as Array<{state:string;medication_id:string}>;expect(versions).toHaveLength(2);expect(new Set(versions.map(row=>row.medication_id)).size).toBe(1);expect(versions.map(row=>row.state).sort()).toEqual(['ended','superseded']);
 expect((await page.request.get(`/api/reminders/calendar?client_id=${clientId}`)).status()).toBe(422);
 await page.locator('[data-guide="me"]').click();await page.locator('.entry-group').getByRole('button',{name:/Medication reminders/}).click();
 await page.getByRole('button',{name:'Back',exact:true}).click();await page.getByRole('button',{name:/Language and speech/}).last().click();await page.getByLabel('Settings language').selectOption('zh');await expect(page.getByRole('heading',{name:'语言与语音'})).toBeVisible();
 await page.getByRole('button',{name:'返回',exact:true}).click();await page.getByRole('button',{name:/无障碍设置|无障碍/}).click();const slider=page.getByRole('slider');await slider.fill('150');await slider.dispatchEvent('pointerup');
 await page.locator('[data-guide="today"]').click();await expect(page.locator('.greeting')).toContainText('访客!');
 for(const width of [390,430,1280]){await page.setViewportSize({width,height:900});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:`${artifactRoot}/today-zh-large-${width}.png`});}
 await page.locator('[data-guide="me"]').click();await page.getByRole('button',{name:/帮助／使用指南/}).click();await page.getByRole('button',{name:'新手指南',exact:true}).click();
 const largeGuide=page.getByRole('dialog',{name:'新手指南'});await expect(largeGuide).toBeVisible();
 for(const width of [390,430,1280]){await page.setViewportSize({width,height:900});await expect.poll(async()=>{const box=await largeGuide.boundingBox();return Boolean(box&&box.x>=0&&box.y>=0&&box.x+box.width<=width&&box.y+box.height<=900);}).toBe(true);await page.screenshot({path:`${artifactRoot}/guide-zh-large-${width}.png`});}
 await page.getByRole('button',{name:'稍后再说',exact:true}).click();
});

test('visual result Back preserves acquisition and Forward restores evidence (visual HTTP MOCK)',async({page})=>{
 await page.route('**/api/evidence/check-dose*',route=>route.fulfill({json:{id:'00000000-0000-4000-a000-000000000001',decision:'missing_reference',reason:'No eligible personal pill photos are available. Add a reference photo to your medication.',reference_ids:[],outcome:null,ingestion_proven:false,safe_to_take:false}}));
 await page.goto('/');await page.getByRole('button',{name:'Skip for now'}).click();await page.getByRole('button',{name:'Compare a pill photo',exact:true}).click();await page.getByRole('button',{name:'Check this dose',exact:true}).click();
 await page.locator('input[type=file]:visible').setInputFiles({name:'DEMO-synthetic.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a1XcAAAAASUVORK5CYII=','base64')});
 await page.getByRole('checkbox').check();await page.getByRole('button',{name:'Check photo',exact:true}).click();await expect(page.getByRole('heading',{name:'Photo check result',exact:true})).toBeVisible();await expect(page.getByText('Add a personal reference first',{exact:true})).toBeVisible();
 await page.screenshot({path:`${artifactRoot}/mock-visual-result-390.png`});await page.getByRole('button',{name:'Back',exact:true}).click();await expect(page.getByRole('heading',{name:'Compare a pill photo',exact:true})).toBeVisible();
 expect(await page.locator('input[type=file]:visible').evaluate(input=>(input as HTMLInputElement).files?.[0]?.name)).toBe('DEMO-synthetic.png');
 await page.goForward();await expect(page.getByRole('heading',{name:'Photo check result',exact:true})).toBeVisible();await page.goBack();await page.getByRole('button',{name:'Back',exact:true}).click();await expect(page.locator('[data-guide="today"]')).toHaveAttribute('aria-current','page');await expect(page.getByRole('button',{name:'Back',exact:true})).toHaveCount(0);
});
