/** BROWSER + MOCK HTTP; actual SW registration, no external push or DB call. */
import {test,expect} from '@playwright/test';
test.skip(process.env.RUN_PUSH_LOCAL!=='1','Explicit local Vite fixture only');
test('compact notification settings in EN/ZH at phone/desktop widths and actual service worker registration',async({page})=>{
 const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
 let language='en';let remindersEnabled=true;
 const token='DEMO.notifications-session';
 const user={id:'d00d0000-0000-4000-8000-000000000001',aud:'authenticated',role:'authenticated',email:null,phone:'',app_metadata:{provider:'anonymous',providers:['anonymous']},user_metadata:{demo_only:true},is_anonymous:true,created_at:'2026-10-20T00:00:00Z'};
 await page.route(url=>new URL(url.href).pathname.includes('/auth/v1/'),async route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/signup'))return route.fulfill({json:{access_token:token,token_type:'bearer',expires_in:3600,refresh_token:'DEMO.refresh',user}});
  if(path.endsWith('/user'))return route.fulfill({json:user});
  throw new Error(`Unexpected synthetic Auth request: ${path}`);
 });
 await page.route(url=>new URL(url.href).pathname.startsWith('/api/'),route=>{
  const path=new URL(route.request().url()).pathname;
  let body:unknown={};
  if(path.endsWith('/preferences')){if(route.request().method()==='PUT'){const update=route.request().postDataJSON() as {reminders_enabled?:boolean};if(typeof update.reminders_enabled==='boolean')remindersEnabled=update.reminders_enabled;}body={preferred_language:language,speech_locale:'en-SG',text_size:'standard',text_scale_percent:language==='zh'?150:100,voice_enabled:true,tts_autoplay:false,reminder_lead_minutes:0,reminders_enabled:remindersEnabled,timezone:'Asia/Singapore'};}
  else if(path.endsWith('/push/config'))body={available:true,public_key:'DEMO-no-live-key',test_available:true};
  else if(path.endsWith('/push/subscriptions')||path.endsWith('/reminders/plan')||path.endsWith('/care-tasks'))body=[];
  else if(path.endsWith('/speech/capabilities'))body={cloud_tts_allowed:false};
  else throw new Error(`Unexpected local fixture API: ${path}`);
  return route.fulfill({json:body});
 });
 for(const [width,locale] of [[390,'en'],[430,'zh'],[1280,'en']] as const){
  language=locale;await page.setViewportSize({width,height:920});await page.goto('/e2e/push-settings.html');
  await expect(page.getByRole('heading',{name:locale==='zh'?'此设备通知':'Device Notifications',exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:locale==='zh'?'导出日历':'Export Calendar',exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:locale==='zh'?'导出日历':'Export Calendar',exact:true})).toBeInViewport();
  await expect(page.locator('section.reminder-settings__section')).toHaveCount(2);
  const medicationSwitch=page.getByRole('switch',{name:locale==='zh'? /\u5b9a\u65f6\u7528\u836f\u63d0\u9192/ : 'Medication Reminders'});
  const initialChecked=remindersEnabled;
  await expect(medicationSwitch).toHaveAttribute('aria-checked',initialChecked?'true':'false');
  await medicationSwitch.hover();
  const brandColor=await page.evaluate(()=>{const probe=document.createElement('span');probe.style.color=getComputedStyle(document.documentElement).getPropertyValue('--brand');document.body.append(probe);const color=getComputedStyle(probe).color;probe.remove();return color;});
  const offColor=await page.evaluate(()=>{const probe=document.createElement('span');probe.style.color=getComputedStyle(document.documentElement).getPropertyValue('--ink-3');document.body.append(probe);const color=getComputedStyle(probe).color;probe.remove();return color;});
  await expect.poll(()=>medicationSwitch.evaluate(element=>getComputedStyle(element).backgroundColor)).toBe(initialChecked?brandColor:offColor);
  const actions=page.locator('.device-notification-actions button');
  await expect(actions).toHaveCount(2);
  const boxes=await Promise.all([actions.nth(0),actions.nth(1)].map(button=>button.evaluate(element=>{const {width,height}=element.getBoundingClientRect();return {width,height};})));
  expect(Math.abs(boxes[0].height-boxes[1].height)).toBeLessThan(1);expect(Math.abs(boxes[0].width-boxes[1].width)).toBeLessThan(1);
  await expect(page.locator('.device-notification-actions__reason')).toBeVisible();
  const deviceSwitch=page.getByRole('switch',{name:locale==='zh'?'接收设备通知':'Receive Device Notifications'});
  await expect(deviceSwitch).toBeVisible();await expect(deviceSwitch).toHaveAttribute('aria-checked','false');
  await deviceSwitch.focus();await expect(deviceSwitch).toBeFocused();
  await page.locator('.device-notification-actions button').nth(1).click();
  const dialog=page.getByRole('dialog');await expect(dialog).toBeVisible();
  await expect(dialog.locator('ol.push-setup-steps li')).toHaveCount(4);
  const pushSupported=await page.evaluate(()=>isSecureContext&&'serviceWorker' in navigator&&'PushManager' in window&&'Notification' in window);
  if(!pushSupported)await expect(dialog.getByText(locale==='zh'?'此浏览器或设备不支持后台通知':'This browser or device does not support background notifications.')).toBeVisible();
  expect(await page.evaluate(()=>Notification.permission)).toBe('default');
  await dialog.getByText(locale==='zh'?'高级信息与设备管理':'Advanced information and device management').click();
  const guide=page.locator('#notification-guide');await guide.locator('summary').click();
  await guide.getByRole('combobox').selectOption('iOS');await expect(guide).toContainText('16.4');
  await page.keyboard.press('Escape');await expect(dialog).toBeHidden();
  if(width===390){
   await medicationSwitch.focus();await page.keyboard.press('Space');await medicationSwitch.hover();
   const changedChecked=!initialChecked;
   await expect(medicationSwitch).toHaveAttribute('aria-checked',changedChecked?'true':'false');
   await expect.poll(()=>medicationSwitch.evaluate(element=>getComputedStyle(element).backgroundColor)).toBe(changedChecked?brandColor:offColor);
   await page.reload();await expect(page.getByRole('switch',{name:/Medication Reminders|\u5b9a\u65f6\u7528\u836f\u63d0\u9192/})).toHaveAttribute('aria-checked',changedChecked?'true':'false');
  }
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 }
 await page.evaluate(async()=>{await navigator.serviceWorker.register('/sw.js',{scope:'/'});await navigator.serviceWorker.ready;});
 await expect.poll(()=>page.evaluate(async()=>(await navigator.serviceWorker.getRegistration('/'))?.active?.state)).toBe('activated');
 expect(errors).toEqual([]);
});
