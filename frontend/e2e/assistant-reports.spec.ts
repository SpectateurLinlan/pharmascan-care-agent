/** Fixed synthetic clock at20:00 SG: a real current dose, no historical backfill. */
import {test,expect} from '@playwright/test';

for(const language of ['en','zh'] as const){
 for(const prn of [false,true]){
 test(`independently confirms ${prn?'PRN':'scheduled'} patient report in ${language}`,async({page,baseURL})=>{
  expect(new URL(baseURL!).hostname).toBe('127.0.0.1');
  expect((await (await page.request.get('/api/health')).json()).database).toBe('simulated_in_memory');
  if(language==='en')await page.setViewportSize({width:1280,height:900});
  const say=(en:string,zh:string)=>language==='zh'?zh:en;
  const client=`DEMO-report-${crypto.randomUUID()}`,name=`DEMO ${prn?'PRN':'scheduled'} patient medicine`;
  const session=await (await page.request.post('/api/demo/start',{data:{client_id:client}})).json();
  await page.request.put(`/api/me/preferences?client_id=${client}`,{data:{preferred_language:language,voice_enabled:false,tts_autoplay:false}});
  const draft=await (await page.request.post(`/api/medications/drafts?client_id=${client}`,{data:{medication_name:name,dose_amount:1,dose_unit:'tablet',...(prn?{is_prn:true,food_instruction:'DEMO original PRN instructions'}:{frequency_kind:'daily',frequency_local_times:['20:00']})}})).json();
  expect((await page.request.post(`/api/medications/drafts/${draft.source_id}/review?client_id=${client}`,{data:{field_ids:null}})).ok()).toBe(true);
  const summary=await (await page.request.post(`/api/medications/drafts/${draft.regimen_id}/challenge?client_id=${client}&session_id=${session.session_id}`,{data:{}})).json();
  expect((await page.request.post(`/api/medications/activate?client_id=${client}`,{data:{regimen_id:draft.regimen_id,challenge_id:summary.challenge_id,session_id:summary.session_id,session_state:summary.session_state,session_state_version:summary.session_state_version}})).ok()).toBe(true);
  await page.addInitScript(({client,owner})=>{localStorage.setItem('pharmascan.client_id',client);localStorage.setItem(`pharmascan.quick-start.v4:${owner}`,JSON.stringify({version:4,status:'skipped',step:0}));},{client,owner:session.patient_id});
  let confirmations=0,reports=0;
  page.on('request',request=>{const path=new URL(request.url()).pathname;if(request.method()==='POST'&&/\/api\/(?:prn|doses\/[^/]+)\/report/.test(path)){if(path.endsWith('/challenge'))confirmations++;else reports++;}});
  await page.goto('/');
  const composer=page.locator('.composer-row').getByRole('textbox');
  const sent=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/agent/workflows/messages');
  await composer.fill(prn?say('record an as-needed dose','记录按需服药自述'):say('record a dose','记录服药自述'));await composer.press('Enter');
  const response=await sent;expect(response.ok(),await response.text()).toBe(true);const initial=(await response.json()).workflow;
  const panel=page.getByRole('region',{name:say('Current task','当前办理任务'),exact:true});
  await panel.getByRole('button',{name:`${say('Choose plan','选择计划')}: ${name}`,exact:true}).click();
  expect(confirmations).toBe(0);expect(reports).toBe(0);
  if(language==='zh'&&prn){
   await panel.getByRole('button',{name:'不保存本次办理',exact:true}).click();
   await expect(panel.getByRole('button',{name:'核对服药自述',exact:true})).toHaveCount(0);
   await panel.getByRole('button',{name:'保存本次任务并继续核对',exact:true}).click();
  }
  await panel.getByRole('button',{name:say('Review dose report','核对服药自述'),exact:true}).click();
  const patient=panel.getByRole('region',{name:say('Patient dose report','患者服药自述'),exact:true});
  await expect(patient.getByRole('button',{name:say('Taken','已服用'),exact:true})).toBeEnabled();
  expect(confirmations).toBe(0);expect(reports).toBe(0);
  await patient.getByRole('button',{name:say('Taken','已服用'),exact:true}).click();
  const sheet=page.getByRole('dialog',{name:say('Confirm your dose report','确认服药记录'),exact:true});
  await expect(sheet).toContainText(name);expect(reports).toBe(0);
  await sheet.getByRole('button',{name:say('Cancel','取消'),exact:true}).click();
  expect(reports).toBe(0);
  await patient.getByRole('button',{name:say('Taken','已服用'),exact:true}).click();
  await expect(sheet).toBeVisible();
  await page.screenshot({path:`../outputs/assistant-workflows/patient-report-${language}-${prn?'prn':'scheduled'}.png`,fullPage:true});
  let lost=false;
  if(language==='en'&&prn)await page.route('**/api/prn/report?*',async route=>{lost=true;const actual=await route.fetch();expect(actual.ok()).toBe(true);await route.abort('failed');},{times:1});
  await sheet.getByRole('button',{name:say('Confirm record','确认记录'),exact:true}).click();
  if(language==='en'&&prn){
   await sheet.getByRole('button',{name:'Check report result',exact:true}).click();expect(lost).toBe(true);
  }
  await expect(panel).toContainText(say('Your patient report was saved.','患者自述已保存'));
  await expect(sheet).toBeHidden();expect(reports).toBe(1);
  const state=await (await page.request.get(`/api/agent/workflows/tasks/${initial.task_id}?client_id=${client}`)).json();
  expect(state.state).toBe('completed');expect(state.result_ref.kind).toBe('dose_event');expect(state.visible_fields.ingestion_proven).toBe(false);
  const history=await page.request.get(`/api/me/dose-history?client_id=${client}&regimen_id=${draft.regimen_id}`);
  expect(history.ok()).toBe(true);const records=(await history.json()).entries;
  expect(records.filter((row:{reported:boolean})=>row.reported)).toHaveLength(1);
  expect(records.find((row:{reported:boolean})=>row.reported).intake_status).toBe('reported_taken');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 });
 }
}
