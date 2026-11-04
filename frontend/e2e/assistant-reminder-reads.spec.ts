/** DEMO_ONLY reminder reads, native ICS downloads and non-sending device status. */
import {readFileSync} from 'node:fs';
import {test,expect} from '@playwright/test';

for(const language of ['en','zh'] as const){
 test(`reads reminders and exports a calendar without sending in ${language}`,async({page,baseURL})=>{
  test.setTimeout(90000);page.setDefaultTimeout(15000);
  expect(new URL(baseURL!).hostname).toBe('127.0.0.1');expect((await(await page.request.get('/api/health')).json()).database).toBe('simulated_in_memory');
  if(language==='en')await page.setViewportSize({width:1280,height:900});
  await page.route('**/*',route=>{const url=new URL(route.request().url());return !['http:','https:'].includes(url.protocol)||url.hostname==='127.0.0.1'?route.continue():route.abort('blockedbyclient');});
  const client=`DEMO-reminder-${crypto.randomUUID()}`,say=(en:string,zh:string)=>language==='zh'?zh:en;
  async function call(method:string,path:string,data?:unknown){const response=await page.request.fetch(`${path}${path.includes('?')?'&':'?'}client_id=${client}`,{method,...(data?{data}:{})});expect(response.ok(),await response.text()).toBe(true);return response.json();}
  const session=await call('POST','/api/demo/start',{client_id:client});await call('PUT','/api/me/preferences',{preferred_language:language,voice_enabled:false,tts_autoplay:false});
  const med=await call('POST','/api/medications/drafts',{medication_name:'DEMO reminder medicine',dose_amount:1,dose_unit:'tablet',frequency_kind:'daily',frequency_local_times:['20:00']});await call('POST',`/api/medications/drafts/${med.source_id}/review`,{field_ids:null});
  const challenge=await call('POST',`/api/medications/drafts/${med.regimen_id}/challenge?session_id=${session.session_id}`,{});await call('POST','/api/medications/activate',{regimen_id:med.regimen_id,...Object.fromEntries(['challenge_id','session_id','session_state','session_state_version'].map(key=>[key,challenge[key]]))});
  await page.addInitScript(({client,owner})=>{localStorage.setItem('pharmascan.client_id',client);localStorage.setItem(`pharmascan.quick-start.v4:${owner}`,JSON.stringify({version:4,status:'skipped',step:0}));if('Notification' in window)Notification.requestPermission=()=>{throw new Error('DEMO test forbids requesting notification permission');};},{client,owner:session.patient_id});
  let calendarReads=0,unsafeWrites=0,planReads=0;const requestBodies:string[]=[];
  page.on('request',request=>{const path=new URL(request.url()).pathname;if(path==='/api/reminders/calendar')calendarReads++;if(path==='/api/reminders/plan')planReads++;if(['POST','PATCH','PUT','DELETE'].includes(request.method())&&(/^\/api\/reminders(?:$|\/push\/(?:test|subscriptions|unsubscribe))/.test(path)||/^\/api\/(medications|doses)\//.test(path)))unsafeWrites++;if(path.includes('/api/agent/workflows/'))requestBodies.push(request.postData()??'');});
  await page.goto('/');const panel=page.getByRole('region',{name:say('Current task','当前办理任务'),exact:true});
  async function send(en:string,zh:string){const response=page.waitForResponse(row=>new URL(row.url()).pathname==='/api/agent/workflows/messages');await page.locator('.composer-row').getByRole('textbox').fill(say(en,zh));await page.locator('.composer-row').getByRole('textbox').press('Enter');return (await(await response).json()).workflow;}
  expect((await send('show my reminders','查看我的提醒')).capability_id).toBe('reminder.list');await expect(panel).toContainText('DEMO reminder medicine');expect(planReads).toBe(0);
  await panel.getByRole('button',{name:say('Next 1 day','未来 1 天'),exact:true}).click();
  const task=await send('export reminder calendar','导出提醒日历');expect(task.capability_id).toBe('reminder.calendar.export');await panel.getByRole('button',{name:say('Export Calendar','导出日历'),exact:true}).click();let dialog=page.getByRole('dialog');await dialog.getByRole('radio',{name:say('Next 90 days','未来 90 天'),exact:true}).check();await dialog.getByRole('button',{name:say('Cancel','取消'),exact:true}).click();expect(calendarReads).toBe(0);
  await panel.getByRole('button',{name:say('Export Calendar','导出日历'),exact:true}).click();dialog=page.getByRole('dialog');await dialog.getByRole('radio',{name:say('Next 90 days','未来 90 天'),exact:true}).check();
  await page.route('**/api/reminders/calendar?*',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({code:'PROVIDER_UNAVAILABLE',message:'DEMO calendar unavailable',rule_id:null})}),{times:1});await dialog.getByRole('button',{name:say('Export .ics','导出 .ics'),exact:true}).click();await expect(dialog.getByRole('alert')).toBeVisible();await expect(dialog.getByRole('radio',{name:say('Next 90 days','未来 90 天'),exact:true})).toBeChecked();
  await page.screenshot({path:`../outputs/assistant-workflows/reminder-calendar-${language}.png`,fullPage:true});
  const downloadEvent=page.waitForEvent('download');const calendarResponse=page.waitForResponse(row=>new URL(row.url()).pathname==='/api/reminders/calendar'&&row.status()===200);await dialog.getByRole('button',{name:say('Export .ics','导出 .ics'),exact:true}).click();const response=await calendarResponse;expect(response.headers()['content-type']).toContain('text/calendar');expect(new URL(response.url()).searchParams.get('range')).toBe('90');expect(response.request().headers()['x-assistant-task']).toBe(task.task_id);
  const download=await downloadEvent,bytes=readFileSync((await download.path())!).toString('utf8');expect(bytes).toContain('BEGIN:VCALENDAR');expect(bytes).toContain('DEMO reminder medicine');expect(calendarReads).toBe(2);
  expect((await call('GET',`/api/agent/workflows/tasks/${task.task_id}`)).result_ref).toBeNull();
  expect((await send('check notification status','查看通知状态')).capability_id).toBe('notification.status');await panel.getByRole('button',{name:say('Check device notification status','核查设备通知状态'),exact:true}).click();const note=panel.getByText(say('Background notifications are not configured for this application.','此应用尚未配置后台通知。'),{exact:true});await expect(note).toBeVisible();await note.scrollIntoViewIfNeeded();await page.screenshot({path:`../outputs/assistant-workflows/reminder-device-status-${language}.png`,fullPage:true});
  expect(unsafeWrites).toBe(0);expect(requestBodies.join('')).not.toContain('p256dh');expect(requestBodies.join('')).not.toContain('endpoint');expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 });
}
