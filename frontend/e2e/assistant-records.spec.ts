/** Local DEMO records only; no model/provider/SQL/device acceptance. */
import {test,expect} from '@playwright/test';

for(const language of ['en','zh'] as const){
 test(`queries actual patient records, sources and summaries in ${language}`,async({page,baseURL})=>{
  expect(new URL(baseURL!).hostname).toBe('127.0.0.1');
  expect((await (await page.request.get('/api/health')).json()).database).toBe('simulated_in_memory');
  if(language==='en')await page.setViewportSize({width:1280,height:900});
  const say=(en:string,zh:string)=>language==='zh'?zh:en;
  const client=`DEMO-records-${crypto.randomUUID()}`;
  const session=await (await page.request.post('/api/demo/start',{data:{client_id:client}})).json();
  await page.request.put(`/api/me/preferences?client_id=${client}`,{data:{preferred_language:language,conversation_history_enabled:true,voice_enabled:false,tts_autoplay:false}});
  const draft=await (await page.request.post(`/api/medications/drafts?client_id=${client}`,{data:{medication_name:'DEMO recorded PRN',dose_amount:1,dose_unit:'tablet',is_prn:true,food_instruction:'DEMO original PRN instructions'}})).json();
  expect((await page.request.post(`/api/medications/drafts/${draft.source_id}/review?client_id=${client}`,{data:{field_ids:null}})).ok()).toBe(true);
  const activation=await (await page.request.post(`/api/medications/drafts/${draft.regimen_id}/challenge?client_id=${client}&session_id=${session.session_id}`,{data:{}})).json();
  expect((await page.request.post(`/api/medications/activate?client_id=${client}`,{data:{regimen_id:draft.regimen_id,challenge_id:activation.challenge_id,session_id:activation.session_id,session_state:activation.session_state,session_state_version:activation.session_state_version}})).ok()).toBe(true);
  const report={regimen_id:draft.regimen_id,intake_status:'taken',idempotency_key:`DEMO-${crypto.randomUUID()}`};
  const confirmation=await (await page.request.post(`/api/prn/report/challenge?client_id=${client}`,{data:report})).json();
  expect((await page.request.post(`/api/prn/report?client_id=${client}`,{data:{...report,challenge_id:confirmation.challenge_id}})).ok()).toBe(true);
  const original=await page.request.get(`/api/me/dose-history?client_id=${client}&regimen_id=${draft.regimen_id}`);
  expect(original.ok(),await original.text()).toBe(true);
  const before=await original.json();expect(before.entries).toHaveLength(1);
  await page.addInitScript(({client,owner})=>{localStorage.setItem('pharmascan.client_id',client);localStorage.setItem(`pharmascan.quick-start.v4:${owner}`,JSON.stringify({version:4,status:'skipped',step:0}));},{client,owner:session.patient_id});
  await page.goto('/');
  const composer=page.locator('.composer-row').getByRole('textbox');
  const panel=page.getByRole('region',{name:say('Current task','当前办理任务'),exact:true});
  const writes:string[]=[];page.on('request',request=>{if(request.method()==='POST'&&/\/api\/(?:prn|doses|medications)\//.test(new URL(request.url()).pathname))writes.push(request.url());});
  for(const [en,zh,key] of [
   ["show today's medicines",'查看今日用药','medication.today'],['show due doses','查看待自述剂次','medication.due'],
   ['show record catalogue','查看记录目录','record.catalogue'],['show medication history','查看用药历史','medication.history'],
   ['check medication status','查看服药状态','medication.status'],['view medication sources','查看药物原始来源','medication.source.view'],
   ['show my medication instructions','查看我的服药说明','medication.instructions'],
   ['show weekly medication summary','查看本周用药统计','record.summary'],['prepare for my visit','准备复诊','record.visit.prepare'],
   ['show medication records','查看服药记录','record.history'],
  ] as const){
   const sent=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/agent/workflows/messages');
   await composer.fill(say(en,zh));await composer.press('Enter');
   const response=await sent;expect(response.ok(),await response.text()).toBe(true);
   let view=(await response.json()).workflow;expect(view.capability_id).toBe(key);
   if(view.missing_fields.includes('medication_id')){
    await panel.getByRole('button',{name:`${say('View record','查看记录')}: DEMO recorded PRN`,exact:true}).click();
    await expect(panel.getByRole('heading',{name:'DEMO recorded PRN',level:3,exact:true})).toBeVisible();
   }
   await expect(panel).toContainText('DEMO recorded PRN');
   expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
   expect(await panel.getByRole('button',{name:/^Confirm record$|^确认记录$|^Review this medication$/}).count()).toBe(0);
   if(key==='medication.source.view')await expect(panel).toContainText('DEMO original PRN instructions');
   if(key==='record.summary'){
    const selection=panel.getByRole('combobox',{name:say('Summary period','统计范围')});
    await selection.selectOption('month');await panel.getByRole('button',{name:say('Apply record filters','应用记录筛选'),exact:true}).click();
    await expect(selection).toHaveValue('month');
   }
   if(key==='record.history'){
    const selection=panel.getByRole('combobox',{name:say('History range','历史范围')});
    await selection.selectOption('7');
    await panel.getByRole('button',{name:say('Apply record filters','应用记录筛选'),exact:true}).click();
    await expect(panel.getByRole('button',{name:say('Apply record filters','应用记录筛选'),exact:true})).toBeDisabled();
    await expect(panel).toContainText(say('Patient reported taken','患者自述已服用'));
    await page.screenshot({path:`../outputs/assistant-workflows/records-query-${language}.png`,fullPage:true});
   }
  }
  expect(writes).toEqual([]);
  expect(await (await page.request.get(`/api/me/dose-history?client_id=${client}&regimen_id=${draft.regimen_id}`)).json()).toEqual(before);
 });
}
