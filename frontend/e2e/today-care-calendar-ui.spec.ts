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
  for(const width of [390,1280]){
   await page.setViewportSize({width,height:844});
   await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
   await page.screenshot({path:`../outputs/qa/today-compact-${language}-${width}.png`,fullPage:true});
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
  const mobileFilter=page.locator('.care-status-filter__mobile select');
  await mobileFilter.selectOption('completed');
  await expect(page.getByRole('button',{name:/DEMO completed task/})).toBeVisible();
  await expect(page.getByRole('button',{name:/DEMO overdue task/})).toHaveCount(0);
  await view.getByRole('button',{name:language==='zh'?'列表':'List'}).click();
  await expect(page.getByRole('button',{name:/DEMO completed task/})).toBeVisible();
  await page.setViewportSize({width:1280,height:844});
  const filters=page.getByRole('group',{name:filterName});
  await expect(filters.getByRole('button',{name:language==='zh'?'已完成':'Completed'})).toHaveAttribute('aria-pressed','true');
  await page.getByRole('button',{name:language==='zh'?'新增跟进':'Add Follow-up'}).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  for(const width of [390,1280]){
   await page.setViewportSize({width,height:844});
   await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  }
  expect(errors).toEqual([]);
 });
}
