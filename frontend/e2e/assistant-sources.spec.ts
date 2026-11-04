/** Real loopback, synthetic label replay; no production/provider/device evidence. */
import {test,expect,type Page} from '@playwright/test';
import {readFileSync} from 'node:fs';
const photo=readFileSync(new URL('../../tests/backend/fixtures/DEMO_workflow_photo.png',import.meta.url));
const failedPhoto=readFileSync(new URL('../../tests/backend/fixtures/DEMO_workflow_photo_unavailable.png',import.meta.url));

async function open(page:Page,language:'en'|'zh'){
 const client=`DEMO-sources-${language}-${crypto.randomUUID()}`;
 expect((await (await page.request.get('/api/health')).json()).database).toBe('simulated_in_memory');
 const session=await (await page.request.post('/api/demo/start',{data:{client_id:client}})).json();
 await page.request.put(`/api/me/preferences?client_id=${client}`,{data:{preferred_language:language,voice_enabled:false,tts_autoplay:false}});
 await page.addInitScript(({client,owner})=>{localStorage.setItem('pharmascan.client_id',client);localStorage.setItem(`pharmascan.quick-start.v4:${owner}`,JSON.stringify({version:4,status:'skipped',step:0}));},{client,owner:session.patient_id});
 await page.goto('/');
 const composer=page.locator('.composer-row').getByRole('textbox');
 await composer.fill(language==='zh'?'添加药物来源':'add a medication source');await composer.press('Enter');
 const panel=page.getByRole('region',{name:language==='zh'?'当前办理任务':'Current task'});
 await expect(panel.getByRole('button',{name:language==='zh'?'选择照片':'Choose a photo',exact:true})).toBeVisible();
 return {client,panel};
}
for(const language of ['en','zh'] as const){
 test(`source original is saved first and shared review activates independently in ${language}`,async({page,baseURL})=>{
  test.setTimeout(90000);expect(new URL(baseURL!).hostname).toBe('127.0.0.1');
  await page.setViewportSize(language==='en'?{width:1280,height:900}:{width:390,height:844});
  const {client,panel}=await open(page,language);
  await page.locator('.composer-row input[type=file]').setInputFiles({name:'DEMO-source.png',mimeType:'image/png',buffer:photo});
  const send=page.getByRole('button',{name:language==='zh'?'发送':'Send',exact:true});
  await expect(send).toBeEnabled({timeout:5000});await send.click();
  await page.getByRole('checkbox',{name:language==='zh'?'允许识别已保存的照片':'Allow recognition of saved photos'}).check();
  await page.getByRole('button',{name:language==='zh'?'识别已保存照片':'Recognize saved photo',exact:true}).click();
  await panel.getByRole('button',{name:language==='zh'?'核对药物来源':'Review medication source',exact:true}).click();
  let lost=false;
  if(language==='en')await page.route(/\/api\/evidence\/tasks\/[^/]+\/saved-original\?/,async route=>{if(lost){await route.continue();return;}lost=true;const result=await route.fetch();expect(result.ok()).toBe(true);await route.abort('failed');});
  await panel.getByRole('button',{name:language==='zh'?'保存此来源并继续核对':'Save this source and continue review',exact:true}).click();
  if(language==='en'){await expect(page.getByRole('alert')).toBeVisible();await panel.getByRole('button',{name:'Check task status',exact:true}).click();expect(lost).toBe(true);}
  const source=panel.getByRole('region',{name:language==='zh'?'核对药物来源':'Review medication sources'});
  await expect(source.getByRole('heading',{name:'DEMO Photo medicine'})).toBeVisible();
  const initial=(await (await page.request.get(`/api/evidence/tasks?client_id=${client}`)).json())[0];
  await source.getByRole('button',{name:language==='zh'?'补充另一份资料':'Add another source',exact:true}).click();
  await page.locator('.composer-row input[type=file]').setInputFiles({name:'DEMO-duplicate-original.png',mimeType:'image/png',buffer:photo});await send.click();
  await source.getByRole('combobox',{name:language==='zh'?'选择来源原图':'Choose the original source photo'}).selectOption({label:language==='zh'?'来源原图 2':'Original photo 2'});
  await source.getByRole('button',{name:language==='zh'?'保存所选补充来源':'Save selected additional source',exact:true}).click();
  await expect(source.getByRole('combobox',{name:language==='zh'?'选择来源原图':'Choose the original source photo'})).toHaveValue('');
  const supplemented=(await (await page.request.get(`/api/evidence/tasks?client_id=${client}`)).json());expect(supplemented).toHaveLength(1);expect(supplemented[0].id).toBe(initial.id);expect(supplemented[0].source_ids).toEqual(initial.source_ids);
  const sourceComposer=page.locator('.composer-row').getByRole('textbox');await sourceComposer.fill(language==='zh'?'核对药物来源':'review medication sources');await sourceComposer.press('Enter');
  await panel.getByRole('button',{name:`${language==='zh'?'选择来源':'Choose source'}: DEMO Photo medicine 200mg`,exact:true}).click();
  await panel.getByRole('button',{name:language==='zh'?'继续原登记任务':'Continue original enrollment',exact:true}).click();await expect(source.getByRole('heading',{name:'DEMO Photo medicine'})).toBeVisible();
  await source.locator('input[type=time]').first().fill('08:00');await source.locator('.time-input-row .icon-button').first().click();await source.locator('input[type=time]').nth(1).fill('20:00');
  await source.locator('.consent input[type=checkbox]').last().check();
  await page.screenshot({path:`../outputs/assistant-workflows/source-review-${language}.png`,fullPage:true});
  await source.getByRole('heading',{name:'DEMO Photo medicine'}).scrollIntoViewIfNeeded();await page.screenshot({path:`../outputs/assistant-workflows/source-review-top-${language}.png`,fullPage:true});
  if(language==='zh')await page.route(/\/api\/evidence\/tasks\/[^/]+\/review\?/,async route=>{if(lost){await route.continue();return;}lost=true;const result=await route.fetch();expect(result.ok()).toBe(true);await route.abort('failed');});
  await source.getByRole('button',{name:language==='zh'?'保存已核对来源并继续':'Save reviewed source and continue',exact:true}).click();
  if(language==='zh'){await expect(page.getByRole('alert')).toBeVisible();await panel.getByRole('button',{name:'核查办理状态',exact:true}).click();expect(lost).toBe(true);}
  const add=panel.getByRole('button',{name:language==='zh'?'添加此药物':'Add this medication',exact:true});await expect(add).toBeDisabled();
  const rows=await (await page.request.get(`/api/me/regimens?client_id=${client}`)).json();expect(rows).toHaveLength(1);expect(rows[0].state).toBe('draft');
  const composer=page.locator('.composer-row').getByRole('textbox');await composer.fill(language==='zh'?'继续药物草稿':'resume a medication draft');await composer.press('Enter');
  await panel.getByRole('button',{name:`${language==='zh'?'选择草稿':'Choose draft'}: DEMO Photo medicine · v1`,exact:true}).click();
  await panel.getByRole('button',{name:language==='zh'?'继续原登记任务':'Continue original enrollment',exact:true}).click();
  await expect(add).toBeVisible();
  await panel.getByRole('checkbox',{name:language==='zh'?'我已对照原始服用说明核对过以上内容。':'I have checked these details against my original instructions.'}).check();
  await add.click();await page.getByRole('button',{name:language==='zh'?'确认：激活此用药计划':'Yes, save this medication',exact:true}).click();
  await expect(panel).toContainText(language==='zh'?'药物计划已启用。':'The medication plan is active.');
  const tasks=await (await page.request.get(`/api/agent/workflows/tasks?client_id=${client}`)).json();expect(tasks).toHaveLength(3);const completed=tasks.find((row:{capability_id:string})=>row.capability_id==='medication.source.add');expect(completed.state).toBe('completed');
  const originals=await (await page.request.get(`/api/agent/workflows/tasks/${completed.task_id}/attachments?client_id=${client}`)).json();
  expect(originals).toHaveLength(2);for(const original of originals){const raw=await page.request.get(`/api/agent/workflows/tasks/${completed.task_id}/attachments/${original.id}?client_id=${client}`);expect(await raw.body()).toEqual(photo);}
  expect(await page.evaluate(()=>Object.keys(localStorage).some(key=>key.startsWith('pharmascan.enrollment.')))).toBe(false);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 });
 test(`failed source recognition retains the exact original in ${language}`,async({page})=>{
  test.setTimeout(60000);const {client}=await open(page,language);
  await page.locator('.composer-row input[type=file]').setInputFiles({name:'DEMO-unavailable.png',mimeType:'image/png',buffer:failedPhoto});
  await page.getByRole('button',{name:language==='zh'?'发送':'Send',exact:true}).click();
  await page.getByRole('checkbox',{name:language==='zh'?'允许识别已保存的照片':'Allow recognition of saved photos'}).check();
  await page.getByRole('button',{name:language==='zh'?'识别已保存照片':'Recognize saved photo',exact:true}).click();
  await expect(page.getByText(language==='zh'?'暂时无法使用图片识别服务，原图仍已保存。':'Photo recognition is unavailable. The original is still saved.',{exact:true})).toBeVisible();
  const tasks=await (await page.request.get(`/api/agent/workflows/tasks?client_id=${client}`)).json();
  const originals=await (await page.request.get(`/api/agent/workflows/tasks/${tasks[0].task_id}/attachments?client_id=${client}`)).json();
  const raw=await page.request.get(`/api/agent/workflows/tasks/${tasks[0].task_id}/attachments/${originals[0].id}?client_id=${client}`);expect(await raw.body()).toEqual(failedPhoto);
  expect((await (await page.request.get(`/api/evidence/tasks?client_id=${client}`)).json())).toHaveLength(0);
 });
 test(`unsaved source photo stays in page memory until explicit save in ${language}`,async({page})=>{
  test.setTimeout(60000);const {client,panel}=await open(page,language);
  await panel.getByRole('button',{name:language==='zh'?'不保存本次办理':'Do not save this workflow',exact:true}).click();
  const before=await (await page.request.get(`/api/agent/history?client_id=${client}`)).json();
  await page.locator('.composer-row input[type=file]').setInputFiles({name:'DEMO-unsaved.png',mimeType:'image/png',buffer:photo});
  const send=page.getByRole('button',{name:language==='zh'?'发送':'Send',exact:true});await expect(send).toBeDisabled();
  await page.getByRole('checkbox',{name:language==='zh'?'允许处理这张照片。本应用不保存原图，刷新后将丢失页面上的原图。':'Allow photo processing. This app will not save the original; refreshing loses the page copy.'}).check();
  await send.click();await expect(page.getByText(language==='zh'?'仅在当前页面保留，刷新后会丢失此照片。':'Page copy only. Refreshing loses this photo.',{exact:true})).toBeVisible();
  expect((await (await page.request.get(`/api/agent/workflows/tasks?client_id=${client}`)).json())).toHaveLength(0);
  expect((await (await page.request.get(`/api/evidence/tasks?client_id=${client}`)).json())).toHaveLength(0);
  expect(await (await page.request.get(`/api/agent/history?client_id=${client}`)).json()).toEqual(before);
  await panel.getByRole('button',{name:language==='zh'?'现在保存药物并继续核对':'Save this medication and continue review',exact:true}).click();
  await expect(panel.getByRole('button',{name:language==='zh'?'核对药物来源':'Review medication source',exact:true})).toBeVisible();
  const tasks=await (await page.request.get(`/api/agent/workflows/tasks?client_id=${client}`)).json();expect(tasks).toHaveLength(1);
  const originals=await (await page.request.get(`/api/agent/workflows/tasks/${tasks[0].task_id}/attachments?client_id=${client}`)).json();expect(originals).toHaveLength(1);
  const raw=await page.request.get(`/api/agent/workflows/tasks/${tasks[0].task_id}/attachments/${originals[0].id}?client_id=${client}`);expect(await raw.body()).toEqual(photo);
  expect((await (await page.request.get(`/api/evidence/tasks?client_id=${client}`)).json())).toHaveLength(0);
 });
}
