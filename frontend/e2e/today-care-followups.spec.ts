/** Actual React -> local FastAPI/application, synthetic memory. SQL is tested separately. */
import {expect,test} from '@playwright/test';
import {mockPatientApp} from './polish-a1-fixture';

for(const language of ['en','zh'] as const){
 test(`Today and Care Tasks confirmed workflows (${language})`,async({page,baseURL})=>{
  test.setTimeout(90000);page.setDefaultTimeout(15000);expect(new URL(baseURL!).port).toBe('5193');
  const {errors}=await mockPatientApp(page,true,{token:'DEMO.correctness02-synthetic-token',owner:'de020000-0000-4000-8000-000000000001'});
  await page.route(url=>new URL(url).pathname.startsWith('/api/'),route=>route.continue());
  await page.clock.install({time:new Date('2026-10-19T04:00:00Z')});
  await page.request.put('/api/me/preferences',{headers:{Authorization:'Bearer DEMO.correctness02-synthetic-token'},data:{preferred_language:language,text_scale_percent:100}});
  const c=(en:string,zh:string)=>language==='zh'?zh:en;
  await page.goto('/#today');
  const followups=page.getByRole('region',{name:c('Recent dose reports','近期服药情况')});
  await expect(followups.getByText(c('Unreported means there is no confirmed patient report. It does not mean a dose was missed.','尚未记录表示系统没有收到经您确认的服药自述，不等于未服用。'))).toBeVisible();
  const dose=followups.getByRole('button',{name:c('Report dose status','补记服药情况')}).first();await dose.click();
  const dialog=page.getByRole('dialog');await dialog.getByRole('radio').nth(language==='en'?1:2).check();
  await dialog.getByRole('button',{name:c('Review report','核对自述'),exact:true}).click();await expect(dialog.getByRole('combobox')).toBeFocused();
  await dialog.getByRole('combobox').selectOption('forgot_to_record');await dialog.getByRole('button',{name:c('Review report','核对自述'),exact:true}).click();
  await expect(dialog.getByText(c('Review your report','请核对您的自述'))).toBeVisible();
  await page.screenshot({path:`../outputs/qa/today-care-${language}-late-mobile.png`,fullPage:true});
  const reportSaved=page.waitForResponse(response=>response.request().method()==='POST'&&/\/late-report(?:\?|$)/.test(new URL(response.url()).pathname));
  await dialog.getByRole('button',{name:c('Confirm report','确认记录'),exact:true}).click();expect((await reportSaved).status()).toBe(200);
  await expect(page.getByText(c('Patient report saved.','已保存您的服药自述。'))).toBeVisible();
  await page.getByRole('button',{name:c('View all follow-ups','查看全部用药跟进')}).click();
  await page.getByRole('button',{name:c('Add medication follow-up','添加用药跟进')}).click();
  await dialog.getByRole('button',{name:c('Review and save','核对并保存')}).click();await expect(dialog.locator('input[name=title]')).toBeFocused();await expect(dialog.getByRole('alert')).toHaveCount(3);
  await dialog.locator('input[name=title]').fill(`DEMO browser task ${language}`);
  await dialog.locator('input[name=date]').fill('2026-10-22');await dialog.locator('input[name=time]').fill('14:00');
  await dialog.locator('select[name=reminder]').selectOption('30');
  for(const width of [390,1280]){await page.setViewportSize({width,height:900});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:`../outputs/qa/today-care-${language}-form-${width}.png`,fullPage:true});}
  await dialog.getByRole('button',{name:c('Review and save','核对并保存')}).click();
  await dialog.getByRole('button',{name:c('Confirm and save','确认保存')}).click();
  await expect(dialog.getByRole('heading',{name:`DEMO browser task ${language}`})).toBeVisible();
  await expect(page).toHaveURL(/care-tasks\?task=/);
  await page.reload();await expect(dialog.getByRole('heading',{name:`DEMO browser task ${language}`})).toBeVisible();
  await dialog.getByRole('button',{name:c('Mark complete','标记完成')}).click();
  await dialog.getByRole('button',{name:c('Confirm','确认'),exact:true}).click();
  await expect(dialog.getByRole('button',{name:c('Reopen and reschedule','重新打开并改期')})).toBeVisible();
  await dialog.getByRole('button',{name:c('Reopen and reschedule','重新打开并改期')}).click();
  await dialog.locator('input[name=date]').fill('2026-10-23');await dialog.locator('select[name=reminder]').selectOption('none');
  await dialog.getByRole('button',{name:c('Review and save','核对并保存')}).click();await dialog.getByRole('button',{name:c('Confirm and save','确认保存')}).click();
  await expect(dialog.getByRole('button',{name:c('Mark complete','标记完成')})).toBeVisible();
  await expect(dialog.getByText(c('Task created','创建事项'))).toBeVisible();
  await page.screenshot({path:`../outputs/qa/today-care-${language}-detail-desktop.png`,fullPage:true});
  await dialog.getByRole('button',{name:c('Close','关闭'),exact:true}).click();
  await page.getByRole('button',{name:c('Overdue','已过期'),exact:true}).click();await expect(page.getByRole('button',{name:/DEMO check collection/})).toBeVisible();
  expect(errors).toEqual([]);
 });
}

test('Today task deep link and explicit past-entry confirmation use the actual application',async({page})=>{
 test.setTimeout(60000);page.setDefaultTimeout(15000);
 const {errors}=await mockPatientApp(page,true,{token:'DEMO.correctness02-synthetic-token',owner:'de020000-0000-4000-8000-000000000001'});
 await page.route(url=>new URL(url).pathname.startsWith('/api/'),route=>route.continue());
 await page.clock.install({time:new Date('2026-10-19T04:00:00Z')});
 await page.request.put('/api/me/preferences',{headers:{Authorization:'Bearer DEMO.correctness02-synthetic-token'},data:{preferred_language:'en'}});
 await page.goto('/#today');
 const card=page.getByRole('button',{name:/DEMO prepare review/});await card.click();
 const dialog=page.getByRole('dialog');await expect(dialog.getByRole('heading',{name:'DEMO prepare review'})).toBeVisible();await expect(page).toHaveURL(/care-tasks\?task=/);
 await dialog.getByRole('button',{name:'Close',exact:true}).click();await page.getByRole('button',{name:'Add medication follow-up'}).click();
 await dialog.locator('input[name=title]').fill('DEMO browser historical entry');await dialog.locator('input[name=date]').fill('2026-10-17');await dialog.locator('input[name=time]').fill('14:00');
 await dialog.getByRole('button',{name:'Review and save'}).click();await expect(dialog.locator('select[name=reminder]')).toBeFocused();await expect(dialog.getByRole('alert')).toContainText('past');
 await dialog.locator('select[name=reminder]').selectOption('none');await dialog.getByRole('button',{name:'Review and save'}).click();
 await expect(dialog.getByText(/Save it as a historical task/)).toBeVisible();await dialog.getByRole('button',{name:'Confirm historical entry'}).click();
 const saved=page.waitForResponse(response=>response.request().method()==='POST'&&new URL(response.url()).pathname==='/api/me/care-tasks');await dialog.getByRole('button',{name:'Confirm and save'}).click();const result=await (await saved).json() as {historical_entry:boolean;reminder_minutes:number|null};expect(result.historical_entry).toBe(true);expect(result.reminder_minutes).toBeNull();
 await expect(dialog.getByRole('heading',{name:'DEMO browser historical entry'})).toBeVisible();expect(errors).toEqual([]);
});

test('no active medicines still exposes and confirms existing ended-plan follow-ups',async({page})=>{
 test.skip(process.env.QA_CARE_NO_ACTIVE!=='1','Requires the dedicated ended-plan synthetic server');
 test.setTimeout(60000);
 const {errors}=await mockPatientApp(page,true,{token:'DEMO.correctness02-synthetic-token',owner:'de020000-0000-4000-8000-000000000001'});
 await page.route(url=>new URL(url).pathname.startsWith('/api/'),route=>route.continue());
 await page.clock.install({time:new Date('2026-10-19T04:00:00Z')});
 const headers={Authorization:'Bearer DEMO.correctness02-synthetic-token'};
 await page.request.put('/api/me/preferences',{headers,data:{preferred_language:'en'}});
 expect((await (await page.request.get('/api/me/medications',{headers})).json() as {medications:unknown[]}).medications).toEqual([]);
 await page.goto('/#today');const section=page.getByRole('region',{name:'Recent dose reports'});
 await section.getByRole('button',{name:'Report dose status'}).first().click();const dialog=page.getByRole('dialog');
 await dialog.getByRole('radio').nth(2).check();await dialog.getByRole('combobox').selectOption('forgot_to_record');
 await dialog.getByRole('button',{name:'Review report',exact:true}).click();await expect(dialog.getByText('Review your report')).toBeVisible();
 const saved=page.waitForResponse(response=>response.request().method()==='POST'&&/\/late-report$/.test(new URL(response.url()).pathname));
 await dialog.getByRole('button',{name:'Confirm report',exact:true}).click();expect((await saved).status()).toBe(200);
 await expect(section.getByText('Patient report saved.')).toBeVisible();expect(errors).toEqual([]);
});


test('unreleased capabilities remain unavailable without dose reads or silent advanced settings',async({page})=>{
 const {errors}=await mockPatientApp(page,true,{token:'DEMO.correctness02-synthetic-token',owner:'de020000-0000-4000-8000-000000000001'});
 await page.route(url=>new URL(url).pathname.startsWith('/api/'),route=>route.continue());
 let reads=0;page.on('request',request=>{if(new URL(request.url()).pathname==='/api/me/dose-follow-ups')reads++;});
 await page.route('**/api/health',async route=>{const response=await route.fetch();await route.fulfill({response,json:{...await response.json(),late_dose_reports_enabled:false,care_task_followups_enabled:false}});});
 await page.clock.install({time:new Date('2026-10-19T04:00:00Z')});
 await page.request.put('/api/me/preferences',{headers:{Authorization:'Bearer DEMO.correctness02-synthetic-token'},data:{preferred_language:'en'}});
 await page.goto('/#today');await expect(page.getByText(/Late reporting is not enabled yet/)).toBeVisible();expect(reads).toBe(0);
 await page.getByRole('button',{name:'View all follow-ups'}).click();await page.getByRole('button',{name:'Add medication follow-up'}).click();
 await expect(page.getByLabel('Advance reminder')).toBeDisabled();await expect(page.getByLabel('Advance reminder')).toHaveValue('0');
 expect(errors).toEqual([]);
});
