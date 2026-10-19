/** Actual App/components; DEMO_ONLY intercepted Auth/API, not real OCR extraction. */
import {test,expect} from '@playwright/test';
import {mockPatientApp} from './polish-a1-fixture';
import type {SourcePreview,EvidenceTask} from '../src/api/client';

test('unstructured OCR candidates remain visible and unconfirmed in the real enrollment flow',async({page})=>{
 test.setTimeout(45000);
 const {errors,prefs,writes}=await mockPatientApp(page);
 prefs.preferred_language='zh';
 const task:EvidenceTask={id:'DEMO-source-task',medication_id:'DEMO-med',version:1,status:'pending_information',product:{name:'DEMO 示例药品',strength:'500 mg',dose_form:null,formulation:null,brand:null,ingredients:[],category:'unknown',verification:'source_supplied'},source_ids:['DEMO-source'],missing:['schedule'],conflicts:[],possible_duplicate_ids:[],draft_regimen_id:null,suggested_regimen:{medication_name:'DEMO 示例药品',dose_amount:1,dose_unit:'tablet',frequency_rule:null,is_prn:false,food_instruction:null}};
 const preview:SourcePreview={source_document_id:'DEMO-source',source_kind:'prescription',provider:'DEMO_ONLY fixture',extraction_model:'DEMO_ONLY',review_required:true,note:'DEMO_ONLY synthetic source',candidates:[{product:{name:'DEMO 示例药品',strength:'500 mg',source_lines:['DEMO ER tablet. Take one tablet at 20:00. For 7 days.']},review_status:'extracted',can_activate_regimen:false,regimen_evidence:{directions:null,dose_amount:null,frequency:null,administration_times:null,duration:null}}]};
 await page.route('**/api/evidence/tasks**',route=>{
  const path=new URL(route.request().url()).pathname;
  return route.fulfill({json:path.endsWith('/sources')?[{id:'DEMO-source',source_kind:'prescription',review_status:'extracted',extraction_evidence:preview}]:path.endsWith('/DEMO-source-task')?task:[task]});
 });
 await page.goto('/');await page.locator('[data-guide="medicines"]').click();
 await page.getByRole('button',{name:/完成药物设置|项药物设置待核对/}).click();
 await page.getByRole('button',{name:/DEMO 示例药品/}).click();
 const hint=page.getByRole('region',{name:'原始标签待核对信息'}).last();
 await expect(hint).toContainText('ER');await expect(hint).toContainText('20:00');await expect(hint).toContainText('For 7 days');
 await expect(page.getByLabel('用药时间 1',{exact:true})).toHaveValue('');
 await expect(page.getByRole('button',{name:'继续确认用药计划'})).toBeDisabled();
 for(const width of [390,1280]){
  await page.setViewportSize({width,height:1000});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:`../outputs/release/ocr-review-${width}.png`,fullPage:true});
 }
 await page.getByLabel('用药时间 1',{exact:true}).fill('20:00');
 expect(writes.filter(path=>!['/api/demo/start','/api/me/care-tasks/refresh'].includes(path))).toEqual([]);expect(errors).toEqual([]);
});
