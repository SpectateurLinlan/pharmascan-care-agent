/** DEMO_ONLY actual retained source photos and explicit local label replay. */
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {test,expect} from '@playwright/test';

for(const language of ['en','zh'] as const){
 test(`previews a source explicitly without clinical saving in ${language}`,async({page,baseURL})=>{
  test.setTimeout(90000);page.setDefaultTimeout(15000);
  expect(new URL(baseURL!).hostname).toBe('127.0.0.1');expect((await(await page.request.get('/api/health')).json()).database).toBe('simulated_in_memory');
  if(language==='en')await page.setViewportSize({width:1280,height:900});
  await page.route('**/*',route=>{const url=new URL(route.request().url());return !['http:','https:'].includes(url.protocol)||url.hostname==='127.0.0.1'?route.continue():route.abort('blockedbyclient');});
  const client=`DEMO-source-preview-${crypto.randomUUID()}`,say=(en:string,zh:string)=>language==='zh'?zh:en;
  async function call(method:string,path:string,data?:unknown){const response=await page.request.fetch(`${path}${path.includes('?')?'&':'?'}client_id=${client}`,{method,...(data?{data}:{})});expect(response.ok(),await response.text()).toBe(true);return response.json();}
  const session=await call('POST','/api/demo/start',{client_id:client});await call('PUT','/api/me/preferences',{preferred_language:language,voice_enabled:false,tts_autoplay:false});
  await page.addInitScript(({client,owner})=>{localStorage.setItem('pharmascan.client_id',client);localStorage.setItem(`pharmascan.quick-start.v4:${owner}`,JSON.stringify({version:4,status:'skipped',step:0}));},{client,owner:session.patient_id});
  await page.goto('/');const panel=page.getByRole('region',{name:say('Current task','当前办理任务'),exact:true});let stores=0,reads=0,patientWrites=0;
  page.on('request',request=>{const path=new URL(request.url()).pathname;if(request.method()==='PUT'&&path.includes('/attachments/'))stores++;if(request.method()==='POST'&&path.endsWith('/source-preview'))reads++;if(['POST','PATCH','DELETE'].includes(request.method())&&/^\/api\/(evidence|medications|doses)\//.test(path))patientWrites++;});
  const started=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/agent/workflows/messages');await page.locator('.composer-row').getByRole('textbox').fill(say('preview a medication label','预览药物标签'));await page.locator('.composer-row').getByRole('textbox').press('Enter');const task=(await(await started).json()).workflow;expect(task.capability_id).toBe('source.preview');
  await panel.getByRole('button',{name:say('Do not save this workflow','不保存本次办理'),exact:true}).click();
  const bytes=readFileSync(resolve('../tests/backend/fixtures/DEMO_workflow_photo.png'));await panel.locator('input[type="file"]').setInputFiles({name:'DEMO_source.png',mimeType:'image/png',buffer:bytes});
  await panel.getByRole('button',{name:say('Prescription','处方'),exact:true}).click();await panel.getByRole('button',{name:say('Pharmacy label','药房标签'),exact:true}).click();await expect(panel).toContainText('DEMO_source.png');
  const preview=panel.getByRole('button',{name:say('Preview source','预览来源'),exact:true});await expect(preview).toBeDisabled();expect(stores).toBe(0);expect(reads).toBe(0);await panel.getByRole('checkbox').check();await preview.click();
  await expect(panel.getByRole('heading',{name:'DEMO Photo medicine',exact:true})).toBeVisible();expect(reads).toBe(1);expect(stores).toBe(0);
  await panel.getByRole('button',{name:say('Save source preview draft','保存来源预览草稿'),exact:true}).click();await expect(panel).toContainText('DEMO_source.png');await expect(panel.getByRole('heading',{name:'DEMO Photo medicine',exact:true})).toHaveCount(0);
  const retained=page.waitForResponse(response=>response.request().method()==='PUT'&&new URL(response.url()).pathname.includes('/attachments/'));await panel.getByRole('button',{name:say('Save preview original','保存预览原图'),exact:true}).click();const original=(await(await retained).json()).attachment;expect(original.extraction_status).toBe('not_requested');
  await expect(panel).toContainText(say('The preview original is saved. Saving did not start extraction.','预览原图已保存，保存操作未启动提取。'));expect(reads).toBe(1);expect(stores).toBe(1);
  const path=`/api/agent/workflows/tasks/${task.task_id}/attachments/${original.id}?client_id=${client}`;expect((await(await page.request.get(path)).body()).equals(bytes)).toBe(true);
  await page.reload();await page.getByRole('button',{name:say('Unfinished tasks','未完成的办理'),exact:true}).click();await page.getByRole('region',{name:say('Unfinished tasks','未完成的办理'),exact:true}).getByRole('button').last().click();await expect(panel).toContainText(say('The preview original is saved. Saving did not start extraction.','预览原图已保存，保存操作未启动提取。'));expect(reads).toBe(1);await expect(preview).toBeDisabled();
  await page.route(`**/api/agent/workflows/tasks/${task.task_id}/source-preview?*`,route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({code:'PROVIDER_UNAVAILABLE',message:'DEMO source read unavailable',rule_id:null})}),{times:1});await panel.getByRole('checkbox').check();await preview.click();await expect(panel.getByRole('alert')).toBeVisible();expect(reads).toBe(2);expect((await(await page.request.get(path)).body()).equals(bytes)).toBe(true);
  await preview.click();await expect(panel.getByRole('heading',{name:'DEMO Photo medicine',exact:true})).toBeVisible();expect(reads).toBe(3);
  const lines=panel.locator('details').filter({has:page.locator('summary').filter({hasText:say('Original source lines','原始来源文字')})});await lines.locator('summary').click();await expect(lines).toContainText('DEMO Photo medicine 200mg');await lines.scrollIntoViewIfNeeded();await expect(lines).toBeVisible();
  const limit=panel.getByText(say('Preview results stay on this page. Reopening the task requires another explicit read.','预览结果仅留在当前页面，重新打开任务后需明确发起新的读取。'),{exact:true});await limit.scrollIntoViewIfNeeded();await expect(limit).toBeVisible();
  await page.screenshot({path:`../outputs/assistant-workflows/source-preview-${language}.png`,fullPage:true});
  const view=await call('GET',`/api/agent/workflows/tasks/${task.task_id}`);expect(view.result_ref).toBeNull();expect(JSON.stringify(view)).not.toContain('DEMO Photo medicine');const metadata=await call('GET',`/api/agent/workflows/tasks/${task.task_id}/attachments`);expect(metadata[0].extraction_status).toBe('not_requested');expect(patientWrites).toBe(0);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 });
}
