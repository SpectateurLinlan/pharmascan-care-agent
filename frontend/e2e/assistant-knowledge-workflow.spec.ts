/** Explicit general knowledge workflow; public label replay, no live provider. */
import {test,expect} from '@playwright/test';

for(const language of ['en','zh'] as const){
 test(`explicit sourced knowledge, case and confirmed typo in ${language}`,async({page,baseURL})=>{
  expect(new URL(baseURL!).hostname).toBe('127.0.0.1');
  expect((await (await page.request.get('/api/health')).json()).database).toBe('simulated_in_memory');
  if(language==='en')await page.setViewportSize({width:1280,height:900});
  const say=(en:string,zh:string)=>language==='zh'?zh:en,client=`DEMO-knowledge-flow-${crypto.randomUUID()}`;
  const session=await (await page.request.post('/api/demo/start',{data:{client_id:client}})).json();
  expect((await page.request.put(`/api/me/preferences?client_id=${client}`,{data:{preferred_language:language,voice_enabled:false,tts_autoplay:false}})).ok()).toBe(true);
  await page.addInitScript(({client,owner})=>{localStorage.setItem('pharmascan.client_id',client);localStorage.setItem(`pharmascan.quick-start.v4:${owner}`,JSON.stringify({version:4,status:'skipped',step:0}));},{client,owner:session.patient_id});
  let lookups=0;page.on('request',request=>{if(request.method()==='POST'&&/\/tasks\/[^/]+\/knowledge$/.test(new URL(request.url()).pathname))lookups++;});
  await page.goto('/');const composer=page.locator('.composer-row').getByRole('textbox');
  await composer.fill(say('look up a medicine','查询药物知识'));await composer.press('Enter');
  const panel=page.getByRole('region',{name:say('Current task','当前办理任务'),exact:true});
  const query=panel.getByRole('region',{name:say('Medication knowledge query','药物知识查询'),exact:true});
  const input=query.getByRole('textbox',{name:say('Medicine name','药物名称'),exact:true});
  await input.fill('IbUpRoFeN');await query.getByRole('button',{name:say('Apply medicine name','使用此药名'),exact:true}).click();
  const search=query.getByRole('button',{name:say('Search medication knowledge','查询药物知识'),exact:true});
  await expect(search).toBeEnabled();expect(lookups).toBe(0);
  await search.click();await expect(query.locator('.answer-sources')).toBeVisible();expect(lookups).toBe(1);
  await query.locator('.answer-sources>summary').click();const source=query.locator('.answer-sources a').first();await source.scrollIntoViewIfNeeded();await expect(source).toBeVisible();await expect(source).toHaveAttribute('href',/^https:\/\/dailymed\.nlm\.nih\.gov\//);
  await expect(query).toContainText(say('Searched openFDA / SPL','查询了 openFDA / SPL'));
  await page.screenshot({path:`../outputs/assistant-workflows/knowledge-workflow-${language}.png`,fullPage:true});
  if(language==='zh'){
   await panel.getByRole('button',{name:'不保存本次办理',exact:true}).click();
   await expect(query.locator('.answer-sources')).toHaveCount(0);
  }
  await input.fill(say('ibuprofne','布洛分'));await query.getByRole('button',{name:say('Apply medicine name','使用此药名'),exact:true}).click();
  const candidate=query.getByRole('button',{name:say('Use IBUPROFEN and search','确认 IBUPROFEN 并查询'),exact:true});
  await expect(candidate).toBeEnabled();expect(lookups).toBe(1);
  const response=page.waitForResponse(row=>/\/tasks\/[^/]+\/knowledge$/.test(new URL(row.url()).pathname));
  await candidate.click();const result=await response;expect(result.ok(),await result.text()).toBe(true);
  if(language==='zh')expect(result.request().postDataJSON().ephemeral).toEqual({capability_id:'medication.knowledge',fields:{medication_name:'布洛分'}});
  const body=await result.json();expect(body.general_knowledge.status).toBe('matched');expect(body.general_knowledge.personal_dosing_authority).toBe(false);
  await expect(query.locator('.answer-sources')).toBeVisible();expect(lookups).toBe(2);
  const tasks=await (await page.request.get(`/api/agent/workflows/tasks?client_id=${client}`)).json();
  expect(JSON.stringify(tasks)).not.toContain('general_knowledge');expect(JSON.stringify(tasks)).not.toContain('use_facts');
  expect((await (await page.request.get(`/api/me/medications?client_id=${client}`)).json()).medications).toEqual([]);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 });
}
