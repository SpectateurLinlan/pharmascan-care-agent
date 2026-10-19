/** Actual App -> local FastAPI/SIMULATED owned memory, no external provider. */
import {expect,test} from '@playwright/test';
import {mockPatientApp} from './polish-a1-fixture';

test('interval first time is optional and default 08:00 survives the real draft and confirmation summary',async({page,baseURL})=>{
 test.setTimeout(60000);expect(new URL(baseURL!).port).toBe('5193');
 await mockPatientApp(page,true,{token:'DEMO.correctness02-synthetic-token',owner:'de020000-0000-4000-8000-000000000001'});
 await page.route(url=>new URL(url).pathname.startsWith('/api/'),route=>route.continue());
 await page.goto('/');await page.locator('[data-guide="medicines"]').click();
 await page.getByRole('button',{name:'Add manually',exact:true}).click();
 await page.getByLabel('Medication name',{exact:true}).fill('DEMO interval browser');
 await page.getByLabel('Dose amount',{exact:true}).fill('1');
 await page.getByLabel('Schedule',{exact:true}).selectOption('interval');
 await expect(page.getByText(/When is the first dose/)).toBeVisible();
 await expect(page.getByLabel('First dose time (optional)',{exact:true})).toHaveValue('');
 await page.getByLabel('Interval in hours',{exact:true}).fill('8');
 await page.getByLabel('Course start date',{exact:true}).fill('2026-10-18');
 await page.getByLabel('First dose time (optional)',{exact:true}).scrollIntoViewIfNeeded();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:'../outputs/interval-start-mobile.png'});
 await page.getByRole('button',{name:'Review and add',exact:true}).click();
 await expect(page.getByText('Every N hours: 8; First dose time: Default 08:00',{exact:true})).toBeVisible();
 await page.getByRole('checkbox',{name:'I have checked these details against my original instructions.'}).check();
 const draft=page.waitForResponse(r=>r.url().includes('/api/medications/drafts')&&r.request().method()==='POST');
 await page.getByRole('button',{name:'Add this medication',exact:true}).click();
 expect((await draft).ok()).toBe(true);
 await expect(page.getByRole('heading',{name:'Please check this before I save it'})).toBeVisible();
 await expect(page.getByText('Every N hours: 8; First dose time: Default 08:00',{exact:true})).toHaveCount(2);
 await page.setViewportSize({width:1280,height:900});await page.screenshot({path:'../outputs/interval-start-confirmation.png'});
 // No activation click or self-report: a disclosed default is not confirmation or ingestion.
});

test('Chinese enlarged interval form keeps the default disclosure and first-time input usable',async({page,baseURL})=>{
 expect(new URL(baseURL!).port).toBe('5193');
 await mockPatientApp(page,true,{token:'DEMO.correctness02-synthetic-token',owner:'de020000-0000-4000-8000-000000000001'});
 await page.route(url=>new URL(url).pathname.startsWith('/api/'),route=>route.continue());
 await page.request.put('/api/me/preferences',{headers:{Authorization:'Bearer DEMO.correctness02-synthetic-token'},data:{preferred_language:'zh',text_scale_percent:150}});
 await page.goto('/');await page.locator('[data-guide="medicines"]').click();
 await page.getByRole('button',{name:'手动添加',exact:true}).click();
 await page.getByLabel('用药频率',{exact:true}).selectOption('interval');
 await expect(page.getByLabel('首次服药时间（可选）',{exact:true})).toBeVisible();
 await expect(page.getByText(/未填写时默认使用 08:00/)).toBeVisible();
 await page.getByLabel('首次服药时间（可选）',{exact:true}).fill('07:00');
 await page.getByLabel('首次服药时间（可选）',{exact:true}).scrollIntoViewIfNeeded();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:'../outputs/interval-start-zh150.png'});
});
