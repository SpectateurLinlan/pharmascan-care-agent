/** Real Chromium/React. Synthetic Auth/HTTP for clocks; synthetic FastAPI for tasks. */
import {expect,test} from '@playwright/test';
import {mockPatientApp} from './polish-a1-fixture';

test('a second tab suppresses an owned reminder and a failed snooze does not record intake',async({page,context})=>{
 const start=new Date('2026-10-19T00:00:00Z');
 const row={key:'DEMO-tabs:original',occurrence_id:'DEMO-tabs',regimen_id:'DEMO-plan',medication_name:'DEMO synthetic reminder',dose_amount:1,dose_unit:'tablet',food_instruction:null,due_at:start.toISOString(),remind_at:start.toISOString(),expires_at:'2026-10-19T02:00:00Z'};
 const setup=async(target:typeof page)=>{
  const mock=await mockPatientApp(target);mock.prefs.reminders_enabled=true;
  await target.clock.install({time:start});
  await target.route(url=>new URL(url).pathname==='/api/reminders/alerts',route=>route.fulfill({json:[row]}));
  await target.route(url=>new URL(url).pathname==='/api/reminders',route=>route.fulfill({status:503,json:{code:'PROVIDER_UNAVAILABLE',message:'DEMO reminder service unavailable',rule_id:null}}));
  return mock;
 };
 const first=await setup(page);await page.goto('/#today');await expect(page.getByRole('dialog',{name:'Medication reminder'})).toBeVisible();
 await page.getByRole('button',{name:'15 min later'}).click();await expect(page.getByRole('dialog')).toBeVisible();
 await expect(page.getByRole('status').filter({hasText:'DEMO reminder service unavailable'})).toBeVisible();
 const other=await context.newPage();const second=await setup(other);await other.goto('/#today');
 await expect(other.getByRole('heading',{name:'MediThread Assistant'})).toBeVisible();await other.clock.fastForward(15000);
 await expect(other.getByRole('dialog',{name:'Medication reminder'})).toHaveCount(0);
 expect([...first.writes,...second.writes].some(path=>path.includes('dose-events'))).toBe(false);
 await other.close();
});

for(const minutes of [15,30]){
 test(`snooze ${minutes} survives stale polling, reload and original expiry`,async({page})=>{
  const mock=await mockPatientApp(page);mock.prefs.reminders_enabled=true;
  await page.route(url=>new URL(url).pathname.endsWith('/auth/v1/token'),route=>route.fulfill({json:{access_token:'DEMO.synthetic-session-token',refresh_token:'DEMO.refresh',token_type:'bearer',expires_in:3600,user:{id:'d00d0000-0000-4000-8000-000000000001',aud:'authenticated',role:'authenticated',is_anonymous:true,app_metadata:{provider:'anonymous',providers:['anonymous']},user_metadata:{demo_only:true},created_at:'2026-10-16T00:00:00Z'}}}));
  const start=Date.parse('2026-10-19T00:00:00Z');let now=start,until=start;
  await page.clock.install({time:new Date(start)});
  const original={key:'DEMO-occ:original',occurrence_id:'DEMO-occ',regimen_id:'DEMO-plan',medication_name:'DEMO synthetic reminder',dose_amount:1,dose_unit:'tablet',food_instruction:null,due_at:new Date(start).toISOString(),remind_at:new Date(start).toISOString(),expires_at:new Date(start+2*3600000).toISOString()};
  await page.route(url=>new URL(url).pathname==='/api/reminders/alerts',route=>route.fulfill({json:[now<until?original:{...original,key:until===start?original.key:`DEMO-occ:${until}`,remind_at:new Date(until).toISOString()}]}));
  let writes=0;
  await page.route(url=>new URL(url).pathname==='/api/reminders',route=>{
   expect(route.request().method()).toBe('POST');expect(route.request().postDataJSON().minutes).toBe(minutes);
   until=now+minutes*60000;writes++;
   return route.fulfill({json:{patient_id:'DEMO-only',occurrence_id:original.occurrence_id,remind_at:new Date(until).toISOString()}});
  });
  await page.goto('/#today');await expect(page.getByRole('dialog',{name:'Medication reminder'})).toBeVisible();
  await page.getByRole('button',{name:`${minutes} min later`}).click();await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.reload();await expect(page.getByRole('heading',{name:'MediThread Assistant'})).toBeVisible();
  now+=60000;await page.clock.fastForward(60000);await expect(page.getByRole('dialog')).toHaveCount(0);
  now=until;await page.clock.fastForward((minutes-1)*60000);
  await expect(page.getByRole('dialog',{name:'Medication reminder'})).toBeVisible();await expect(page.getByRole('dialog')).toHaveCount(1);
  now=start+2*3600000;await page.clock.fastForward((120-minutes)*60000);
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.reload();await expect(page.getByRole('heading',{name:'MediThread Assistant'})).toBeVisible();
  await expect(page.getByRole('dialog')).toHaveCount(0);expect(writes).toBe(1);expect(mock.errors).toEqual([]);
 });
}

test('direct task creation is aligned, responsive and persists multiple reviewed reminders',async({page,baseURL})=>{
 expect(new URL(baseURL!).port).toBe('5193');
 const mock=await mockPatientApp(page,true,{token:'DEMO.correctness02-synthetic-token',owner:'de020000-0000-4000-8000-000000000001'});
 await page.route(url=>new URL(url).pathname.startsWith('/api/'),route=>route.continue());
 await page.clock.install({time:new Date('2026-10-19T04:00:00Z')});
 await page.request.put('/api/me/preferences',{headers:{Authorization:'Bearer DEMO.correctness02-synthetic-token'},data:{preferred_language:'en',text_scale_percent:100}});
 await page.goto('/#care-tasks');await page.getByRole('button',{name:'Add medication follow-up'}).click();
 const dialog=page.getByRole('dialog',{name:'New medication follow-up'});await expect(dialog).toBeVisible();
 for(const width of [390,1280]){
  await page.setViewportSize({width,height:900});
  const date=await dialog.getByLabel('Date (required)',{exact:true}).boundingBox(),time=await dialog.getByLabel('Time (required)',{exact:true}).boundingBox();
  expect(date).not.toBeNull();expect(time).not.toBeNull();
  if(width>600)expect(Math.abs(date!.y-time!.y)).toBeLessThan(2);else expect(time!.y).toBeGreaterThan(date!.y+date!.height);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:`../outputs/unified-local-rc/care-modal-${width}.png`,fullPage:true});
 }
 await dialog.getByLabel('Title (required)').fill('DEMO multiple reminders');
 await dialog.getByLabel('Date (required)',{exact:true}).fill('2026-10-21');await dialog.getByLabel('Time (required)',{exact:true}).fill('12:30');
 await dialog.getByRole('checkbox',{name:'Custom',exact:true}).check();await dialog.getByLabel('Custom minutes').fill('0.5');
 await dialog.getByRole('button',{name:'Review and save'}).click();await expect(dialog.getByRole('alert')).toContainText('valid reminder times');
 await dialog.getByRole('checkbox',{name:'Custom',exact:true}).uncheck();
 await dialog.getByRole('checkbox',{name:'At scheduled time'}).check();await dialog.getByRole('checkbox',{name:'1 day before'}).check();
 await dialog.getByRole('button',{name:'Review and save'}).click();
 const saved=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/me/care-tasks'&&response.request().method()==='POST');
 await dialog.getByRole('button',{name:'Confirm and save'}).click();const response=await saved;
 expect(response.status()).toBe(200);expect((await response.json()).reminder_offsets).toEqual([1440,60,0]);
 await expect(page.getByRole('dialog',{name:'Follow-up details'})).toBeVisible();expect(mock.errors).toEqual([]);
});
