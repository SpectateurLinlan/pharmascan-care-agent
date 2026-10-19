/** Actual App, actual local API and DEMO_ONLY enrollment; never production. */
import {test,expect} from '@playwright/test';
import {mockPatientApp} from './polish-a1-fixture';
test('Chinese enlarged enrollment form remains operable at narrow and wide widths',async({page,baseURL})=>{
 expect(new URL(baseURL!).origin).toBe('http://127.0.0.1:5182');await mockPatientApp(page);
 await page.route(url=>new URL(url).pathname.startsWith('/api/'),route=>route.continue());
 const headers={Authorization:'Bearer DEMO.synthetic-session-token'};
 await page.request.put('/api/me/preferences',{headers,data:{preferred_language:'zh',text_scale_percent:150,reminders_enabled:false}});
 await page.goto('/');await page.locator('[data-guide="medicines"]').click();await page.getByRole('button',{name:/手动添加/}).click();
 await expect(page.getByRole('radio',{name:'填写服用天数',exact:true})).toBeChecked();
 for(const width of [390,430,768,1280]){
  await page.setViewportSize({width,height:1000});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  expect(await page.locator('#med-time-0').evaluate(el=>el.getBoundingClientRect().width)).toBeGreaterThan(150);
 }
 await page.getByRole('radio',{name:'填写最后用药日',exact:true}).check();await expect(page.getByLabel('最后用药日（含当天）',{exact:true})).toBeVisible();
});
test('calendar alternatives, control baselines and automatically fading enrollment success',async({page,baseURL})=>{
 expect(new URL(baseURL!).origin).toBe('http://127.0.0.1:5182');
 await mockPatientApp(page);await page.route(url=>new URL(url).pathname.startsWith('/api/'),route=>route.continue());
 const headers={Authorization:'Bearer DEMO.synthetic-session-token'};
 await page.request.put('/api/me/preferences',{headers,data:{preferred_language:'en',text_scale_percent:100,reminders_enabled:false}});
 await page.goto('/');await page.locator('[data-guide="medicines"]').click();await page.getByRole('heading',{name:/Add medication/}).waitFor();await page.getByRole('button',{name:/Add manually/}).click();
 await page.getByLabel('Medication name',{exact:true}).fill('DEMO calendar responsive refinement');await page.getByLabel('Dose amount',{exact:true}).fill('1');
 await page.getByLabel('Course start date',{exact:true}).fill('2026-10-17');await page.getByLabel('Number of days',{exact:true}).fill('7');await expect(page.getByText('Last day (inclusive): 2026-10-23',{exact:true})).toBeVisible();
 await page.getByRole('radio',{name:'Enter last day',exact:true}).check();await expect(page.getByLabel('Last day (inclusive)',{exact:true})).toHaveValue('2026-10-23');await page.getByLabel('Last day (inclusive)',{exact:true}).fill('2026-10-24');await expect(page.getByText('Number of days: 8',{exact:true})).toBeVisible();
 for(const width of [390,430,768,1024,1280,1600]){
  await page.setViewportSize({width,height:1000});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  if(width>=768){for(const ids of [['#med-dose','#med-unit'],['.course-fields input[type="date"]']]){const tops=await page.locator(ids.join(',')).evaluateAll(nodes=>nodes.filter(node=>node.getBoundingClientRect().width>0).map(node=>node.getBoundingClientRect().top));if(tops.length>1)expect(Math.max(...tops)-Math.min(...tops)).toBeLessThan(2);}}
  const bottom=await page.locator('#med-time-0').evaluate(el=>el.getBoundingClientRect().bottom),button=await page.getByRole('button',{name:'Add another time',exact:true}).evaluate(el=>el.getBoundingClientRect().bottom);if(width>640)expect(Math.abs(bottom-button)).toBeLessThan(2);else{expect(button).toBeGreaterThan(bottom);expect(await page.locator('#med-time-0').evaluate(el=>el.getBoundingClientRect().width)).toBeGreaterThan(150);}
  if([390,1280].includes(width)){await page.locator('#med-time-0').blur();await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:`../outputs/enrollment-refined-${width}.png`,fullPage:true});}
 }
 await page.getByRole('button',{name:'Review and add',exact:true}).click();await page.getByLabel('I have checked these details against my original instructions.').check();await page.getByRole('button',{name:'Add this medication',exact:true}).click();await page.getByRole('button',{name:'Yes, save this medication',exact:true}).click();
 const success=page.getByText('Medication added. It now appears in your medication list.',{exact:true});await expect(success).toBeVisible();await expect(page.locator('.patient-toast--success button')).toHaveCount(0);await expect(success).toHaveCount(0,{timeout:7000});
 const records=await page.request.get('/api/me/regimens',{headers});const row=(await records.json() as {display_name:string;course_start_date:string;course_end_date:string}[]).find(row=>row.display_name==='DEMO calendar responsive refinement');expect(row?.course_start_date).toBe('2026-10-17');expect(row?.course_end_date).toBe('2026-10-24');
});
