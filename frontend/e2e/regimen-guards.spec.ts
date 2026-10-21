/** LOCAL browser + real application API over isolated synthetic memory stores. */
import {test,expect} from '@playwright/test';
import type {DraftCreateResponse,ConfirmChallengeResponse,MedicationListResponse} from '../src/api/client';

test.skip(process.env.RUN_LOCAL_REGIMEN_QA!=='1','Requires isolated synthetic QA servers; never run against patient data');

test('history opt-in, overlap conflict, explicit stop and understandable legacy records',async({page})=>{
 const pageErrors:string[]=[];page.on('pageerror',error=>pageErrors.push(error.message));
 const clientId=`DEMO-regimen-browser-${Date.now()}`;const query=`?client_id=${clientId}`;
 // Prevent accidental external auth, model or storage access in this test.
 await page.route('**/*',route=>['127.0.0.1','localhost'].includes(new URL(route.request().url()).hostname)?route.continue():route.abort());
 const start=await (await page.request.post('/api/demo/start',{data:{client_id:clientId}})).json() as {patient_id:string;session_id:string};
 const payload={medication_name:'DEMO Amlodipine',dose_amount:5,dose_unit:'mg',frequency_kind:'daily',frequency_local_times:['20:00']};
 const firstResponse=await page.request.post('/api/medications/drafts'+query,{data:payload});
 expect(firstResponse.status()).toBe(200);
 const first=await firstResponse.json() as DraftCreateResponse;
 expect((await page.request.post(`/api/medications/drafts/${first.source_id}/review${query}`,{data:{}})).status()).toBe(200);
 const challenge=await (await page.request.post(`/api/medications/drafts/${first.regimen_id}/challenge${query}&session_id=${start.session_id}`)).json() as ConfirmChallengeResponse;
 expect((await page.request.post('/api/medications/activate'+query,{data:{regimen_id:first.regimen_id,challenge_id:challenge.challenge_id,session_id:challenge.session_id,session_state:challenge.session_state,session_state_version:challenge.session_state_version}})).status()).toBe(200);
 const duplicate=await page.request.post('/api/medications/drafts'+query,{data:{...payload,dose_amount:10,is_prn:true,frequency_kind:null,frequency_local_times:[],food_instruction:'as needed'}});
 expect(duplicate.status()).toBe(409);expect((await duplicate.json()).code).toBe('REGIMEN_OVERLAP');

 await page.addInitScript(({clientId,start})=>{
  localStorage.setItem('pharmascan.client_id',clientId);
  localStorage.setItem('pharmascan.agent-session',start.session_id);
  localStorage.setItem(`pharmascan.quick-start.v4:${start.patient_id}`,JSON.stringify({version:4,status:'skipped',step:0}));
 },{clientId,start});
 await page.goto('/');
 const skip=page.getByRole('button',{name:'Skip for now'});if(await skip.isVisible())await skip.click();
 await page.getByLabel('Review your message before sending').focus();
 const dialog=page.locator('.conversation-workspace');await expect(dialog).toBeVisible();
 await dialog.getByText('Saved conversations',{exact:true}).click();
 const toggle=dialog.getByRole('checkbox',{name:'Save new conversations on this account'});
 const saved=page.waitForResponse(response=>response.request().method()==='PUT'&&response.url().includes('/api/me/preferences'));
 await toggle.click();expect((await saved).status()).toBe(200);await expect(toggle).toBeChecked();
 await expect(dialog.getByText('Saving is on. New conversations will be stored on this account.')).toBeVisible();
 await dialog.getByLabel('Review your message before sending').fill('DEMO show my medication plan');
 const reply=page.waitForResponse(response=>response.request().method()==='POST'&&response.url().includes('/api/agent/messages'));
 await dialog.getByRole('button',{name:'Send',exact:true}).click();expect((await reply).status()).toBe(200);
 await expect.poll(async()=>{
  const history=await (await page.request.get('/api/agent/history'+query)).json() as {entries:{user_text:string}[]};
  return history.entries.some(row=>row.user_text==='DEMO show my medication plan');
 }).toBe(true);
 await page.reload();await page.getByLabel('Review your message before sending').focus();
 await dialog.getByText('Saved conversations',{exact:true}).click();await expect(toggle).toBeChecked();
 await expect(dialog.locator('.conversation-history').getByText('DEMO show my medication plan',{exact:true})).toBeVisible();
 await toggle.scrollIntoViewIfNeeded();
 await page.screenshot({path:'../outputs/regimen-fix/history-saving-390.png',fullPage:true});
 await dialog.getByRole('button',{name:'Back'}).click();

 // Explicit UI-only mock for legacy duplicate records. New API writes above
 // cannot create this state; no database rows are inserted to manufacture it.
 const medications=await (await page.request.get('/api/me/medications'+query)).json() as MedicationListResponse;
 const original=medications.medications[0]!;
 await page.route('**/api/me/medications*',route=>route.fulfill({json:{...medications,medications:[original,{...original,medication_id:'DEMO-legacy-med',regimen_id:'DEMO-legacy-plan',dose_amount:10,is_prn:true}]}}));
 await page.reload();await expect(page.getByText(/Multiple recorded plans have the same medicine name/)).toBeVisible();
 await expect(page.getByText('2 medication plans')).toBeVisible();await expect(page.getByText(/Plan 1/)).toHaveCount(0);
 await page.screenshot({path:'../outputs/regimen-fix/legacy-plans-390.png',fullPage:true});
 expect((await page.request.put('/api/me/preferences'+query,{data:{preferred_language:'zh'}})).status()).toBe(200);
 await page.reload();await expect(page.getByText('2 项用药计划')).toBeVisible();
 await page.screenshot({path:'../outputs/regimen-fix/legacy-plans-zh-390.png',fullPage:true});

 expect((await page.request.post(`/api/medications/${first.regimen_id}/end${query}`,{data:{confirmed:true}})).status()).toBe(200);
 expect((await page.request.post('/api/medications/drafts'+query,{data:{...payload,dose_amount:10}})).status()).toBe(200);
 expect(pageErrors).toEqual([]);
});
