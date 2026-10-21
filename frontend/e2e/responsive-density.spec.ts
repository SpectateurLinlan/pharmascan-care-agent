/** Actual browser layout; all identities, medicines and HTTP responses are DEMO_ONLY. */
import {expect,test,chromium,type Page} from '@playwright/test';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {mockPatientApp} from './polish-a1-fixture';

const phase=process.env.DENSITY_CAPTURE_PHASE??'after';
const output=path.resolve('../outputs/qa',`density-${phase}`);
async function seed(page:Page,language:'en'|'zh',scale=100){
 const fixture=await mockPatientApp(page,true);
 Object.assign(fixture.prefs,{preferred_language:language,speech_locale:language==='zh'?'zh-CN':'en-SG',voice_enabled:true,text_scale_percent:scale});
 await page.clock.install({time:new Date('2026-10-20T04:00:00Z')});
 fixture.setCapabilities({late_dose_reports_enabled:true,care_task_followups_enabled:true});
 fixture.setTodayDate('2026-10-20T04:00:00Z','2026-10-20');
 fixture.setMedications(['DEMO Amlodipine 10 mg','DEMO Metformin 500 mg','DEMO Nifedipine LA 30 mg'].map((display_name,index)=>({regimen_id:`DEMO-plan-${index}`,medication_id:`DEMO-med-${index}`,display_name,is_prn:false,dose_amount:1,dose_unit:'tablet',version_no:1,identity_status:'reviewed',source_backed:true,frequency_rule:{kind:'daily',local_times:['08:00','20:00'],days_of_week:[]}})));
 fixture.setDoseFollowUps({items:[{occurrence_id:'DEMO-occurrence',regimen_id:'DEMO-plan-0',medication_id:'DEMO-med-0',medication_name:'DEMO Amlodipine 10 mg',due_at:'2026-10-20T02:00:00Z',dose_amount:1,dose_unit:'tablet',report_id:null,intake_status:null,actual_administration_at:null,recorded_at:null,reason:null,notes:'',can_report:true}],has_more:false,timezone:'Asia/Singapore',as_of:'2026-10-20T04:00:00Z'});
 fixture.setDueDose({occurrence_id:'DEMO-occurrence',due_at:'2026-10-20T02:00:00Z'});
 const tasks=([['open','2026-10-20T13:00:00Z'],['open','2026-10-19T01:00:00Z'],['completed','2026-10-20T01:00:00Z']] as const).map(([status,due_at],index)=>({id:`DEMO-task-${index}`,title:language==='zh'?`演示用药复查 ${index+1}`:`DEMO medication review ${index+1}`,category:'medication_review' as const,due_at,status,medication_id:null,regimen_id:null,notes:'',reminder_minutes:0,patient_id:'DEMO-owner',source:'patient_reported' as const,version:1,history:[],created_at:'2026-10-18T00:00:00Z',updated_at:'2026-10-18T00:00:00Z',demo_only:true as const}));
 fixture.setCareTasks(tasks);
 await page.route(url=>new URL(url).pathname==='/api/me/care-tasks',route=>route.fulfill({json:tasks}));
 await page.route(url=>new URL(url).pathname==='/api/agent/conversations',route=>route.fulfill({json:{entries:[],next_before:null}}));
 const review={generated_at:'2026-10-20T04:00:00Z',timezone:'Asia/Singapore',observation_window_days:30,summary:{period:'month',window_start:'2026-10-01T00:00:00Z',window_end:'2026-10-20T04:00:00Z',generated_at:'2026-10-20T04:00:00Z',timezone:'Asia/Singapore',reported_taken:0,reported_not_taken:0,unsure:0,observations:[],questions:[],coverage_note:'DEMO stored occurrences only',medications:[]},source_records:[],trends:[],barriers:[],inventory:[],follow_ups:[],questions:[],adherence_denominator:'DEMO unrecorded is unknown',source_note:'DEMO patient report'} satisfies import('../src/api/care').MedicationCareReview;
 await page.route(url=>new URL(url).pathname==='/api/me/medication-review',route=>route.fulfill({json:review}));
 return fixture;
}

async function metrics(page:Page){return page.evaluate(()=>{
 const bounds=(selector:string)=>{const element=document.querySelector(selector);if(!element)return null;const b=element.getBoundingClientRect();return {x:b.x,y:b.y,width:b.width,height:b.height};};
 return {innerWidth,innerHeight,outerWidth,outerHeight,dpr:devicePixelRatio,visualScale:visualViewport?.scale,root:getComputedStyle(document.documentElement).fontSize,body:getComputedStyle(document.body).fontSize,rail:getComputedStyle(document.documentElement).getPropertyValue('--rail-width'),overflow:document.documentElement.scrollWidth>innerWidth,header:bounds('.app-header'),nav:bounds('.patient-nav'),assistant:bounds('.today-assistant'),medication:bounds('#today-medication'),add:bounds('.medication-add-actions'),summary:bounds('.records-summary--highlight'),visibleSuggestions:document.querySelectorAll('.today-assistant .assistant-tasks button').length};
 });}

async function assertPageLayout(page:Page,reference:{x:number;width:number},label:string){
 const measured=await page.locator('.app-main').evaluate(main=>{
  const visible=(element:Element)=>element.isConnected&&element.getClientRects().length>0;
  const bounds=(element:Element)=>{const rect=element.getBoundingClientRect();return {selector:element.className,x:rect.x,width:rect.width,right:rect.right};};
  const surfaces=[main,...Array.from(main.children).filter(visible),...Array.from(main.querySelectorAll('.ui-screen,.ui-screen__head,.conversation-workspace,.regimen-history-page,.about-page')).filter(visible)];
  const cards=Array.from(main.querySelectorAll('.card')).filter(visible);
  const fullCards=cards.filter(card=>{
   const parent=card.parentElement;if(!parent)return false;
   if(!parent.matches('.app-main,.ui-screen,.profile-screen > section,.account-security-panel,[data-page]'))return false;
   const grid=getComputedStyle(parent);return grid.display!=='grid'||grid.gridTemplateColumns.split(' ').length===1||getComputedStyle(card).gridColumnEnd==='-1';
  });
  return {surfaces:[...surfaces,...fullCards].map(bounds),cards:cards.map(bounds),overflow:document.documentElement.scrollWidth>innerWidth};
 });
 for(const box of measured.surfaces){expect(Math.abs(box.x-reference.x),`${label} ${box.selector} left`).toBeLessThan(1);expect(Math.abs(box.width-reference.width),`${label} ${box.selector} width`).toBeLessThan(1);}
 for(const box of measured.cards){expect(box.x,`${label} card left`).toBeGreaterThanOrEqual(reference.x-1);expect(box.right,`${label} card right`).toBeLessThanOrEqual(reference.x+reference.width+1);}
 expect(measured.overflow,label).toBe(false);return measured;
}

for(const language of ['en','zh'] as const)test(`responsive density, essential controls and text scaling (${language})`,async({page})=>{
 const fixture=await seed(page,language);await mkdir(output,{recursive:true});
 const results=[];
 const widths=phase==='before'?[390,1280]:[320,360,390,430,768,1280,1440];
 for(const scale of phase==='before'?[100]:[100,125,150]){
  fixture.prefs.text_scale_percent=scale;
  if(scale!==100)await page.reload();
  for(const width of scale===100?widths:[320,360,390]){
   await page.setViewportSize({width,height:width===360?800:width===320?640:width===430?932:844});
   for(const route of scale===100?['today','medicines','care-tasks','me','records','settings','privacy','reminder-settings','language-settings','accessibility']:['today','medicines','care-tasks','me','records']){
    await page.goto(`/#${route}`);await expect(page.locator('.app-header')).toBeVisible();
    await expect.poll(()=>page.evaluate(()=>document.documentElement.style.getPropertyValue('--font-scale'))).toBe(String(scale/100));
    if(route==='today')await expect(page.locator('#today-medication')).toBeVisible();
    if(route==='today')await expect(page.locator('#today-medication')).toContainText('DEMO Amlodipine');
    if(route==='medicines')await expect(page.locator('.medication-add-actions')).toBeVisible();
    const data=await metrics(page);results.push({route,scale,width,...data});
    if(phase!=='before'){
     expect(data.overflow,`${route} ${language} ${width} scale ${scale}`).toBe(false);
     const controls=page.locator('.header-quick-actions button');
     await expect(controls).toHaveCount(3);
     for(const control of await controls.all())await expect(control).toBeVisible();
     const headerBoxes=await page.locator('.app-header button:visible').evaluateAll(elements=>elements.map(element=>{const r=element.getBoundingClientRect();return {x:r.x,right:r.right,width:r.width,height:r.height};}));
     for(const box of headerBoxes){expect(box.x).toBeGreaterThanOrEqual(0);expect(box.right).toBeLessThanOrEqual(width+1);expect(box.width).toBeGreaterThanOrEqual(44);expect(box.height).toBeGreaterThanOrEqual(44);}
     if(route==='today'){
      const chips=page.locator('.today-assistant .assistant-tasks button');await expect(chips).toHaveCount(4);
      for(const chip of await chips.all())expect(await chip.evaluate(element=>getComputedStyle(element).display)).not.toBe('none');
      const composer=page.locator('.today-assistant .composer-row');
      const insets=await composer.evaluate(element=>{const outer=element.getBoundingClientRect();return ['.mic-button','.composer-send'].map(selector=>{const button=element.querySelector(selector)!.getBoundingClientRect();return {top:button.top-outer.top,bottom:outer.bottom-button.bottom,right:outer.right-button.right};});});
      for(const inset of insets){expect(inset.top).toBeGreaterThanOrEqual(4);expect(inset.bottom).toBeGreaterThanOrEqual(4);}
      expect(insets[1]!.right).toBeGreaterThanOrEqual(4);
      if(language==='zh'&&width===390&&scale===100)await composer.screenshot({path:path.join(output,'today-composer-inset-zh-390.png')});
      expect(await composer.evaluate(element=>getComputedStyle(element).columnGap)).toBe('10px');
      const gaps=await composer.evaluate(element=>Array.from(element.querySelectorAll('.photo-button,input:not([type=file]),.composer-allowance,.voice-inline,.composer-send')).filter(child=>child.getClientRects().length>0).map(child=>{const rect=child.getBoundingClientRect();return {left:rect.left,right:rect.right};}));
      for(let i=0;i<gaps.length-1;i++)expect(gaps[i+1]!.left-gaps[i]!.right).toBeGreaterThanOrEqual(9);
      const row=await composer.evaluate(element=>['.photo-button','input:not([type=file])','.mic-button','.composer-send'].map(selector=>{const b=element.querySelector(selector)!.getBoundingClientRect();return {x:b.x,y:b.y,width:b.width,height:b.height};}));
      expect(Math.max(...row.map(b=>b.y+b.height/2))-Math.min(...row.map(b=>b.y+b.height/2))).toBeLessThan(3);
      expect(row[0]!.width).toBeLessThanOrEqual(36);expect(row[2]!.width).toBeLessThanOrEqual(36);expect(row[2]!.height).toBeLessThanOrEqual(36);
      expect(await composer.locator('.photo-button svg').evaluate(element=>getComputedStyle(element).width)).toBe('14px');
      expect(await composer.locator('.mic-button svg').evaluate(element=>getComputedStyle(element).width)).toBe('16px');
      expect(row[1]!.width).toBeGreaterThan(60);
      for(let i=0;i<row.length-1;i++)expect(row[i]!.x+row[i]!.width).toBeLessThanOrEqual(row[i+1]!.x+1);
     }
     if(route==='records'){const contentBox=await page.locator('[data-app-content]').boundingBox();expect(data.summary!.width).toBeGreaterThan(Math.min(contentBox!.width-2,700));}
     if(route==='care-tasks'){
      const grid=page.locator('.care-calendar__grid');await expect(grid.locator('[role=columnheader]')).toHaveCount(7);
      expect(await grid.evaluate(element=>element.scrollWidth<=element.clientWidth),`${language} calendar ${width}px ${scale}%`).toBe(true);
     }
    }
    if((width===360||width===390||width===1280)&&['today','medicines','care-tasks','me','records'].includes(route))await page.screenshot({path:path.join(output,`${route}-${language}-${width}-${scale}.png`)});
   }
  }
 }
 await writeFile(path.join(output,`metrics-${language}.json`),JSON.stringify(results,null,2));
 expect(fixture.errors).toEqual([]);
});

test('mobile suggestions remain reachable and follow-up creation stays usable',async({page})=>{
 const fixture=await seed(page,'en');await page.setViewportSize({width:390,height:844});
 await page.goto('/#today');await expect(page.locator('#today-medication')).toContainText('DEMO Amlodipine');
 const strip=page.locator('.today-assistant .assistant-tasks');
 for(const action of await strip.getByRole('button').all())await expect(action).toBeVisible();
 expect(await strip.evaluate(element=>element.scrollWidth<=element.clientWidth)).toBe(true);
 const last=strip.getByRole('button',{name:'Prepare for a visit'});await last.focus();await last.click();
 await expect(page.locator('.today-assistant input:not([type=file])')).not.toHaveValue('');
 expect(fixture.writes).not.toContain('/api/agent/messages');
 for(const [width,height,scale] of [[390,844,100],[360,800,150]]){
  fixture.prefs.text_scale_percent=scale!;await page.setViewportSize({width:width!,height:height!});
  await page.goto('/#care-tasks');await page.reload();
  await page.locator('.care-task-page__header .primary').click();await expect(page.getByRole('dialog')).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  const dialog=page.getByRole('dialog');expect(await dialog.evaluate(element=>element.scrollWidth<=element.clientWidth)).toBe(true);
  await page.keyboard.press('Escape');await expect(dialog).toHaveCount(0);
 }
 expect(fixture.errors).toEqual([]);
});

test('reference empty and review-required compositions use actual UI states',async({page})=>{
 const fixture=await seed(page,'zh');fixture.setMedications([]);
 fixture.setDoseFollowUps({items:[],has_more:false,timezone:'Asia/Singapore',as_of:'2026-10-20T04:00:00Z'});
 await mkdir(output,{recursive:true});
 for(const width of [360,390,768,1280]){
  await page.setViewportSize({width,height:width===360?800:844});
  for(const route of ['today','medicines','records','me','care-tasks']){
   await page.goto(`/#${route}`);
   if(route==='today')await expect(page.locator('#today-medication')).toBeVisible();
   if(route==='medicines')await expect(page.locator('.medication-add-actions')).toBeVisible();
   expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
   await page.screenshot({path:path.join(output,`reference-${route}-zh-${width}.png`)});
  }
 }
 expect(fixture.errors).toEqual([]);
});

test('detail density, alignment and conversation controls follow the owner supplement',async({page})=>{
 const fixture=await seed(page,'zh');await mkdir(output,{recursive:true});
 for(const width of [360,390,430,1280]){
  await page.setViewportSize({width,height:width===360?800:844});
  await page.goto('/#today');await expect(page.locator('.today-confirmation-region')).toBeVisible();
  const pending=await page.locator('.today-confirmation-region').boundingBox();
  const actual=await page.locator('.today-overview--embedded').boundingBox();
  if(actual)expect(pending!.y).toBeGreaterThanOrEqual(actual.y+actual.height-1);
  if(width>=360&&width<=430){
   const heading=await page.locator('.today-assistant__heading h2').boundingBox(),open=await page.locator('.today-assistant__expand').boundingBox();
   expect(Math.abs(heading!.y+heading!.height/2-open!.y-open!.height/2)).toBeLessThan(2);
  }
  await page.locator('.today-assistant__expand').click();
  await expect(page).toHaveURL(/#assistant/);
  await page.screenshot({path:path.join(output,`workspace-opening-${width}.png`)});
  const shortcuts=page.locator('.conversation-workspace .workspace-tasks .assistant-tasks button');await expect(shortcuts).toHaveCount(4);
  if(width<768){const positions=await shortcuts.evaluateAll(elements=>elements.map(element=>element.getBoundingClientRect().y));expect(Math.max(...positions)-Math.min(...positions)).toBeLessThan(2);}
  await page.screenshot({path:path.join(output,`workspace-zh-${width}.png`)});
  await page.goto('/#medicines');await expect(page.locator('.medication-list-row').first()).toBeVisible();
  const medIcon=await page.locator('.medication-list-row__icon').first().boundingBox(),shortcutIcon=await page.locator('.medicine-shortcut .ui-row__icon').first().boundingBox();
  if(width<768)expect(Math.abs(medIcon!.x+medIcon!.width/2-shortcutIcon!.x-shortcutIcon!.width/2)).toBeLessThan(2);
  await page.goto('/#records');const boxes=await page.locator('.records-summary-actions button').evaluateAll(elements=>elements.map(element=>element.getBoundingClientRect().width));
  expect(Math.max(...boxes)-Math.min(...boxes)).toBeLessThan(1);
  expect(Math.min(...await page.locator('.records-summary-actions button').evaluateAll(elements=>elements.map(element=>element.getBoundingClientRect().height)))).toBeGreaterThan(0);
  for(const height of await page.locator('.records-summary-actions button').evaluateAll(elements=>elements.map(element=>element.getBoundingClientRect().height)))expect(height).toBeLessThanOrEqual(44);
  const pendingRecords=page.locator('.records-pending-disclosure');await pendingRecords.locator('summary').click();
  await expect(pendingRecords.locator('.late-dose-list button.primary')).toBeVisible();
  expect((await pendingRecords.locator('.late-dose-list button.primary').boundingBox())!.height).toBeLessThanOrEqual(44);
  await page.goto('/#reminder-settings');await expect(page.locator('.calendar-export-action')).toBeVisible();
  const exportBox=await page.locator('.calendar-export-action').boundingBox(),head=await page.locator('.ui-screen__head').boundingBox();
  expect(Math.abs(exportBox!.x+exportBox!.width-head!.x-head!.width)).toBeLessThan(2);
  for(const height of await page.locator('.device-notification-action').evaluateAll(elements=>elements.map(element=>element.getBoundingClientRect().height)))expect(height).toBeLessThanOrEqual(40);
  await page.screenshot({path:path.join(output,`reminders-zh-${width}.png`)});
  await page.goto('/#language-settings');
  for(const box of await page.locator('input[type=checkbox]').evaluateAll(elements=>elements.map(element=>element.getBoundingClientRect().width)))expect(box).toBeLessThanOrEqual(18);
  await page.screenshot({path:path.join(output,`language-zh-${width}.png`)});
  await page.goto('/#caregivers');await expect(page.locator('.app-header')).toBeVisible();await expect(page.locator('.care-contacts-add')).toBeVisible();
  await page.evaluate(()=>window.scrollTo({top:0,behavior:'instant'}));
  expect((await page.locator('.care-contacts-add').boundingBox())!.height).toBeLessThanOrEqual(40);
  await page.screenshot({path:path.join(output,`contacts-zh-${width}.png`)});
 }
 expect(fixture.errors).toEqual([]);
});

test('navigation uses bottom tabs only at narrow portrait widths',async({page})=>{
 const fixture=await seed(page,'zh');await mkdir(output,{recursive:true});
 for(const [width,height,rail] of [[360,800,false],[390,844,false],[430,932,false],[599,844,false],[600,844,true],[640,800,true],[768,1024,true],[844,390,true],[1023,844,true],[1280,844,true],[1880,1138,true],[568,320,true]] as const){
  await page.setViewportSize({width,height});await page.goto('/#medicines');await expect(page.locator('.medication-add-actions')).toBeVisible();
  const nav=page.locator('.patient-nav');
  const bounds=await nav.boundingBox();expect(bounds).not.toBeNull();
  expect(await nav.evaluate(element=>getComputedStyle(element).flexDirection)).toBe(rail?'column':'row');
  if(rail){expect(bounds!.x).toBe(0);expect(bounds!.y).toBe(0);expect(bounds!.height).toBe(height);expect(bounds!.width).toBeLessThan(230);
   const firstDestination=await nav.locator('button:not(.nav-assistant)').first().boundingBox();expect(firstDestination!.y).toBeGreaterThanOrEqual(48);
   const main=await page.locator('[data-app-content]').boundingBox();expect(main!.x).toBeGreaterThanOrEqual(bounds!.width);
  }else{expect(bounds!.width).toBe(width);expect(bounds!.y+bounds!.height).toBe(height);}
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:path.join(output,`navigation-${width}-${height}.png`)});
 }
 expect(fixture.errors).toEqual([]);
});

test('care task filters stay compact and list order puts pending before overdue',async({page})=>{
 const fixture=await seed(page,'en');await mkdir(output,{recursive:true});
 for(const width of [360,390,1280]){
  await page.setViewportSize({width,height:844});await page.goto('/#care-tasks');
  await expect(page.locator('.care-view-switch')).toBeVisible();
  const viewButtons=page.locator('.care-view-switch button'),statusButtons=page.locator('.care-status-filter--desktop button');
  for(const control of await statusButtons.all()){
   const box=await control.boundingBox();expect(box).not.toBeNull();expect(box!.height).toBe(36);expect(box!.width).toBeGreaterThanOrEqual(64);
  }
  expect((await page.locator('.care-task-page__header .primary').boundingBox())!.height).toBe(36);
  expect((await page.locator('.care-task-page__header .primary').boundingBox())!.width).toBeGreaterThanOrEqual(128);
  await viewButtons.nth(0).click();await expect(page.locator('.care-calendar')).toBeVisible();
  const switchStyle=await page.locator('.care-view-switch').evaluate(element=>getComputedStyle(element).backgroundColor);
  const selectedStyle=await viewButtons.nth(0).evaluate(element=>getComputedStyle(element,'::before').backgroundColor);
  expect(switchStyle).not.toBe('rgba(0, 0, 0, 0)');expect(selectedStyle).not.toBe('rgba(0, 0, 0, 0)');
  for(const height of await page.locator('.care-calendar__month button').evaluateAll(elements=>elements.map(element=>element.getBoundingClientRect().height)))expect(height).toBe(36);
  for(const height of await viewButtons.evaluateAll(elements=>elements.map(element=>element.getBoundingClientRect().height)))expect(height).toBe(36);
  if(width===390)await page.screenshot({path:path.join(output,'care-task-calendar-compact-390.png')});
  await viewButtons.nth(1).click();await expect(page.locator('.care-list-view')).toBeVisible();
  expect(await page.locator('.care-list-view > section').evaluateAll(elements=>elements.map(element=>element.getAttribute('aria-labelledby')))).toEqual(['care-list-pending','care-list-overdue','care-list-completed']);
  expect(await page.getByRole('button',{name:/DEMO medication review 1/}).count()).toBe(1);
  if(width===390||width===1280)await page.screenshot({path:path.join(output,`care-task-list-compact-${width}.png`)});
 }
 expect(fixture.errors).toEqual([]);
});

test('overview pages share Records content width in landscape and desktop',async({page})=>{
 await seed(page,'zh');await mkdir(output,{recursive:true});
 for(const width of [390,844,1280,1920,2560]){
  await page.setViewportSize({width,height:width===844?390:1000});
  await page.goto('/#records');await expect(page.locator('.records-screen')).toBeVisible();
  const reference=(await page.locator('.records-screen').boundingBox())!;
  for(const route of ['today','medicines','me']){
   await page.goto(`/#${route}`);await expect(page.locator('.app-header')).toBeVisible();
   const content=(await page.locator('[data-app-content]').boundingBox())!;
   expect(Math.abs(content.x-reference.x),`${route} left at ${width}`).toBeLessThan(1);
   expect(Math.abs(content.width-reference.width),`${route} width at ${width}`).toBeLessThan(1);
   expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
   if(width===2560)await page.screenshot({path:path.join(output,`${route}-records-width-2560.png`)});
  }
 }
});

test('child pages share Records width and centered card boundaries',async({page})=>{
 const fixture=await seed(page,'zh'),errors:string[]=[],results:unknown[]=[];page.on('pageerror',error=>errors.push(error.message));await mkdir(output,{recursive:true});
 const routes=['today','medicines','records','me','assistant','check','check-result','label','manual','unfinished','past-medicines','gallery','care-tasks','health-notes','adherence-barriers','medication-review','medication-records','summary-week','summary-month','summary-course','profile','account','caregivers','settings','reminder-settings','language-settings','accessibility','privacy','conversations','about','feedback','help'];
 for(const width of [844,2560]){
  await page.setViewportSize({width,height:width===844?390:1143});await page.goto('/?layout-audit=reference#records');await page.waitForLoadState('networkidle');
  const reference=(await page.locator('.records-screen').boundingBox())!;
  for(const route of routes){
   await page.goto(`/?layout-audit=${route}#${route}`);await page.waitForLoadState('networkidle');await expect(page.locator('.app-header'),route).toBeVisible();
   results.push({width,route,...await assertPageLayout(page,reference,`${route} ${width}`)});
   if(width===2560&&['assistant','reminder-settings','settings','conversations','profile'].includes(route))await page.screenshot({path:path.join(output,`shared-layout-${route}-2560.png`)});
  }
 }
 const demoPlan={regimen_id:'DEMO-plan-0',medication_id:'DEMO-med-0',display_name:'DEMO Amlodipine 10 mg',version_no:1,state:'active',effective_from:'2026-10-01T00:00:00Z',effective_to:null,course_start_date:null,course_end_date:null,dose_amount:1,dose_unit:'tablet',food_instruction:null,is_prn:false,local_times:['08:00'],frequency_rule:{kind:'daily',local_times:['08:00'],days_of_week:[]}} satisfies import('../src/api/client').RegimenHistoryItem;
 fixture.setPlans([demoPlan]);
 const stock={medication_id:'DEMO-med-0',unit:'tablet',last_confirmed_stock:null,last_confirmed_at:null,estimated_remaining:null,daily_requirement:null,estimated_days:null,low_stock:false,estimate_note:'DEMO stock is unknown',transactions:[]} satisfies import('../src/api/care').StockStatus;
 await page.route(url=>new URL(url).pathname==='/api/me/inventory/DEMO-med-0',route=>route.fulfill({json:stock}));
 await page.goto('/?layout-audit=selected#records');await page.waitForLoadState('networkidle');const reference=(await page.locator('.records-screen').boundingBox())!;
 await page.goto('/?layout-audit=selected#medicines');await page.waitForLoadState('networkidle');await page.locator('.medication-list-row').first().click();await expect(page).toHaveURL(/#medicine-detail/);
 for(const route of ['medicine-detail','medicine-history','medication-inventory','edit-medication']){
  await page.evaluate(value=>{location.hash=value==='edit-medication'?'medicine-detail':value;},route);await page.evaluate(()=>new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve()))));
  if(route==='edit-medication'){await page.getByRole('button',{name:'管理用药计划',exact:true}).click();await expect(page.locator('[data-page="edit-medication"] .card')).toBeVisible();}
  else await expect(page.locator('.app-main h1:visible'),route).toHaveCount(1);
  results.push({width:2560,route,...await assertPageLayout(page,reference,route)});
 }
 await writeFile(path.join(output,'shared-layout-pages.json'),JSON.stringify(results,null,2));expect(errors).toEqual([]);
});

for(const language of ['en','zh'] as const)test(`shared action button sizing across pages and dialogs (${language})`,async({page})=>{
 const browserErrors:string[]=[];page.on('pageerror',error=>browserErrors.push(error.message));
 await seed(page,language);const measurements:unknown[]=[],violations:unknown[]=[];let audited=0;
 async function audit(route:string,width:number){
  const controls=await page.locator('button:visible').evaluateAll(buttons=>buttons.filter(button=>{
   if(!button.isConnected||button.getClientRects().length===0)return false;
   if(button.closest('.app-header,.patient-nav'))return false;
   if(button.matches('.ui-row,.records-medication-history-link,.identity-card,.medication-add-action,.medication-list-row,.medicine-shortcut,.pending-medication-review,.medicine-chip,.care-list__button,.history-info-row,.history-switch,.patient-switch'))return false;
   return Boolean(button.textContent?.trim())&&!button.querySelector('small,p,h1,h2,h3,h4,.ui-row__hint');
  }).map(button=>{
   const style=getComputedStyle(button),rect=button.getBoundingClientRect(),lines=new Set<number>();
   const walker=document.createTreeWalker(button,NodeFilter.SHOW_TEXT);
   for(let node=walker.nextNode();node;node=walker.nextNode()){
    if(!node.textContent?.trim()||node.parentElement?.closest('.sr-only,[aria-hidden=true]'))continue;
    const range=document.createRange();range.selectNodeContents(node);
    for(const line of range.getClientRects())if(line.width>0&&line.height>0)lines.add(Math.round(line.top));
   }
   return {label:button.textContent?.trim(),classes:button.className,font:style.fontSize,minHeight:style.minHeight,height:rect.height,lines:lines.size,clipped:button.scrollHeight>button.clientHeight+1};
  }));
  measurements.push({route,width,controls});
  audited+=controls.length;
  for(const control of controls)if(control.font!=='12px'||control.minHeight!=='36px'||control.height<36||(control.lines<=1&&control.height>36.1)||control.clipped)violations.push({route,width,...control});
 }
 for(const width of [390,1280]){
  await page.setViewportSize({width,height:900});
  await page.goto('/?button-audit=reference#records');await page.waitForLoadState('networkidle');const reference=(await page.locator('.records-screen').boundingBox())!;
  for(const route of ['today','medicines','records','me','care-tasks','settings','privacy','reminder-settings','language-settings','accessibility','caregivers','health-notes','adherence-barriers','medication-review','medication-records','gallery','manual','assistant','profile','feedback','about']){
   await page.goto(`/?button-audit=${route}#${route}`);await page.waitForLoadState('networkidle');await expect(page.locator('.app-header'),route).toBeVisible({timeout:5000});await audit(route,width);
   await assertPageLayout(page,reference,`${route} ${language} ${width}`);
   if(language==='zh'&&width===390&&['today','records','reminder-settings','assistant'].includes(route))await page.screenshot({path:path.join(output,`buttons-unified-${route}-zh-390.png`)});
   if(route==='care-tasks'){await page.locator('.care-task-page__header .primary').click();await expect(page.locator('.care-flow')).toBeVisible();await audit('care-task-dialog',width);}
   if(route==='caregivers'){await page.locator('.care-contacts-add').click();await expect(page.locator('.bottom-sheet')).toBeVisible();await audit('caregiver-dialog',width);}
  }
 }
 await mkdir(output,{recursive:true});await writeFile(path.join(output,`button-sizing-${language}.json`),JSON.stringify(measurements,null,2));
 expect(violations).toEqual([]);
 expect(audited).toBeGreaterThan(200);
 expect(browserErrors).toEqual([]);
});

test('native browser zoom diagnosis with identical outer window size',async()=>{
 test.skip(process.env.DENSITY_ZOOM_AUDIT!=='1','Run explicitly for before/after native browser zoom evidence.');
 const context=await chromium.launchPersistentContext('',{headless:false,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',viewport:null,args:['--window-size=1280,900','--window-position=40,40']});
 try{
  const page=await context.newPage();await seed(page,'en');await page.goto('http://127.0.0.1:5174/#today');
  await expect(page.locator('#today-medication')).toContainText('DEMO Amlodipine');
  await page.evaluate(()=>{document.title='MediThread density zoom audit';});
  const records=[];await mkdir(output,{recursive:true});
  const settings=await context.newPage();await settings.goto('chrome://settings/appearance');
  await page.bringToFront();
  const baseDpr=await page.evaluate(()=>devicePixelRatio);
  const cdp=await context.newCDPSession(page);const {windowId}=await cdp.send('Browser.getWindowForTarget');
  // Chrome's native window has a minimum width. Exact mobile CSS viewports are tested above.
  for(const windowWidth of [1280]){
   await cdp.send('Browser.setWindowBounds',{windowId,bounds:{width:windowWidth,height:900}});
   let initialOuterWidth:number|undefined;
   for(const [zoom,steps] of [[1,0],[.75,3],[2/3,4]]){
    const select=settings.locator('#zoomLevel');
    await select.selectOption({label:steps===0?'100%':steps===3?'75%':'67%'});
    await expect.poll(()=>page.evaluate(()=>devicePixelRatio)).toBeCloseTo(baseDpr*zoom!,1);
    const measured=await metrics(page);initialOuterWidth??=measured.outerWidth;
    expect(measured.outerWidth).toBe(initialOuterWidth);
    records.push({zoom,requestedWindowWidth:windowWidth,...measured});await page.screenshot({path:path.join(output,`native-zoom-${measured.outerWidth}-${zoom}.png`)});
   }
  }
  await writeFile(path.join(output,'native-zoom.json'),JSON.stringify(records,null,2));
 }finally{await context.close();}
});
