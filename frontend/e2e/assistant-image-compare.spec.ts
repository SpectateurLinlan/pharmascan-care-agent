/** DEMO_ONLY explicit image processing replay; no real provider or clinical writes. */
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {test,expect} from '@playwright/test';

for(const language of ['en','zh'] as const){
 test(`checks a retained photo explicitly without clinical writes in ${language}`,async({page,baseURL})=>{
  test.setTimeout(90000);page.setDefaultTimeout(15000);
  expect(new URL(baseURL!).hostname).toBe('127.0.0.1');expect((await(await page.request.get('/api/health')).json()).database).toBe('simulated_in_memory');
  if(language==='en')await page.setViewportSize({width:1280,height:900});
  await page.route('**/*',route=>{const url=new URL(route.request().url());return !['http:','https:'].includes(url.protocol)||url.hostname==='127.0.0.1'?route.continue():route.abort('blockedbyclient');});
  const client=`DEMO-compare-${crypto.randomUUID()}`,say=(en:string,zh:string)=>language==='zh'?zh:en;
  async function call(method:string,path:string,data?:unknown){const response=await page.request.fetch(`${path}${path.includes('?')?'&':'?'}client_id=${client}`,{method,...(data?{data}:{})});expect(response.ok(),await response.text()).toBe(true);return response.json();}
  const session=await call('POST','/api/demo/start',{client_id:client});await call('PUT','/api/me/preferences',{preferred_language:language,voice_enabled:false,tts_autoplay:false});
  await page.addInitScript(({client,owner})=>{localStorage.setItem('pharmascan.client_id',client);localStorage.setItem(`pharmascan.quick-start.v4:${owner}`,JSON.stringify({version:4,status:'skipped',step:0}));},{client,owner:session.patient_id});
  await page.goto('/');const panel=page.getByRole('region',{name:say('Current task','当前办理任务'),exact:true});let stores=0,queries=0,clinicalWrites=0;
  page.on('request',request=>{const path=new URL(request.url()).pathname;if(request.method()==='PUT'&&path.includes('/attachments/'))stores++;if(request.method()==='POST'&&path.endsWith('/compare'))queries++;if(['POST','PATCH','DELETE'].includes(request.method())&&(/^\/api\/(evidence|medications|doses)\//.test(path)||path==='/api/visual-check'))clinicalWrites++;});
  const started=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/agent/workflows/messages');
  await page.locator('.composer-row').getByRole('textbox').fill(say('compare a pill photo','比对药片照片'));await page.locator('.composer-row').getByRole('textbox').press('Enter');const task=(await(await started).json()).workflow;expect(task.capability_id).toBe('image.compare');
  await panel.getByRole('button',{name:say('Do not save this workflow','不保存本次办理'),exact:true}).click();
  const bytes=readFileSync(resolve('../tests/backend/fixtures/DEMO_workflow_photo.png'));await panel.locator('input[type="file"]').setInputFiles({name:'DEMO_check.png',mimeType:'image/png',buffer:bytes});
  const check=panel.getByRole('button',{name:say('Check photo','开始比对照片'),exact:true});await expect(check).toBeDisabled();expect(queries).toBe(0);expect(stores).toBe(0);
  await panel.getByRole('checkbox').check();await check.click();await expect(panel).toContainText(say('No eligible personal reference is available. A gallery photo alone does not establish a verified reference.','没有可用于比对的个人参考照片。保存到图库的照片不等于已验证的参考照片。'));expect(stores).toBe(0);
  await panel.getByRole('button',{name:say('Look for catalogue candidates','查找目录候选'),exact:true}).click();await expect(check).toBeDisabled();await panel.getByRole('checkbox').check();await check.click();await expect(panel).toContainText('DEMO catalogue clue');expect(queries).toBe(2);
  await panel.getByRole('button',{name:say('Save photo check draft','保存照片比对草稿'),exact:true}).click();await expect(panel).toContainText('DEMO_check.png');await expect(panel).not.toContainText('DEMO catalogue clue');
  const retained=page.waitForResponse(response=>response.request().method()==='PUT'&&new URL(response.url()).pathname.includes('/attachments/'));await panel.getByRole('button',{name:say('Save comparison original','保存比对原图'),exact:true}).click();const original=(await(await retained).json()).attachment;
  await expect(panel).toContainText(say('The comparison original is saved. Saving did not start processing.','比对原图已保存，保存操作未启动识别处理。'));expect(queries).toBe(2);expect(stores).toBe(1);
  const path=`/api/agent/workflows/tasks/${task.task_id}/attachments/${original.id}?client_id=${client}`;expect((await(await page.request.get(path)).body()).equals(bytes)).toBe(true);
  await page.reload();await page.getByRole('button',{name:say('Unfinished tasks','未完成的办理'),exact:true}).click();await page.getByRole('region',{name:say('Unfinished tasks','未完成的办理'),exact:true}).getByRole('button').last().click();
  await expect(panel).toContainText(say('The comparison original is saved. Saving did not start processing.','比对原图已保存，保存操作未启动识别处理。'));expect(queries).toBe(2);await expect(check).toBeDisabled();
  await page.route(`**/api/agent/workflows/tasks/${task.task_id}/compare?*`,route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({code:'PROVIDER_UNAVAILABLE',message:'DEMO processing unavailable',rule_id:null})}),{times:1});
  await panel.getByRole('checkbox').check();await check.click();await expect(panel.getByRole('alert')).toBeVisible();expect((await(await page.request.get(path)).body()).equals(bytes)).toBe(true);expect(queries).toBe(3);
  await check.click();await expect(panel).toContainText('DEMO catalogue clue');expect(queries).toBe(4);await expect(panel).not.toContainText('0.99');
  const limits=panel.getByText(say('Results stay on this page. Reopening the task requires another explicit check.','结果仅留在当前页面，重新打开办理任务后需明确发起新的比对。'),{exact:true});
  await limits.scrollIntoViewIfNeeded();await expect(limits).toBeVisible();await expect(panel.getByText(/DEMO catalogue clue/)).toBeVisible();
  await page.screenshot({path:`../outputs/assistant-workflows/image-compare-${language}.png`,fullPage:true});
  const view=await call('GET',`/api/agent/workflows/tasks/${task.task_id}`);expect(view.result_ref).toBeNull();expect(JSON.stringify(view)).not.toContain('DEMO catalogue clue');expect(clinicalWrites).toBe(0);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 });
}
