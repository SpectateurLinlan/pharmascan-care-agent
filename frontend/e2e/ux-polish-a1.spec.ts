/** DEMO_ONLY real App/browser, isolated Auth and patient HTTP fixtures. */
import {test,expect} from '@playwright/test';
import {mockPatientApp} from './polish-a1-fixture';
import type {MedicationSummary,RegimenHistoryItem,ReviewSummary} from '../src/api/client';
import {writeFileSync} from 'node:fs';

test('same-condition visual evidence for four dashboard surfaces',async({page})=>{
 const {errors}=await mockPatientApp(page);
 await page.goto('/e2e/patient-feedback.html?shell=1');
 for(const width of [390,1280,1920]){
  await page.setViewportSize({width,height:1000});
  for(const destination of ['today','medicines','records','me']){
   await page.locator(`[data-guide="${destination}"]`).click();
   await expect(page.locator('.app-main')).toBeVisible();
   await page.screenshot({path:`../outputs/polish-a1-${process.env.UX_CAPTURE_PHASE??'after'}-${destination}-${width}.png`,fullPage:true});
   expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  }
 }
 expect(errors).toEqual([]);
});

test('all root pages share the viewport baseline at enlarged fonts and zoom-equivalent widths',async({page})=>{
 test.setTimeout(120000);const mock=await mockPatientApp(page);const measurements:object[]=[];
 for(const language of ['en','zh'])for(const font of [100,150]){
  mock.prefs.preferred_language=language;mock.prefs.text_scale_percent=font;
  await page.goto('/e2e/patient-feedback.html?shell=1');
  // Effective CSS widths exercise browser-zoom reflow, not native zoom controls.
  for(const width of [390,430,768,1024,1280,1600,1920,Math.round(1280/1.25),Math.round(1280/1.5)]){
   await page.setViewportSize({width,height:1000});
   for(const destination of ['today','medicines','records','me']){
    await page.locator(`[data-guide="${destination}"]`).click();
    const metric=await page.evaluate(()=>{
     const main=document.querySelector('.app-main')!,header=document.querySelector('.app-header')!;
     const m=main.getBoundingClientRect(),h=header.getBoundingClientRect(),style=getComputedStyle(header);
     return {width:innerWidth,contentWidth:m.width,mainLeft:m.left,headerStart:h.left+parseFloat(style.paddingLeft),canvas:getComputedStyle(document.body).backgroundColor};
    });
    expect(Math.abs(metric.mainLeft-metric.headerStart)).toBeLessThan(2);
    expect(metric.contentWidth).toBeLessThanOrEqual(1201);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    measurements.push({language,font,destination,...metric});
    if(language==='zh'&&font===150&&[390,1280].includes(width))await page.screenshot({path:`../outputs/polish-a1-zh150-${destination}-${width}.png`,fullPage:true});
   }
  }
 }
 writeFileSync('../outputs/polish-a1-layout-measurements.json',JSON.stringify(measurements,null,2));
 expect(mock.errors).toEqual([]);
});

const medicine=(i:number):MedicationSummary=>({medication_id:`DEMO-med-${i}`,regimen_id:`DEMO-plan-${i}`,display_name:`DEMO synthetic long medicine name ${i} / ${'extended name '.repeat(2)}`,dose_amount:1,dose_unit:'tablet',is_prn:false,version_no:1,identity_status:'user_reviewed_document',source_backed:true,frequency_rule:{kind:'daily',local_times:['08:00'],days_of_week:[]}});
const plan:RegimenHistoryItem={...medicine(0),effective_from:'2026-10-01T00:00:00Z',effective_to:null,state:'active',course_start_date:null,course_end_date:null,food_instruction:null,dose_amount:1,dose_unit:'tablet',local_times:['08:00']};

test('responsive data volumes, languages, enlarged text and readable navigation',async({page})=>{
 test.setTimeout(120000);const mock=await mockPatientApp(page);
 for(const language of ['en','zh'])for(const font of [100,150]){
  mock.prefs.preferred_language=language;mock.prefs.text_scale_percent=font;
  for(const count of [0,1,2,5,10]){
   mock.setMedications(Array.from({length:count},(_,i)=>medicine(i)));
   await page.goto('/e2e/patient-feedback.html?shell=1');
   for(const width of [390,430,768,1024,1280,1600,1920]){
    await page.setViewportSize({width,height:1000});await page.locator('[data-guide="medicines"]').click();
    await expect(page.locator('.medicine-shortcuts button')).toHaveCount(3);
    await expect(page.locator('.medicine-shortcuts')).toBeVisible();
    // Medication rows retain every real fetched item, including long names.
    await expect(page.locator('.ui-screen--medicines .ui-row')).toHaveCount(count);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    if([0,1,5,10].includes(count)&&[390,1280,1920].includes(width)){
     await page.locator('[data-guide="today"]').click();
     if(count>1)await expect(page.locator('.medicine-list-row')).toHaveCount(count);
     const overflow=await page.evaluate(()=>[...document.querySelectorAll('main *')].filter(el=>el.getBoundingClientRect().right>innerWidth+1).map(el=>({tag:el.tagName,class:el.className,right:el.getBoundingClientRect().right})).slice(0,12));
     expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),JSON.stringify({width,font,language,count,overflow})).toBe(true);
     if(count===10&&font===150&&language==='zh'&&width===1280)await page.screenshot({path:'../outputs/polish-a1-today-ten-zh150-1280.png',fullPage:true});
    }
   }
  }
 }
 expect(mock.errors).toEqual([]);
});

test('history scope, stable plan selection, progressive records and summary actions',async({page})=>{
 const mock=await mockPatientApp(page);mock.setPlans([plan,{...plan,regimen_id:'DEMO-previous',version_no:2,state:'superseded',effective_from:'2026-09-01T00:00:00Z'}]);
 for(const count of [0,1,5,20]){
  mock.setEvents(Array.from({length:count},(_,i)=>({occurrence_id:`DEMO-${i}`,due_at:new Date(Date.UTC(2026,9,16,0,i)).toISOString(),reported:i%4!==3,intake_status:['reported_taken','reported_not_taken','unsure',null][i%4]!,visual_status:null})));
  await page.goto('/e2e/patient-feedback.html?shell=1');await page.locator('[data-guide="records"]').click();
  const history=page.locator('.record-history');await expect(history.locator('.history li')).toHaveCount(Math.min(5,count));
  for(let n=5;n<count;n+=5)await history.getByRole('button',{name:'Load more records'}).click();
  await expect(history.locator('.history li')).toHaveCount(count);
  await expect(history.getByRole('button',{name:'Load more records'})).toHaveCount(0);
  await page.getByLabel('Medication plan',{exact:true}).selectOption('DEMO-previous');
  await expect(history.locator('.history li')).toHaveCount(Math.min(5,count));
 }
 for(const [label,period] of [['This week','week'],['This month','month'],['By medication plan','course']]){
  await page.locator('[data-guide="records"]').click();await page.getByRole('button',{name:label,exact:true}).click();
  await expect(page.getByText('Record-based report',{exact:true})).toBeVisible();
  expect(mock.reads.some(url=>new URL(url).searchParams.get('period')===period)).toBe(true);
 }
});

test('short, medium and long report disclosure, desktop scroll, mobile flow and complete exports',async({page})=>{
 const mock=await mockPatientApp(page);
 for(const count of [1,8,40]){
  const data:ReviewSummary={period:'week',window_start:'2026-10-10T00:00:00Z',window_end:'2026-10-17T00:00:00Z',generated_at:'2026-10-17T00:00:00Z',timezone:'Asia/Singapore',reported_taken:2,reported_not_taken:1,unsure:1,questions:['DEMO question'],coverage_note:'No report is not a missed dose.',medications:[],observations:Array.from({length:count},(_,i)=>({id:`DEMO-note-${i}`,patient_id:'DEMO-patient',severity:null,notes:null,medication_id:null,source:'patient_reported',created_at:'2026-10-16T00:00:00Z',updated_at:'2026-10-16T00:00:00Z',demo_only:true,occurred_at:'2026-10-16T00:00:00Z',description:`DEMO observation ${i} ${'readable synthetic note '.repeat(8)}`}))};
  mock.setReport(data);await page.goto('/e2e/patient-feedback.html?shell=1');await page.locator('[data-guide="records"]').click();await page.getByRole('button',{name:'This week',exact:true}).click();
  await page.getByText('Detailed records and sources',{exact:true}).click();
  const reader=page.getByRole('region',{name:'Detailed records and sources'});await expect(reader).toContainText(`DEMO observation ${count-1}`);
  await page.setViewportSize({width:1920,height:1000});expect(await reader.evaluate(el=>getComputedStyle(el).overflowY)).toBe('auto');
  await page.setViewportSize({width:390,height:844});expect(await reader.evaluate(el=>getComputedStyle(el).overflowY)).not.toBe('auto');
  const download=page.waitForEvent('download');await page.getByRole('button',{name:'Export summary',exact:true}).click();
  const file=await download;const stream=await file.createReadStream();const chunks:Buffer[]=[];for await(const chunk of stream)chunks.push(Buffer.from(chunk));expect(Buffer.concat(chunks).toString('utf8')).toContain(`DEMO observation ${count-1}`);
 }
 expect(mock.errors).toEqual([]);
});
