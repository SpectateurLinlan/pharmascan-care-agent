import {expect,test} from '@playwright/test';
import {mockPatientApp} from './polish-a1-fixture';

for(const language of ['en','zh'] as const){
 test(`Today medication and follow-up cards stay compact and localized (${language})`,async({page})=>{
  const token=`DEMO.today-${language}`;
  const {errors,prefs,setCapabilities,setMedications,setTodayDate,setDoseFollowUps,setDueDose,setCareTasks}=await mockPatientApp(page,true,{token,owner:'d00d0000-0000-4000-8000-000000000001'});
  prefs.preferred_language=language;prefs.timezone='Asia/Singapore';
  await page.clock.install({time:new Date('2026-10-19T04:00:00Z')});
  setCapabilities({late_dose_reports_enabled:true,care_task_followups_enabled:true});
  setTodayDate('2026-10-19T04:00:00Z','2026-10-19');
  setMedications([{regimen_id:'DEMO-plan',medication_id:'DEMO-med',display_name:'DEMO Amlodipine',is_prn:false,dose_amount:1,dose_unit:'tablet',version_no:1,identity_status:'reviewed',source_backed:true}]);
  setDoseFollowUps({items:[{occurrence_id:'DEMO-today-occurrence',regimen_id:'DEMO-plan',medication_id:'DEMO-med',medication_name:'DEMO Amlodipine',due_at:'2026-10-19T00:00:00Z',dose_amount:1,dose_unit:'tablet',report_id:null,intake_status:null,actual_administration_at:null,recorded_at:null,reason:null,notes:''}],has_more:false,timezone:'Asia/Singapore',as_of:'2026-10-19T04:00:00Z'});
  setDueDose({occurrence_id:'DEMO-today-occurrence',due_at:'2026-10-19T00:00:00Z'});
  setCareTasks([{id:'DEMO-task',title:'DEMO medication review',category:'medication_review',due_at:'2026-10-19T13:09:00Z',status:'open',medication_id:'DEMO-med',regimen_id:'DEMO-plan',notes:'',reminder_minutes:30,patient_id:'DEMO-owner',source:'patient_reported',version:1,history:[],created_at:'2026-10-18T00:00:00Z',updated_at:'2026-10-18T00:00:00Z',demo_only:true}]);
  await page.goto('/#today');
  const c=(en:string,zh:string)=>language==='zh'?zh:en;
  const medication=page.getByRole('region',{name:c("Today's medication",'今日用药')});
  await expect(medication.getByRole('heading',{name:c("Today's confirmation",'今日待确认')})).toBeVisible();
  await expect(medication.locator('time')).toHaveAttribute('datetime','2026-10-19');
  await expect(medication.getByText(language==='zh'?'1 项':'1 item')).toBeVisible();
  await expect(medication.getByRole('button',{name:c('Record status','记录情况')})).toBeVisible();
  await expect(medication.getByText('DEMO Amlodipine')).toHaveCount(1);
  await expect(page.getByText('DEMO medication review')).toBeVisible();
  await expect(page.getByRole('button',{name:new RegExp(c('Add Follow-up','新增跟进'))})).toBeVisible();
  for(const width of [360,390,430,768,1280,1440,1920]){
   await page.setViewportSize({width,height:844});
   await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
   const typography=await page.locator('body').evaluate(element=>({body:getComputedStyle(element).fontSize,root:getComputedStyle(document.documentElement).fontSize,role:getComputedStyle(document.documentElement).getPropertyValue('--fs-body'),scale:document.documentElement.style.getPropertyValue('--font-scale'),sheets:Array.from(document.styleSheets).map(sheet=>sheet.href)}));
   expect(typography.body,JSON.stringify(typography)).toBe('12px');
   expect(await page.locator('h1').first().evaluate(element=>getComputedStyle(element).fontSize)).toBe(width<=640?'20px':'22px');
   const shortcutCount=await page.locator('.today-assistant .assistant-tasks button:visible').count();
   expect(shortcutCount).toBe(4);
   expect(await page.locator('.today-assistant__expand').evaluate(element=>getComputedStyle(element).borderStyle)).toBe('solid');
   const visibleChips=page.locator('.today-assistant .assistant-tasks button:visible');
   for(let index=0;index<await visibleChips.count();index++){
    const box=await visibleChips.nth(index).boundingBox();expect(box).not.toBeNull();
    expect(box!.height).toBeGreaterThanOrEqual(40);expect(box!.width).toBeLessThan(width<=640?width-32:width/2);
   }
   if(width===390||width===1280)await page.screenshot({path:`../outputs/qa/today-compact-${language}-${width}.png`});
  }
  expect(errors).toEqual([]);
 });
 test(`Care Task calendar/list controls remain usable on mobile and desktop (${language})`,async({page})=>{
  const token=`DEMO.calendar-${language}`;
  const {errors,prefs}=await mockPatientApp(page,true,{token,owner:'d00d0000-0000-4000-8000-000000000001'});
  prefs.preferred_language=language;prefs.speech_locale=language==='zh'?'zh-CN':'en-SG';
  await page.clock.install({time:new Date('2026-10-19T04:00:00Z')});
  const tasks=[
   {id:'DEMO-overdue',title:'DEMO overdue task',category:'medication_review',due_at:'2026-10-19T02:00:00Z',status:'open',medication_id:null,regimen_id:null,notes:'',reminder_minutes:0,patient_id:'DEMO-owner',source:'patient_reported',version:1,history:[],created_at:'2026-10-18T00:00:00Z',updated_at:'2026-10-18T00:00:00Z',demo_only:true},
   {id:'DEMO-pending',title:'DEMO pending task',category:'medication_review',due_at:'2026-10-19T05:00:00Z',status:'open',medication_id:null,regimen_id:null,notes:'',reminder_minutes:0,patient_id:'DEMO-owner',source:'patient_reported',version:1,history:[],created_at:'2026-10-18T00:00:00Z',updated_at:'2026-10-18T00:00:00Z',demo_only:true},
   {id:'DEMO-completed',title:'DEMO completed task',category:'medication_review',due_at:'2026-10-19T03:00:00Z',status:'completed',medication_id:null,regimen_id:null,notes:'',reminder_minutes:0,patient_id:'DEMO-owner',source:'patient_reported',version:1,history:[],created_at:'2026-10-18T00:00:00Z',updated_at:'2026-10-18T00:00:00Z',demo_only:true},
  ];
  await page.route('**/api/me/care-tasks**',route=>route.fulfill({json:tasks}));
  await page.goto('/#care-tasks');
  const view=page.getByRole('group',{name:language==='zh'?'跟进视图':'Care Task view'});
  await expect(view.getByRole('button',{name:language==='zh'?'日历':'Calendar'})).toHaveAttribute('aria-pressed','true');
  const filterName=language==='zh'?'按状态筛选':'Filter by status';
  await expect.poll(()=>view.evaluate(element=>element.getBoundingClientRect().height)).toBeLessThanOrEqual(50);
  await page.locator('.care-status-filter--desktop').getByRole('button',{name:language==='zh'?'已完成':'Completed',exact:true}).click();
  const taskHeader=page.locator('.care-task-page__header'),titleBox=await taskHeader.locator('h2').boundingBox(),addBox=await taskHeader.locator('.primary').boundingBox();
  expect(titleBox).not.toBeNull();expect(addBox).not.toBeNull();
  expect(titleBox!.y+titleBox!.height).toBeGreaterThan(addBox!.y);expect(titleBox!.y).toBeLessThan(addBox!.y+addBox!.height);
  await expect(page.getByRole('button',{name:/DEMO completed task/})).toBeVisible();
  await expect(page.getByRole('button',{name:/DEMO overdue task/})).toHaveCount(0);
  await view.getByRole('button',{name:language==='zh'?'列表':'List'}).click();
  await expect(page.getByRole('button',{name:/DEMO completed task/})).toBeVisible();
  await page.setViewportSize({width:1280,height:844});
  const filters=page.getByRole('group',{name:filterName});
  await expect(filters.getByRole('button',{name:language==='zh'?'已完成':'Completed'})).toHaveAttribute('aria-pressed','true');
  await page.getByRole('button',{name:language==='zh'?'新增跟进':'Add Follow-up'}).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await view.getByRole('button',{name:language==='zh'?'日历':'Calendar'}).click();
  for(const width of [360,390,430,768,1280,1440,1920]){
   await page.setViewportSize({width,height:844});
   await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
   const grid=page.locator('.care-calendar__grid'),headers=grid.locator('[role="columnheader"]');
   await expect(headers).toHaveCount(7);
   await expect(headers.first()).toHaveText(language==='zh'?'一':'Mon');
   const geometry=await grid.evaluate(element=>({width:element.clientWidth,scrollWidth:element.scrollWidth,columns:Array.from(element.querySelectorAll('[role="columnheader"]')).map(header=>{const box=header.getBoundingClientRect();return {x:box.x,width:box.width,right:box.right};})}));
   expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.width);
   expect(Math.max(...geometry.columns.map(column=>column.width))-Math.min(...geometry.columns.map(column=>column.width))).toBeLessThan(1);
   expect(geometry.columns.every(column=>column.width>0&&column.right<=geometry.columns[6]!.right)).toBe(true);
   if(width===390||width===1280)await page.screenshot({path:`../outputs/qa/care-calendar-${language}-${width}.png`});
  }
  expect(errors).toEqual([]);
 });
}

test('Records report period controls wrap compactly at mobile and desktop widths',async({page})=>{
 const {errors}=await mockPatientApp(page,true,{token:'DEMO.records-controls',owner:'d00d0000-0000-4000-8000-000000000001'});
 await page.goto('/#records');
 const choices=page.locator('.records-summary-actions button');
 await expect(choices).toHaveCount(3);
 for(const width of [360,390,430,1280]){
  await page.setViewportSize({width,height:844});
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  for(let index=0;index<await choices.count();index++){
   const box=await choices.nth(index).boundingBox();expect(box).not.toBeNull();
   expect(box!.height).toBeGreaterThanOrEqual(40);expect(box!.width).toBeLessThan(width-24);
  }
  if(width===390||width===1280)await page.screenshot({path:`../outputs/qa/records-report-controls-${width}.png`});
 }
 expect(errors).toEqual([]);
});

test('150 percent patient text preference enlarges text without clipping mobile or desktop content',async({page})=>{
 const {prefs}=await mockPatientApp(page,true,{token:'DEMO.text-scale-150',owner:'d00d0000-0000-4000-8000-000000000001'});
 prefs.text_scale_percent=150;
 await page.goto('/#today');
 await expect.poll(()=>page.evaluate(()=>document.documentElement.style.getPropertyValue('--font-scale'))).toBe('1.5');
 for(const width of [390,1280]){
  await page.setViewportSize({width,height:900});
  expect(await page.locator('body').evaluate(element=>getComputedStyle(element).fontSize)).toBe('18px');
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  const primary=page.locator('button:visible').first();
  expect(await primary.evaluate(element=>element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44);
  if(width===390){
   const heading=await page.locator('.today-assistant__heading h2').boundingBox(),open=await page.locator('.today-assistant__expand').boundingBox();
   expect(heading).not.toBeNull();expect(open).not.toBeNull();
   expect(heading!.x+heading!.width<=open!.x||open!.x+open!.width<=heading!.x||heading!.y+heading!.height<=open!.y||open!.y+open!.height<=heading!.y).toBe(true);
   const composerInput=await page.locator('.today-assistant .composer-row input:not([type="file"])').boundingBox(),send=await page.locator('.today-assistant .composer-send').boundingBox();
   expect(composerInput).not.toBeNull();expect(send).not.toBeNull();expect(composerInput!.width).toBeGreaterThan(100);
   expect(composerInput!.x+composerInput!.width).toBeLessThanOrEqual(send!.x+1);
   const nav=await page.locator('.patient-nav').boundingBox();expect(nav).not.toBeNull();expect(nav!.height).toBeLessThan(120);
  }
  await page.screenshot({path:`../outputs/qa/text-scale-150-${width}.png`});
 }
});
