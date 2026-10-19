/** DEMO_ONLY synthetic Auth/HTTP. Layout and interaction, no provider or patient writes. */
import {expect,test,type Page} from '@playwright/test';
import {mockPatientApp} from './polish-a1-fixture';
import {historyCatalogue,historyRecords,historyPage,historyOffset} from '../src/components/historyTestFixture';
import type {MedicationCareReview} from '../src/api/care';
import type {ReviewSummary} from '../src/api/client';

async function inspectSize(page:Page,width:number,height:number,name:string){
 await page.setViewportSize({width,height});
 await page.evaluate(()=>{(document.activeElement as HTMLElement)?.blur();window.scrollTo(0,0);});
 await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 const bounds=await page.locator('main button:visible,main select:visible,main input:visible,main textarea:visible,main .card:visible').evaluateAll(nodes=>nodes.map(node=>{const r=node.getBoundingClientRect();return {left:r.left,right:r.right,width:r.width};}));
 for(const bound of bounds){expect(bound.left).toBeGreaterThanOrEqual(0);expect(bound.right).toBeLessThanOrEqual(width+1);}
 await page.screenshot({path:`../outputs/qa/records-impeccable-${name}-${width}x${height}.png`,fullPage:true});
}

for(const language of ['en','zh'] as const){
 test(`Records hierarchy, bounded controls and child journeys in both orientations (${language})`,async({page})=>{
  const {prefs,errors,writes,setDoseFollowUps,setCapabilities}=await mockPatientApp(page);prefs.preferred_language=language;setCapabilities({late_dose_reports_enabled:true});
  setDoseFollowUps({items:Array.from({length:5},(_,index)=>({occurrence_id:`DEMO-pending-${index}`,regimen_id:'DEMO-plan',medication_id:'DEMO-med',medication_name:`DEMO medicine ${index+1}`,due_at:`2026-10-${19-index}T04:00:00Z`,dose_amount:1,dose_unit:'tablet',report_id:null,intake_status:null,actual_administration_at:null,recorded_at:null,reason:null,notes:'',can_report:index===0||index===2,...(index===1||index===3?{unavailable_reason:'review_required' as const}:{})})),has_more:false,timezone:'Asia/Singapore',as_of:'2026-10-20T04:00:00Z'});
  const c=(en:string,zh:string)=>language==='zh'?zh:en;
  const report:ReviewSummary={period:'week',window_start:'2026-10-10T00:00:00Z',window_end:'2026-10-17T00:00:00Z',generated_at:'2026-10-17T00:00:00Z',timezone:'Asia/Singapore',medications:[],reported_taken:3,reported_not_taken:1,unsure:1,observations:[],questions:[],coverage_note:'No report is not a missed dose.'};
  const review:MedicationCareReview={generated_at:report.generated_at,timezone:report.timezone,observation_window_days:30,summary:report,source_records:[],trends:[],barriers:[],inventory:[],follow_ups:[],questions:[],adherence_denominator:'DEMO_ONLY',source_note:'DEMO_ONLY'};
  await page.route('**/api/me/review-summary?**',route=>route.fulfill({json:report}));
  await page.route('**/api/me/medication-review?**',route=>route.fulfill({json:review}));
  await page.route('**/api/me/medication-history/catalogue**',route=>route.fulfill({json:historyCatalogue}));
  await page.route('**/api/me/medication-history?**',route=>{const cursor=new URL(route.request().url()).searchParams.get('cursor');return route.fulfill({json:historyPage(historyRecords(8),historyOffset(cursor??undefined))});});
  await page.goto('/#records');
  await expect(page.getByRole('heading',{name:c('Records','记录'),exact:true})).toBeVisible();
  const summary=page.locator('.records-summary--highlight');
  const summaryActions=summary.locator('.records-summary-actions');
  await expect(summaryActions).toHaveCSS('justify-content','flex-start');
  await expect(summary.getByRole('button').first()).toHaveCSS('background-color','rgb(255, 255, 255)');
  await expect(summary.getByRole('button',{name:c('This week','本周'),exact:true})).toBeVisible();
  const pending=page.locator('.records-pending-disclosure');
  await expect(pending).not.toHaveAttribute('open','');
  await pending.locator('summary').focus();await page.keyboard.press('Enter');await expect(pending).toHaveAttribute('open','');
  await expect(pending.locator('.late-dose-list > li')).toHaveCount(5);
  await expect(pending.getByRole('button',{name:c('Report dose status','记录服药情况')})).toHaveCount(2);
  await expect(pending.getByText(c('Review the saved medication and plan before reporting this occurrence.','请先核对已保存的药物和计划，再记录该剂次。'))).toHaveCount(3);
  await expect(pending.locator('.late-report-help details')).toHaveCount(0);
  await expect(pending.getByText(c('Late reporting is available for recent scheduled doses only. The time limit follows your schedule, next dose, and midnight in your time zone.','仅可补记近期的计划剂次，有效时间取决于您的用药计划和时区。'))).toBeVisible();
  await expect(pending.getByRole('button',{name:/View all .* reports/})).toHaveCount(0);
  if(language==='zh'){
   await page.setViewportSize({width:390,height:844});
   await page.screenshot({path:'../outputs/qa/records-impeccable-pending-zh-390x844.png',fullPage:true});
  }
  await page.keyboard.press('Enter');
  for(const [width,height] of [[390,844],[844,390],[1280,800]] as const){
   await inspectSize(page,width,height,`${language}-overview`);
   const buttonWidths=await summary.getByRole('button').evaluateAll(nodes=>nodes.map(node=>node.getBoundingClientRect().width));
   for(const width of buttonWidths)expect(width).toBeLessThan(280);
   expect(await page.locator('.records-screen').evaluate(node=>node.getBoundingClientRect().width)).toBeLessThanOrEqual(833);
  }
  await page.setViewportSize({width:390,height:844});
  await page.getByRole('button',{name:new RegExp(c('My medication records','我的用药记录'))}).click();
  await expect(page.getByRole('heading',{name:c('My medication records','我的用药记录'),exact:true})).toBeVisible();
  await expect(page.locator('.record-history .history li')).toHaveCount(5);
  await page.getByRole('button',{name:c('Load more records','加载更多记录')}).click();await expect(page.locator('.record-history .history li')).toHaveCount(8);
  for(const [width,height] of [[390,844],[844,390]] as const)await inspectSize(page,width,height,`${language}-history`);
  await page.getByRole('button',{name:c('Back','返回'),exact:true}).click();
  await page.getByRole('button',{name:new RegExp(c('My health notes','我的健康感受'))}).click();
  await expect(page.getByRole('heading',{level:1,name:c('My health notes','我的健康感受')})).toBeVisible();
  await page.locator('#health-description').fill('DEMO_ONLY feeling well');
  await page.getByRole('button',{name:c('Review health note','核对感受记录')}).click();
  await expect(page.getByRole('dialog')).toBeVisible();await page.getByRole('dialog').getByRole('button',{name:c('Cancel','取消'),exact:true}).click();
  await expect(page.locator('#health-description')).toHaveValue('DEMO_ONLY feeling well');
  for(const [width,height] of [[390,844],[844,390]] as const)await inspectSize(page,width,height,`${language}-health`);
  await page.getByRole('button',{name:c('Back','返回'),exact:true}).click();
  await page.getByRole('button',{name:new RegExp(c('Medication difficulties','用药困难'))}).click();
  await expect(page.getByRole('heading',{level:1,name:c('Medication difficulties','用药困难')})).toBeVisible();
  await page.getByRole('button',{name:c('Add a note in my own words','用自己的话添加备注'),exact:true}).click();
  await expect(page.locator('#difficulty-category')).toBeFocused();
  for(const [width,height] of [[390,844],[844,390]] as const)await inspectSize(page,width,height,`${language}-difficulties`);
  await page.getByRole('button',{name:c('Back','返回'),exact:true}).click();
  await page.getByRole('button',{name:c('This week','本周'),exact:true}).click();
  await expect(page.getByRole('heading',{level:1,name:c('Medication and health summary','用药与健康总结')})).toBeVisible();
  await expect(page.getByText(c('Patient reported taken','患者自述已服用'),{exact:false}).first()).toBeVisible();
  for(const [width,height] of [[390,844],[844,390]] as const)await inspectSize(page,width,height,`${language}-summary`);
  await page.getByRole('button',{name:c('Back','返回'),exact:true}).click();
  await page.getByRole('button',{name:new RegExp(c('Medication review preparation','就诊与用药复查准备'))}).click();
  await expect(page.getByRole('heading',{level:1,name:c('Medication review preparation','就诊与用药复查准备')})).toBeVisible();
  await expect(page.getByRole('button',{name:c('Export medication review','导出用药复查资料')})).toBeVisible();
  for(const [width,height] of [[390,844],[844,390]] as const)await inspectSize(page,width,height,`${language}-review`);
  await page.getByRole('button',{name:c('Back','返回'),exact:true}).click();
  prefs.text_scale_percent=150;
  await page.reload();
  for(const [width,height] of [[390,844],[844,390]] as const)await inspectSize(page,width,height,`${language}-150-overview`);
  await page.getByRole('button',{name:new RegExp(c('My medication records','我的用药记录'))}).click();
  await expect(page.locator('.record-history .history li')).toHaveCount(5);
  for(const [width,height] of [[390,844],[844,390]] as const)await inspectSize(page,width,height,`${language}-150-history`);
  for(const [route,title] of [['health-notes',c('My health notes','我的健康感受')],['adherence-barriers',c('Medication difficulties','用药困难')],['summary-week',c('Medication and health summary','用药与健康总结')],['medication-review',c('Medication review preparation','就诊与用药复查准备')]] as const){
   await page.goto(`/#${route}`);
   await expect(page.getByRole('heading',{level:1,name:title,exact:true})).toBeVisible();
   for(const [width,height] of [[390,844],[844,390]] as const)await inspectSize(page,width,height,`${language}-150-${route}`);
  }
  expect(writes.filter(path=>path.includes('health-observations')||path.includes('barriers')||path.includes('dose'))).toEqual([]);
  expect(errors).toEqual([]);
 });
}
