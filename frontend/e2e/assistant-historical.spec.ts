/** DEMO_ONLY fixed clock; doses existed through normal patient APIs yesterday. */
import {test,expect} from '@playwright/test';

for(const language of ['en','zh'] as const){
 test(`independent historical report and append-only correction in ${language}`,async({page,baseURL})=>{
  expect(new URL(baseURL!).hostname).toBe('127.0.0.1');
  expect((await (await page.request.get('/api/health')).json()).database).toBe('simulated_in_memory');
  if(language==='en')await page.setViewportSize({width:1280,height:900});
  const client='DEMO-history-'+language,say=(en:string,zh:string)=>language==='zh'?zh:en;
  const session=await (await page.request.post('/api/demo/start',{data:{client_id:client}})).json();
  await page.addInitScript(({client,owner})=>{localStorage.setItem('pharmascan.client_id',client);localStorage.setItem(`pharmascan.quick-start.v4:${owner}`,JSON.stringify({version:4,status:'skipped',step:0}));},{client,owner:session.patient_id});
  let challenges=0,writes=0;
  page.on('request',request=>{if(request.method()==='POST'&&new URL(request.url()).pathname.includes('/late-report')){if(request.url().includes('/challenge'))challenges++;else writes++;}});
  await page.goto('/');
  const panel=page.getByRole('region',{name:say('Current task','当前办理任务'),exact:true});
  const composer=page.locator('.composer-row').getByRole('textbox');
  async function start(correction:boolean){
   await composer.fill(correction?say('correct a dose report','更正服药记录'):say('record a late dose','补记服药'));await composer.press('Enter');
   await panel.getByRole('button',{name:new RegExp(say('Select occurrence','选择剂次')+': DEMO historical medicine')}).click();
   await panel.getByRole('button',{name:say('Prepare historical review','准备历史核对'),exact:true}).click();
   await panel.getByRole('button',{name:say('Review historical report','核对历史自述'),exact:true}).click();
  }
  await start(false);
  expect(challenges).toBe(0);expect(writes).toBe(0);
  const sheet=page.getByRole('dialog');
  await sheet.getByRole('radio').first().check();await sheet.getByRole('combobox').selectOption('forgot_to_record');
  await sheet.getByRole('button',{name:say('Review report','核对自述'),exact:true}).click();
  await expect(sheet.getByRole('button',{name:say('Confirm report','确认记录'),exact:true})).toBeEnabled();
  expect(writes).toBe(0);await page.keyboard.press('Escape');await expect(sheet).toBeHidden();expect(writes).toBe(0);
  await panel.getByRole('button',{name:say('Review historical report','核对历史自述'),exact:true}).click();
  await sheet.getByRole('radio').first().check();await sheet.getByRole('combobox').selectOption('forgot_to_record');
  await sheet.getByRole('textbox',{name:say('Notes (optional)','备注（可选）'),exact:true}).fill('DEMO retained historical entries');
  await sheet.getByRole('button',{name:say('Review report','核对自述'),exact:true}).click();
  await expect(sheet.getByRole('button',{name:say('Confirm report','确认记录'),exact:true})).toBeEnabled();
  await page.screenshot({path:`../outputs/assistant-workflows/historical-${language}.png`,fullPage:true});
  let lost=false;
  if(language==='en')await page.route('**/api/me/doses/*/late-report?*',async route=>{const actual=await route.fetch();expect(actual.ok()).toBe(true);lost=true;await route.abort('failed');},{times:1});
  if(language==='zh')await page.route('**/api/me/doses/*/late-report?*',route=>route.abort('failed'),{times:1});
  await sheet.getByRole('button',{name:say('Confirm report','确认记录'),exact:true}).click();
  if(language==='en'){await sheet.getByRole('button',{name:'Check report result',exact:true}).click();expect(lost).toBe(true);}
  if(language==='zh'){
   await sheet.getByRole('button',{name:'核查自述结果',exact:true}).click();
   await expect(sheet.getByRole('textbox',{name:'备注（可选）',exact:true})).toHaveValue('DEMO retained historical entries');
   await expect(sheet.getByRole('combobox')).toHaveValue('forgot_to_record');
   await expect(sheet.getByRole('button',{name:'确认记录',exact:true})).toHaveCount(0);
   await sheet.getByRole('button',{name:'核对自述',exact:true}).click();
   await sheet.getByRole('button',{name:'确认记录',exact:true}).click();
  }
  await expect(panel).toContainText(say('Your historical patient report was saved.','历史患者自述已保存'));await expect(sheet).toBeHidden();expect(writes).toBe(language==='zh'?2:1);
  await start(true);
  await sheet.getByRole('radio').last().check();await sheet.getByRole('combobox').selectOption('correcting_record');
  await sheet.getByRole('button',{name:say('Review report','核对自述'),exact:true}).click();
  await sheet.getByRole('button',{name:say('Confirm report','确认记录'),exact:true}).click();
  await expect(sheet).toBeHidden();await expect(panel).toContainText(say('Your historical patient report was saved.','历史患者自述已保存'));expect(writes).toBe(language==='zh'?3:2);
  const response=await page.request.get(`/api/me/dose-follow-ups?client_id=${client}&include_reported=true`);
  const actual=(await response.json()).items.find((row:{medication_name:string;report_id:string|null})=>row.medication_name==='DEMO historical medicine'&&row.report_id);
  const audit=await (await page.request.get(`/api/me/doses/${actual.occurrence_id}/late-reports?client_id=${client}`)).json();
  expect(audit.corrections.map((row:{intake_status:string})=>row.intake_status)).toEqual(['reported_taken','unsure']);expect(audit.original).toBeNull();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 });
}
