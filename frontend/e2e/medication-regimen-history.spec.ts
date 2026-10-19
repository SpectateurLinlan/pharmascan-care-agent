/** DEMO_ONLY browser journey: synthetic authenticated API data, no live patient records. */
import {expect,test} from '@playwright/test';
import {mockPatientApp} from './polish-a1-fixture';
import type {MedicationSummary,RegimenHistoryItem} from '../src/api/client';

const regimen=(overrides:Partial<RegimenHistoryItem>&Pick<RegimenHistoryItem,'regimen_id'|'display_name'|'state'>):RegimenHistoryItem=>({
 regimen_id:overrides.regimen_id,display_name:overrides.display_name,state:overrides.state,
 medication_id:'DEMO-med-amlodipine',supersedes_id:null,version_no:1,effective_from:null,effective_to:null,
 course_start_date:null,course_end_date:null,dose_amount:1,dose_unit:'tablet',food_instruction:null,
 is_prn:false,local_times:['08:00'],...overrides,
});
const medication:MedicationSummary={medication_id:'DEMO-med-amlodipine',regimen_id:'DEMO-active',display_name:'DEMO Amlodipine',is_prn:false,version_no:3,identity_status:'unknown',source_backed:false,dose_amount:1,dose_unit:'tablet',frequency_rule:{kind:'daily',local_times:['08:00'],days_of_week:[]}};
const rows=[
 regimen({regimen_id:'DEMO-ended-amlodipine',display_name:'DEMO Amlodipine',state:'ended',course_start_date:'2026-08-01',course_end_date:'2026-09-15'}),
 regimen({regimen_id:'DEMO-ended-metformin',display_name:'DEMO Metformin',state:'ended',course_start_date:'2026-07-10',course_end_date:'2026-08-22'}),
 regimen({regimen_id:'DEMO-superseded-nifedipine',display_name:'DEMO Nifedipine LA',state:'superseded',course_start_date:'2026-04-12',course_end_date:'2026-05-30'}),
 regimen({regimen_id:'DEMO-active-old-end',display_name:'DEMO Current Amlodipine',state:'active',course_start_date:'2026-01-01',course_end_date:'2026-02-01'}),
 regimen({regimen_id:'DEMO-future',display_name:'DEMO Planned medication',state:'active',course_start_date:'2099-01-01'}),
 regimen({regimen_id:'DEMO-draft',display_name:'DEMO Draft medication',state:'draft'}),
];

test('an active plan past its planned end stays discoverable across library and browser history',async({page})=>{
 const mock=await mockPatientApp(page);
 mock.setMedications([{...medication,course_start_date:'2020-01-01',course_end_date:'2020-02-01'}]);
 mock.setPlans([regimen({regimen_id:medication.regimen_id,display_name:medication.display_name,state:'active',course_start_date:'2020-01-01',course_end_date:'2020-02-01'})]);
 await page.goto('/#medicines');
 await expect(page.locator('.current-medications-card .medication-list-row')).toHaveCount(0);
 await expect(page.getByRole('button',{name:/Regimen Records/})).toContainText('1 courses');
 await page.getByRole('button',{name:'Medication Library'}).click();
 await expect(page.getByRole('heading',{name:'My Medication Library'})).toBeVisible();
 await page.goBack();await expect(page.locator('.current-medications-card .medication-list-row')).toHaveCount(0);
 await page.goForward();await expect(page.getByRole('heading',{name:'My Medication Library'})).toBeVisible();
 await page.reload();await expect(page.getByRole('heading',{name:'My Medication Library'})).toBeVisible();
 expect(mock.errors).toEqual([]);
});

test('history filters stay mounted across genuine Back/Forward and direct refresh restores records',async({page,browser})=>{
 const mock=await mockPatientApp(page);mock.setMedications([medication]);mock.setPlans([...rows,regimen({regimen_id:'DEMO-active',display_name:'DEMO Amlodipine',state:'active',supersedes_id:'DEMO-superseded-nifedipine',version_no:2})]);
 await page.route('**/api/me/inventory/DEMO-med-amlodipine*',route=>route.fulfill({json:{medication_id:'DEMO-med-amlodipine',unit:null,last_confirmed_stock:null,last_confirmed_at:null,estimated_remaining:null,daily_requirement:null,estimated_days:null,low_stock:false,estimate_note:'DEMO synthetic no stock records',transactions:[]}}));
 await page.goto('/');await page.locator('[data-guide="medicines"]').click();const historyShortcut=page.getByRole('button',{name:/Regimen Records/});await expect(historyShortcut).toContainText('5 courses');await historyShortcut.click();
 await expect(page.getByRole('heading',{name:'Regimen Records'})).toBeVisible();
 await expect(page.locator('.regimen-history-card')).toHaveCount(5); // All confirmed chain tips, including the active successor, remain available
 await expect(page.getByRole('button',{name:/DEMO Amlodipine/}).first()).toBeVisible();
 await expect(page.getByRole('button',{name:/DEMO Metformin/})).toBeVisible();
 await expect(page.getByText('DEMO Current Amlodipine')).toHaveCount(1);await expect(page.getByText('DEMO Planned medication')).toHaveCount(1);
 const search=page.getByRole('searchbox',{name:'Search medication name'});await search.fill('amlodipine');await expect(page.locator('.regimen-history-card')).toHaveCount(3);
 await page.getByRole('button',{name:/DEMO Amlodipine Ended.*View Regimen Details/}).click();
 await expect(page).toHaveURL(/#medicine-detail/);await expect(page.getByTestId('regimen-history-page')).toBeHidden();
 await page.goBack();await expect(page.getByRole('heading',{name:'Regimen Records'})).toBeVisible();await expect(page).toHaveURL(/#past-medicines/);
 await expect(search).toHaveValue('amlodipine');await expect(page.locator('.regimen-history-card')).toHaveCount(3);
 await page.goForward();await expect(page.getByTestId('regimen-history-page')).toBeHidden();
 await page.getByRole('button',{name:'Back'}).click();await expect(page.getByRole('heading',{name:'Regimen Records'})).toBeVisible();await expect(search).toHaveValue('amlodipine');
 const directContext=await browser.newContext({viewport:{width:390,height:844}}),direct=await directContext.newPage();
 const directMock=await mockPatientApp(direct);directMock.setMedications([medication]);directMock.setPlans([...rows,regimen({regimen_id:'DEMO-active',display_name:'DEMO Amlodipine',state:'active',supersedes_id:'DEMO-superseded-nifedipine',version_no:2})]);
 await direct.route('**/api/me/inventory/DEMO-med-amlodipine*',route=>route.fulfill({json:{medication_id:'DEMO-med-amlodipine',unit:null,last_confirmed_stock:null,last_confirmed_at:null,estimated_remaining:null,daily_requirement:null,estimated_days:null,low_stock:false,estimate_note:'DEMO synthetic no stock records',transactions:[]}}));
 await direct.goto('/#past-medicines');await expect(direct.getByRole('heading',{name:'Regimen Records'})).toBeVisible();await expect(direct.locator('.regimen-history-card')).toHaveCount(5);
 await direct.reload();await expect(direct.getByRole('heading',{name:'Regimen Records'})).toBeVisible();await expect(direct.locator('.regimen-history-card')).toHaveCount(5);
 expect(await direct.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await expect(direct.getByRole('searchbox',{name:'Search medication name'})).toBeVisible();await expect(direct.getByLabel('Filter by status')).toBeVisible();await expect(direct.getByLabel('Sort regimens')).toBeVisible();
 expect(directMock.errors).toEqual([]);expect(directMock.writes.filter(path=>path!=='/api/demo/start')).toEqual([]);await directContext.close();
 // App bootstrap and the unrelated background care-task refresh are expected;
 // filtering/history reads must not write regimen lifecycle records.
 expect(mock.errors).toEqual([]);expect(mock.writes.filter(path=>!['/api/demo/start','/api/me/care-tasks/refresh'].includes(path))).toEqual([]);
});
