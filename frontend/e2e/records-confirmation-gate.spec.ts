/** Real local API and confirmation lifecycle; synthetic patient only. */
import {test,expect} from '@playwright/test';
import {mockPatientApp} from './polish-a1-fixture';
test('a reviewed but unconfirmed draft stays out of Records until explicit activation',async({page,baseURL})=>{
 test.setTimeout(60000);page.setDefaultTimeout(10000);expect(new URL(baseURL!).origin).toBe('http://127.0.0.1:5182');await mockPatientApp(page,true,{token:'DEMO.confirmation-session-token',owner:'00000000-0000-0000-0000-000000067932'});
 await page.route(url=>new URL(url).pathname.startsWith('/api/'),route=>route.continue());
 const headers={Authorization:'Bearer DEMO.confirmation-session-token'};
 await page.request.put('/api/me/preferences',{headers,data:{preferred_language:'en',text_scale_percent:100,reminders_enabled:false}});
 await page.goto('/');await page.locator('[data-guide="medicines"]').click();await page.getByRole('button',{name:/Add medication/}).click();await page.getByRole('button',{name:/Add manually/}).click();
 await page.getByLabel('Medication name',{exact:true}).fill('DEMO confirmation gate');await page.getByLabel('Dose amount',{exact:true}).fill('1');
 await page.getByRole('button',{name:'Review and add',exact:true}).click();await page.getByLabel('I have checked these details against my original instructions.').check();
 const created=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/medications/drafts'&&response.request().method()==='POST');
 await page.getByRole('button',{name:'Add this medication',exact:true}).click();const draft=await (await created).json() as {medication_id:string;regimen_id:string};
 await page.getByRole('dialog').getByRole('button',{name:'Cancel',exact:true}).click();
 await page.locator('[data-guide="records"]').click();await expect(page.getByLabel('Medicine',{exact:true}).locator('option').filter({hasText:'DEMO confirmation gate'})).toHaveCount(0);
 const catalogue=await page.request.get('/api/me/medication-history/catalogue',{headers});const before=await catalogue.json() as {medications:{id:string}[];plans:{id:string}[]};
 expect(before.medications.some(row=>row.id===draft.medication_id)).toBe(false);expect(before.plans.some(row=>row.id===draft.regimen_id)).toBe(false);
 expect((await page.request.get(`/api/me/medication-history?regimen_id=${draft.regimen_id}`,{headers})).status()).toBe(404);
 await page.locator('[data-guide="medicines"]').click();await page.getByRole('button',{name:/Finish medication setup/}).click();await page.getByRole('button',{name:/DEMO confirmation gate/}).click();
 await page.getByRole('button',{name:'Review and add',exact:true}).click();await page.getByLabel('I have checked these details against my original instructions.').check();await page.getByRole('button',{name:'Add this medication',exact:true}).click();
 await page.getByRole('button',{name:'Yes, save this medication',exact:true}).click();await expect(page.getByText('Medication added. It now appears in your medication list.',{exact:true})).toBeVisible();
 await page.locator('[data-guide="records"]').click();await expect(page.getByLabel('Medicine',{exact:true}).locator('option').filter({hasText:'DEMO confirmation gate'})).toHaveCount(1);
 await page.getByLabel('Medicine',{exact:true}).selectOption('demo confirmation gate');await expect(page.getByLabel('Medication plan',{exact:true}).locator('option')).toHaveCount(2);
});
