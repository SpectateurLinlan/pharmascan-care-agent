/** Actual Chrome/SDK and Vite module graph; synthetic HTTP/Auth only. No patient data. */
import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
import {mockPatientApp} from './polish-a1-fixture';
import type {MedicationSummary} from '../src/api/client';

const medicine:MedicationSummary={medication_id:'DEMO-med',regimen_id:'DEMO-plan',display_name:'PRIVATE_SYNTHETIC_NAME',is_prn:false,version_no:1,identity_status:'unknown',source_backed:false};
test('local diagnostic uses the existing SDK, ignores duplicate stored sessions and prints no records',async({page})=>{
 const mock=await mockPatientApp(page);mock.setMedications([medicine]);
 await page.goto('/#medicines');await expect(page.getByText('PRIVATE_SYNTHETIC_NAME',{exact:true})).toBeVisible();
 await expect.poll(()=>page.evaluate(()=>typeof window.medithreadMedicationCounts)).toBe('function');
 await page.evaluate(()=>{localStorage.setItem('sb-unrelated-auth-token',JSON.stringify({access_token:'PRIVATE_UNRELATED_TOKEN',expires_at:1}));});
 const calls:string[]=[];
 page.on('request',request=>{if(request.url().includes('/auth/v1/'))calls.push(request.url());});
 const result=await page.evaluate(async()=>window.medithreadMedicationCounts!());
 expect(result.result).toBe('complete');expect(result.endpoints[0]?.item_count).toBe(1);
 expect(JSON.stringify(result)).not.toMatch(/PRIVATE|DEMO-med|DEMO-plan|synthetic-session-token/);
 expect(calls.filter(url=>/signup|token/.test(new URL(url).pathname))).toEqual([]);
 const printed:string[]=[];
 page.on('console',message=>{if(message.type()==='table'||message.text().startsWith('MediThread read-only diagnostic:'))printed.push(message.text());});
 await page.addScriptTag({content:readFileSync(new URL('../../scripts/qa/medication_counts_in_browser.js',import.meta.url),'utf8')});
 await expect.poll(()=>printed.some(line=>line.includes('MediThread read-only diagnostic: complete'))).toBe(true);
 expect(printed.join('\n')).not.toMatch(/PRIVATE|synthetic-session-token/);
 expect(mock.errors).toEqual([]);
});

test('SDK refresh settles before diagnostic reads; 401 and 503 are not false signed-out conclusions',async({page})=>{
 const mock=await mockPatientApp(page);mock.setMedications([medicine]);
 await page.goto('/#medicines');await expect(page.getByText('PRIVATE_SYNTHETIC_NAME',{exact:true})).toBeVisible();
 await expect.poll(()=>page.evaluate(()=>typeof window.medithreadMedicationCounts)).toBe('function');
 let refreshes=0;
 await page.route(url=>new URL(url).pathname.endsWith('/auth/v1/token'),async route=>{
  refreshes++;
  const stored=await page.evaluate(()=>JSON.parse(localStorage.getItem('supabase.auth.token')??'{}'));
  await route.fulfill({json:{access_token:'DEMO.synthetic-session-token',refresh_token:'DEMO.refresh',token_type:'bearer',expires_in:3600,user:stored.user}});
 });
 await page.evaluate(()=>{const session=JSON.parse(localStorage.getItem('supabase.auth.token')??'{}');session.expires_at=1;session.access_token='PRIVATE_EXPIRED_TOKEN';localStorage.setItem('supabase.auth.token',JSON.stringify(session));});
 const refreshed=await page.evaluate(async()=>window.medithreadMedicationCounts!());
 expect(refreshed.result).toBe('complete');expect(refreshes).toBe(1);
 await page.route(url=>new URL(url).pathname==='/api/me/medications',route=>route.fulfill({status:401,json:{code:'AUTH_REQUIRED',message:'PRIVATE',rule_id:null}}));
 await page.route(url=>new URL(url).pathname==='/api/me/regimens',route=>route.fulfill({status:503,json:{code:'PROVIDER_UNAVAILABLE',message:'PRIVATE',rule_id:null}}));
 const report=await page.evaluate(async()=>window.medithreadMedicationCounts!());
 expect(report.result).toBe('partial');expect(report.endpoints.map(row=>row.status)).toEqual([401,503]);expect(JSON.stringify(report)).not.toContain('PRIVATE');
 expect(mock.errors).toEqual([]);
});

test('observes ordinary Today and Alerts failures without issuing diagnostic probes to them',async({page})=>{
 const mock=await mockPatientApp(page);mock.setMedications([medicine]);mock.prefs.reminders_enabled=true;
 await page.route(url=>new URL(url).pathname==='/api/me/today-attention',route=>route.fulfill({status:401,json:{code:'AUTH_REQUIRED',message:'Could not verify the access token with the identity provider',rule_id:null}}));
 await page.route(url=>new URL(url).pathname==='/api/reminders/alerts',route=>route.fulfill({status:503,json:{code:'PROVIDER_UNAVAILABLE',message:'Identity verification service is temporarily unavailable.',rule_id:null}}));
 await Promise.all([
  page.waitForResponse(response=>new URL(response.url()).pathname==='/api/me/today-attention'&&response.status()===401),
  page.waitForResponse(response=>new URL(response.url()).pathname==='/api/reminders/alerts'&&response.status()===503),
  page.goto('/#today'),
 ]);
 await expect.poll(()=>page.evaluate(()=>typeof window.medithreadMedicationCounts)).toBe('function');
 const before=mock.reads.filter(url=>/today-attention|reminders\/alerts/.test(url)).length;
 const report=await page.evaluate(async()=>window.medithreadMedicationCounts!());
 expect(report.observed_requests).toContainEqual({endpoint:'/api/me/today-attention',status:401,authorization_attached:true,failure_stage:'legacy_identity_service_failure_401'});
 expect(report.observed_requests).toContainEqual({endpoint:'/api/reminders/alerts',status:503,authorization_attached:true,failure_stage:'identity_service_unavailable'});
 expect(mock.reads.filter(url=>/today-attention|reminders\/alerts/.test(url))).toHaveLength(before);
 expect(mock.errors).toEqual([]);
});
