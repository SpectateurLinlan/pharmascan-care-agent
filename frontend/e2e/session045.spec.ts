/** Browser integration against isolated in-memory FastAPI; no provider inference. */
import {test,expect} from '@playwright/test';
test.skip(process.env.RUN_LOCAL_UX!=='1','Requires isolated local synthetic QA servers');
test.use({hasTouch:true});
const artifacts=`../outputs/session045/${process.env.QA_BROWSER??'chrome'}`;

test('controlled tour, in-place conversation, four roots and responsive patient surfaces',async({page})=>{
 page.setDefaultTimeout(12000);const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
 await page.goto('/');const guide=page.getByRole('dialog',{name:'Quick start guide'});await expect(guide).toBeVisible();
 await page.mouse.click(4,4);await page.keyboard.press('Escape');await expect(guide).toBeVisible();
 await page.getByRole('button',{name:'Next',exact:true}).click();await page.reload();await expect(page.getByText('2 / 7')).toBeVisible();
 const next=guide.getByRole('button',{name:'Next',exact:true});await next.hover();
 const colors=await next.evaluate(el=>({bg:getComputedStyle(el).backgroundColor,fg:getComputedStyle(el).color}));expect(colors.bg).not.toBe(colors.fg);
 await page.screenshot({path:`${artifacts}/guide-hover-390.png`});await guide.getByRole('button',{name:'Skip for now'}).click();
 await expect(page.locator('.greeting')).toContainText('Guest!');await expect(page.locator('.patient-nav button')).toHaveCount(4);await expect(page.locator('.patient-nav svg')).toHaveCount(4);
 const history=await page.evaluate(()=>window.history.length);
 for(let i=0;i<20;i++)await page.locator(`[data-guide="${['medicines','records','me','today'][i%4]}"]`).click();
 expect(await page.evaluate(()=>window.history.length)).toBe(history);await expect(page.getByRole('button',{name:'Back',exact:true})).toHaveCount(0);
 const input=page.getByLabel('Review your message before sending');const before=page.url();await page.getByRole('button',{name:'Open conversation'}).click();await input.fill('DEMO retained draft');
 const dialog=page.getByRole('dialog',{name:'Medication assistant'});await expect(dialog).toBeVisible();expect(page.url()).toBe(before);await expect(input).toHaveValue('DEMO retained draft');expect(await page.locator('[data-app-content]').evaluate(el=>(el as HTMLElement).inert)).toBe(true);
 await page.screenshot({path:`${artifacts}/assistant-390.png`});await dialog.getByRole('button',{name:'Close conversation'}).click();await expect(input).toHaveValue('DEMO retained draft');
 await page.locator('[data-guide="medicines"]').click();await page.getByRole('button',{name:'Ask your assistant'}).click();await expect(input).toHaveValue('DEMO retained draft');await page.getByRole('button',{name:'Close conversation'}).click();await expect(page.getByRole('heading',{name:'My Medicines',exact:true})).toBeVisible();
 for(const width of [390,430,768,1280]){
  await page.setViewportSize({width,height:900});
  for(const root of ['today','me']){await page.locator(`[data-guide="${root}"]`).click();await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:`${artifacts}/${root}-${width}.png`});}
 }
 await page.locator('.entry-group').getByRole('button',{name:/Language and speech/}).click();await page.getByLabel('Settings language').selectOption('zh');await page.locator('[data-guide="me"]').click();
 await page.getByRole('button',{name:/无障碍设置|无障碍/}).click();const slider=page.getByRole('slider');await slider.fill('150');await slider.dispatchEvent('pointerup');
 for(const width of [390,430,768,1280]){await page.setViewportSize({width,height:900});await page.locator('[data-guide="today"]').click();await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:`${artifacts}/today-zh-150-${width}.png`});}
 await page.getByRole('button',{name:'展开助手对话'}).click();await page.setViewportSize({width:390,height:480});await expect(page.getByRole('button',{name:'发送',exact:true})).toBeInViewport();await page.screenshot({path:`${artifacts}/assistant-zh-150-resize.png`});
 expect(errors).toEqual([]);
});

test('source-based count display and opt-in chat survive refresh without changing the plan',async({page})=>{
 page.setDefaultTimeout(12000);await page.goto('/');await page.getByRole('button',{name:'Skip for now'}).click();
 await page.locator('[data-guide="medicines"]').click();await page.getByRole('button',{name:/Add medication/}).click();await page.getByRole('button',{name:/Add manually/}).click();
 await page.getByLabel('Medication name',{exact:true}).fill('DEMO Long-name Metformin extended-release reference');await page.getByLabel('Dose amount',{exact:true}).fill('1');
 await page.getByText('Product strength and original instructions',{exact:true}).click();await page.getByLabel('Strength per tablet or capsule').fill('500 mg');await page.getByLabel('Dosage form',{exact:true}).selectOption('tablet');await page.getByLabel('Formulation',{exact:true}).selectOption('modified_release');await page.getByLabel('Ingredient scope').selectOption('single');await page.getByLabel('Original dose instructions',{exact:true}).fill('Take 1 tablet daily');
 await page.getByLabel('I checked the strength, form and count against my original instructions.').check();await page.getByRole('button',{name:'Show total from these details'}).click();await expect(page.getByRole('status').filter({hasText:'Total per dose: 500 mg'})).toBeVisible();
 await page.getByRole('button',{name:'Create draft',exact:true}).click();await page.getByRole('button',{name:'I have reviewed these details'}).click();await page.getByRole('button',{name:'Show me the summary to confirm'}).click();await page.getByRole('button',{name:'Yes, save this medication'}).click();await page.locator('[data-guide="today"]').click();
 await page.reload();await expect(page.getByText('DEMO Long-name Metformin extended-release reference',{exact:true}).first()).toBeVisible();await expect(page.getByText('Loading your reviewed schedule...', {exact:true})).toHaveCount(0);await page.screenshot({path:`${artifacts}/reviewed-count-plan-390.png`});
 await page.getByRole('button',{name:'Open conversation'}).click();await page.getByText('Saved conversations',{exact:true}).click();
 const opted=page.waitForResponse(response=>response.url().includes('/preferences')&&response.request().method()==='PUT');await page.getByLabel('Save conversations on this account').click();expect((await opted).ok()).toBe(true);await expect(page.getByLabel('Save conversations on this account')).toBeChecked();
 const input=page.getByLabel('Review your message before sending');await input.fill('Do I need medicine today?');const answer=page.waitForResponse(response=>response.url().includes('/agent/messages'));await page.getByRole('button',{name:'Send',exact:true}).click();expect((await answer).ok()).toBe(true);
 await page.reload();await page.getByRole('button',{name:'Open conversation'}).click();await page.getByText('Saved conversations',{exact:true}).click();await expect(page.locator('.history-message')).toContainText('Do I need medicine today?');await page.locator('.history-message').scrollIntoViewIfNeeded();await page.screenshot({path:`${artifacts}/saved-history-390.png`});
 await page.getByRole('button',{name:'Clear saved conversations',exact:true}).click();await page.getByRole('button',{name:'Confirm clear',exact:true}).click();await expect(page.locator('.history-message')).toHaveCount(0);
 await page.getByRole('button',{name:'Close conversation'}).click();await expect(page.getByText('DEMO Long-name Metformin extended-release reference',{exact:true}).first()).toBeVisible();
});
