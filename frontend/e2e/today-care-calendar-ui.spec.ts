import {expect,test} from '@playwright/test';
import {mockPatientApp} from './polish-a1-fixture';

for(const language of ['en','zh'] as const){
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
