/** Loopback DEMO only: real APIs, no external model/provider/database. */
import {test,expect} from '@playwright/test';

for(const language of ['en','zh'] as const){
 for(const noSave of [false,true]){
 test(`changes recorded plan in ${language}${noSave?' without saving':' with independent activation'}`,async({page,baseURL})=>{
  expect(new URL(baseURL!).hostname).toBe('127.0.0.1');
  expect((await (await page.request.get('/api/health')).json()).database).toBe('simulated_in_memory');
  if(language==='en')await page.setViewportSize({width:1280,height:900});
  const say=(en:string,zh:string)=>language==='zh'?zh:en;
  const client=`DEMO-plan-change-${language}-${crypto.randomUUID()}`;
  const session=await (await page.request.post('/api/demo/start',{data:{client_id:client}})).json();
  await page.request.put(`/api/me/preferences?client_id=${client}`,{data:{preferred_language:language,conversation_history_enabled:true,voice_enabled:false,tts_autoplay:false}});
  const draft=await (await page.request.post(`/api/medications/drafts?client_id=${client}`,{data:{medication_name:'DEMO recorded product',dose_amount:1,dose_unit:'tablet',frequency_kind:'daily',frequency_local_times:['20:00']}})).json();
  expect((await page.request.post(`/api/medications/drafts/${draft.source_id}/review?client_id=${client}`,{data:{field_ids:null}})).ok()).toBe(true);
  const summary=await (await page.request.post(`/api/medications/drafts/${draft.regimen_id}/challenge?client_id=${client}&session_id=${session.session_id}`,{data:{}})).json();
  expect((await page.request.post(`/api/medications/activate?client_id=${client}`,{data:{regimen_id:draft.regimen_id,challenge_id:summary.challenge_id,session_id:summary.session_id,session_state:summary.session_state,session_state_version:summary.session_state_version}})).ok()).toBe(true);
  const before=await (await page.request.get(`/api/me/regimens?client_id=${client}`)).json();
  await page.addInitScript(({client,owner})=>{localStorage.setItem('pharmascan.client_id',client);localStorage.setItem(`pharmascan.quick-start.v4:${owner}`,JSON.stringify({version:4,status:'skipped',step:0}));},{client,owner:session.patient_id});
  await page.goto('/');
  const composer=page.locator('.composer-row').getByRole('textbox');
  await composer.fill(say('change a medication plan','修改用药计划'));await composer.press('Enter');
  const panel=page.getByRole('region',{name:say('Current task','当前办理任务'),exact:true});
  await panel.getByRole('button',{name:new RegExp(`^${say('Choose plan','选择计划')}: DEMO recorded product`)}).click();
  await expect(panel.getByRole('textbox',{name:say('Medication name','药物名称')})).toHaveAttribute('readonly','');
  if(noSave)await panel.getByRole('button',{name:say('Do not save this workflow','不保存本次办理'),exact:true}).click();
  const sent=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/agent/workflows/messages');
  await composer.fill(say('dose: 2 tablets; 21:00','每次2片；21:00'));await composer.press('Enter');
  const collected=await sent;expect(collected.ok(),await collected.text()).toBe(true);
  const workflow=(await collected.json()).workflow;expect(workflow.state).toBe('ready_for_review');
  expect(workflow.input_fields.details.frequency_rule.local_times).toEqual(['21:00']);
  expect(await (await page.request.get(`/api/me/regimens?client_id=${client}`)).json()).toEqual(before);
  await expect(panel.getByRole('region',{name:say('Original recorded plan','原登记计划')})).toContainText('20:00');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  if(noSave){
   await expect(panel.getByRole('button',{name:say('Review this medication','核对这项药物'),exact:true})).toHaveCount(0);
   const list=await (await page.request.get(`/api/agent/workflows/tasks?client_id=${client}`)).json();
   expect(list.some((row:{task_id:string})=>row.task_id===workflow.task_id)).toBe(false);
   await panel.getByRole('button',{name:say('Save this task and continue review','保存本次任务并继续核对'),exact:true}).click();
   await expect(panel.getByRole('button',{name:say('Review this medication','核对这项药物'),exact:true})).toBeVisible();
   expect(await (await page.request.get(`/api/me/regimens?client_id=${client}`)).json()).toEqual(before);
   return;
  }
  await panel.getByRole('region',{name:say('Original recorded plan','原登记计划')}).scrollIntoViewIfNeeded();
  await page.screenshot({path:`../outputs/assistant-workflows/plan-change-input-${language}.png`,fullPage:true});
  let lost=false;
  if(language==='en')await page.route('**/api/agent/workflows/tasks/*/events*',async route=>{
   const body=route.request().postDataJSON();if(body.kind!=='prepare_confirmation'||lost){await route.continue();return;}
   lost=true;const actual=await route.fetch();expect(actual.ok()).toBe(true);await route.abort('failed');
  });
  await panel.getByRole('button',{name:say('Review this medication','核对这项药物'),exact:true}).click();
  if(language==='en'){
   await expect(page.getByRole('alert')).toBeVisible();
   await panel.getByRole('button',{name:'Check task status',exact:true}).click();expect(lost).toBe(true);
  }
  await expect(panel.getByRole('checkbox',{name:say('I have checked these details against my original instructions.','我已对照原始服用说明核对过以上内容。')})).toBeVisible();
  const prepared=await (await page.request.get(`/api/me/regimens?client_id=${client}`)).json();expect(prepared).toHaveLength(2);
  expect(prepared.find((row:{regimen_id:string})=>row.regimen_id===draft.regimen_id)).toEqual(before[0]);
  await composer.fill(say('resume a medication draft','继续药物草稿'));await composer.press('Enter');
  await panel.getByRole('button',{name:new RegExp(`^${say('Choose draft','选择草稿')}: DEMO recorded product`)}).click();
  const resuming=page.waitForResponse(response=>/\/api\/agent\/workflows\/tasks\/[^/]+\/resume-draft$/.test(new URL(response.url()).pathname));
  await panel.getByRole('button',{name:say('Continue original enrollment','继续原登记任务'),exact:true}).click();
  const resumed=await resuming;expect(resumed.ok(),await resumed.text()).toBe(true);
  const restored=await (await page.request.get(`/api/agent/workflows/tasks/${workflow.task_id}?client_id=${client}`)).json();
  expect(restored.capability_id).toBe('medication.plan.change');expect(restored.state).toBe('awaiting_confirmation');
  await panel.getByRole('checkbox',{name:say('I have checked these details against my original instructions.','我已对照原始服用说明核对过以上内容。')}).check();
  const identity=panel.getByRole('checkbox',{name:say('I checked the original medication name against its source.','我已对照来源核对原记录中的药物名称。')});
  if(await identity.count())await identity.check();
  await page.screenshot({path:`../outputs/assistant-workflows/plan-change-review-${language}.png`,fullPage:true});
  await panel.getByRole('button',{name:say('Add this medication','添加此药物'),exact:true}).click();
  expect((await (await page.request.get(`/api/me/regimens?client_id=${client}`)).json()).find((row:{regimen_id:string})=>row.regimen_id===draft.regimen_id).state).toBe('active');
  const activation=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/medications/activate');
  await page.getByRole('button',{name:say('Yes, save this medication','确认：激活此用药计划'),exact:true}).click();
  const activated=await activation;expect(activated.ok(),await activated.text()).toBe(true);
  await expect(panel).toContainText(say('The medication plan is active.','药物计划已启用。'));
  const after=await (await page.request.get(`/api/me/regimens?client_id=${client}`)).json();
  expect(after.find((row:{regimen_id:string})=>row.regimen_id===draft.regimen_id).state).toBe('superseded');
  const active=after.find((row:{state:string})=>row.state==='active');
  expect(active.dose_amount).toBe(2);expect(active.frequency_rule.local_times).toEqual(['21:00']);
  expect(after.filter((row:{state:string})=>row.state==='active')).toHaveLength(1);
 });
 }
}
