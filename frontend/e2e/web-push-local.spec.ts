/** BROWSER + MOCK HTTP; actual SW registration, no external push or DB call. */
import {test,expect} from '@playwright/test';
import {mkdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
test.skip(process.env.RUN_PUSH_LOCAL!=='1','Explicit local Vite fixture only');
test('notification settings in EN/ZH at phone/desktop widths and actual service worker registration',async({page})=>{
 const artifacts=fileURLToPath(new URL('../../outputs/web-push-local/',import.meta.url));await mkdir(artifacts,{recursive:true});
 const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
 let language='en';
 await page.route(url=>url.pathname.startsWith('/api/'),route=>{
  const path=new URL(route.request().url()).pathname;
  let body:unknown={};
  if(path.endsWith('/preferences'))body={preferred_language:language,speech_locale:'en-SG',text_size:'standard',text_scale_percent:language==='zh'?150:100,voice_enabled:true,tts_autoplay:false,reminder_lead_minutes:0,reminders_enabled:true,timezone:'Asia/Singapore'};
  else if(path.endsWith('/push/config'))body={available:true,public_key:'DEMO-no-live-key',test_available:true};
  else if(path.endsWith('/push/subscriptions')||path.endsWith('/reminders/plan'))body=[];
  else if(path.endsWith('/speech/capabilities'))body={cloud_tts_allowed:false};
  else throw new Error(`Unexpected local fixture API: ${path}`);
  return route.fulfill({json:body});
 });
 for(const [width,locale] of [[390,'en'],[430,'zh'],[1280,'en']] as const){
  language=locale;await page.setViewportSize({width,height:920});await page.goto('/e2e/push-settings.html');
  await expect(page.getByRole('heading',{name:locale==='zh'?'设备通知':'Device notifications',exact:true})).toBeVisible();
  const guide=page.locator('#notification-guide');await guide.locator('summary').click();
  await guide.getByRole('combobox').selectOption('iOS');await expect(guide).toContainText('16.4');
  await expect(page.getByRole('button',{name:locale==='zh'?'发送测试通知':'Send test notification',exact:true})).toBeDisabled();
  expect(await page.evaluate(()=>Notification.permission)).toBe('default');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:`${artifacts}settings-${width}-${locale}.png`,fullPage:true});
 }
 await page.evaluate(async()=>{await navigator.serviceWorker.register('/sw.js',{scope:'/'});await navigator.serviceWorker.ready;});
 await expect.poll(()=>page.evaluate(async()=>(await navigator.serviceWorker.getRegistration('/'))?.active?.state)).toBe('activated');
 expect(errors).toEqual([]);
});
