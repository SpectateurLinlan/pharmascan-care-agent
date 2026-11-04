/** DEMO_ONLY real memory patient writes; no permission or notification delivery. */
import {test,expect} from '@playwright/test';

for(const language of ['en','zh'] as const){
 test(`independently confirms reminder changes without duplicate snoozes in ${language}`,async({page,baseURL})=>{
  test.setTimeout(90000);page.setDefaultTimeout(15000);
  expect(new URL(baseURL!).hostname).toBe('127.0.0.1');expect((await(await page.request.get('/api/health')).json()).database).toBe('simulated_in_memory');
  if(language==='en')await page.setViewportSize({width:1280,height:900});
  await page.route('**/*',route=>{const url=new URL(route.request().url());return !['http:','https:'].includes(url.protocol)||url.hostname==='127.0.0.1'?route.continue():route.abort('blockedbyclient');});
  const client=`DEMO-reminder-change-${crypto.randomUUID()}`,say=(en:string,zh:string)=>language==='zh'?zh:en;
  async function call(method:string,path:string,data?:unknown){const response=await page.request.fetch(`${path}${path.includes('?')?'&':'?'}client_id=${client}`,{method,...(data?{data}:{})});expect(response.ok(),await response.text()).toBe(true);return response.json();}
  const session=await call('POST','/api/demo/start',{client_id:client});await call('PUT','/api/me/preferences',{preferred_language:language,voice_enabled:false,tts_autoplay:false});
  const med=await call('POST','/api/medications/drafts',{medication_name:'DEMO reminder change medicine',dose_amount:1,dose_unit:'tablet',frequency_kind:'daily',frequency_local_times:['21:00']});await call('POST',`/api/medications/drafts/${med.source_id}/review`,{field_ids:null});
  const challenge=await call('POST',`/api/medications/drafts/${med.regimen_id}/challenge?session_id=${session.session_id}`,{});await call('POST','/api/medications/activate',{regimen_id:med.regimen_id,...Object.fromEntries(['challenge_id','session_id','session_state','session_state_version'].map(key=>[key,challenge[key]]))});
  // Fixture setup explicitly materializes an existing dose before the observed Assistant journey.
  const plan=await call('GET','/api/reminders/plan');expect(plan.length).toBeGreaterThan(0);
  const beforeRegimens=await call('GET','/api/me/regimens');
  await page.addInitScript(({client,owner})=>{localStorage.setItem('pharmascan.client_id',client);localStorage.setItem(`pharmascan.quick-start.v4:${owner}`,JSON.stringify({version:4,status:'skipped',step:0}));if('Notification' in window)Notification.requestPermission=()=>{throw new Error('DEMO test forbids notification permission');};},{client,owner:session.patient_id});
  let settingsWrites=0,snoozeWrites=0,clinicalWrites=0;const taskBodies:string[]=[];
  page.on('request',request=>{const path=new URL(request.url()).pathname;if(request.method()==='PUT'&&path==='/api/me/preferences')settingsWrites++;if(request.method()==='POST'&&path==='/api/reminders')snoozeWrites++;if(request.method()!=='GET'&&/^\/api\/(medications|doses|prn|sources)/.test(path))clinicalWrites++;if(path.includes('/api/agent/workflows'))taskBodies.push(request.postData()??'');});
  await page.goto('/');const panel=page.getByRole('region',{name:say('Current task','当前办理任务'),exact:true});
  async function send(en:string,zh:string){const response=page.waitForResponse(row=>new URL(row.url()).pathname==='/api/agent/workflows/messages');await page.locator('.composer-row').getByRole('textbox').fill(say(en,zh));await page.locator('.composer-row').getByRole('textbox').press('Enter');return (await(await response).json()).workflow;}
  await send('change reminder settings','修改提醒设置');await panel.getByRole('checkbox',{name:say('Medication Reminders','定时用药提醒'),exact:true}).uncheck();await panel.getByRole('combobox',{name:say('Reminder Lead Time','用药提醒提前时间'),exact:true}).selectOption('30');
  expect(settingsWrites).toBe(0);await panel.getByRole('button',{name:say('Apply reminder details','使用提醒资料'),exact:true}).click();await panel.getByRole('button',{name:say('Prepare reminder review','准备提醒核对'),exact:true}).click();await panel.getByRole('button',{name:say('Review reminder change','核对提醒变更'),exact:true}).click();
  let dialog=page.getByRole('dialog');await expect(dialog).toContainText('30');await dialog.getByRole('button',{name:say('Cancel','取消'),exact:true}).click();expect(settingsWrites).toBe(0);
  await panel.getByRole('button',{name:say('Review reminder change','核对提醒变更'),exact:true}).click();
  await page.route('**/api/me/preferences?*',route=>route.request().method()==='PUT'?route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({code:'PROVIDER_UNAVAILABLE',message:'DEMO preference unavailable',rule_id:null})}):route.continue(),{times:1});
  await page.getByRole('dialog').getByRole('button',{name:say('Confirm reminder change','确认提醒变更'),exact:true}).click();await expect(page.getByRole('dialog').getByRole('alert')).toBeVisible();
  await page.getByRole('dialog').getByRole('button',{name:say('Check reminder result','核查提醒结果'),exact:true}).click();
  await panel.getByRole('button',{name:say('Edit reminder details','修改提醒资料'),exact:true}).click();await panel.getByRole('combobox',{name:say('Reminder Lead Time','用药提醒提前时间'),exact:true}).selectOption('60');await panel.getByRole('button',{name:say('Apply reminder details','使用提醒资料'),exact:true}).click();
  await panel.getByRole('button',{name:say('Prepare reminder review','准备提醒核对'),exact:true}).click();await panel.getByRole('button',{name:say('Review reminder change','核对提醒变更'),exact:true}).click();await page.screenshot({path:`../outputs/assistant-workflows/reminder-settings-review-${language}.png`,fullPage:true});
  await page.getByRole('dialog').getByRole('button',{name:say('Confirm reminder change','确认提醒变更'),exact:true}).click();await expect(panel).toContainText(say('The earlier reminder change was saved. Current settings are shown below.','此前的提醒变更已保存，以下显示当前设置。'));
  const preferences=await call('GET','/api/me/preferences');expect(preferences.reminders_enabled).toBe(false);expect(preferences.reminder_lead_minutes).toBe(60);expect(settingsWrites).toBe(2);
  await send('snooze a reminder','稍后提醒我');await panel.getByRole('button',{name:/DEMO reminder change medicine/}).click();await panel.getByLabel(say('Minutes later','延后分钟数'),{exact:true}).fill('30');await panel.getByRole('button',{name:say('Apply reminder details','使用提醒资料'),exact:true}).click();await panel.getByRole('button',{name:say('Prepare reminder review','准备提醒核对'),exact:true}).click();await panel.getByRole('button',{name:say('Review reminder change','核对提醒变更'),exact:true}).click();dialog=page.getByRole('dialog');await expect(dialog).toContainText('DEMO reminder change medicine');expect(snoozeWrites).toBe(0);await page.screenshot({path:`../outputs/assistant-workflows/reminder-snooze-review-${language}.png`,fullPage:true});
  let actualTime='';await page.route('**/api/reminders?*',async route=>{if(route.request().method()!=='POST')return route.continue();const response=await route.fetch();expect(response.status()).toBe(200);actualTime=(await response.json()).remind_at;await route.abort('connectionfailed');},{times:1});
  await dialog.getByRole('button',{name:say('Confirm reminder change','确认提醒变更'),exact:true}).click();await expect(dialog.getByRole('alert')).toBeVisible();expect(snoozeWrites).toBe(1);await dialog.getByRole('button',{name:say('Check reminder result','核查提醒结果'),exact:true}).click();await expect(panel).toContainText(say('Current saved snooze','当前保存的稍后提醒'));
  expect((await call('GET','/api/reminders'))[0].remind_at).toBe(actualTime);expect(snoozeWrites).toBe(1);expect(clinicalWrites).toBe(0);expect(await call('GET','/api/me/regimens')).toEqual(beforeRegimens);expect(taskBodies.join('')).not.toContain('p256dh');expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 });
}
