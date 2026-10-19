/** Actual App -> local FastAPI/Agent -> synthetic records + cached public labels. No Gemini. */
import {expect,test} from '@playwright/test';
import {writeFile} from 'node:fs/promises';
import {mockPatientApp} from './polish-a1-fixture';

test('medication buttons continue the original intent, keep the conversation and expire safely after reload',async({page,baseURL})=>{
 test.setTimeout(60000);page.setDefaultTimeout(15000);
 expect(new URL(baseURL!).port).toBe('5191');
 const {errors}=await mockPatientApp(page,true,{token:'DEMO.correctness02-synthetic-token',owner:'de020000-0000-4000-8000-000000000001'});
 await page.route(url=>new URL(url).pathname.startsWith('/api/'),route=>route.continue());
 await page.clock.install({time:new Date('2026-10-18T04:00:00Z')});
 const sent:Array<Record<string,unknown>>=[];
 const replies:Array<Record<string,unknown>>=[];
 page.on('request',request=>{if(request.method()==='POST'&&new URL(request.url()).pathname==='/api/agent/messages')sent.push(request.postDataJSON() as Record<string,unknown>);});
 page.on('response',async response=>{if(response.request().method()==='POST'&&new URL(response.url()).pathname==='/api/agent/messages')replies.push(await response.json() as Record<string,unknown>);});
 try{
 const initialPreferences=await page.request.put('/api/me/preferences',{headers:{Authorization:'Bearer DEMO.correctness02-synthetic-token'},data:{preferred_language:'en',text_scale_percent:100,conversation_history_enabled:true}});expect(initialPreferences.ok()).toBe(true);
 await page.goto('/',{waitUntil:'domcontentloaded',timeout:15000});await page.getByRole('button',{name:'Open full chat',exact:true}).click();
 const input=page.getByRole('textbox');await input.fill('What is this medicine for?');await page.getByRole('button',{name:'Send',exact:true}).click();
 const choices=page.getByRole('region',{name:'Choose a medicine'});await expect(choices.getByRole('button')).toHaveCount(3);
 const target=choices.getByRole('button',{name:/Metformin 500 mg/});await target.focus();await page.keyboard.press('Enter');
 await expect(page.locator('.transcript')).toContainText('blood sugar');expect(sent).toHaveLength(2);
 expect(sent[1]?.medication_selection).toBeTruthy();expect(sent[1]?.conversation_id).toBeTruthy();expect(sent[1]?.text).toContain('Metformin');
 await page.getByText('Knowledge sources',{exact:true}).click();await expect(page.getByRole('link',{name:/US drug label/})).toHaveAttribute('href',/dailymed\.nlm\.nih\.gov/);
 await input.fill('Show my health observations');await page.getByRole('button',{name:'Send',exact:true}).click();await expect(page.locator('.transcript')).toContainText('DEMO felt well');
 await input.fill('What is this medicine for?');await page.getByRole('button',{name:'Send',exact:true}).click();await expect(choices.getByRole('button')).toHaveCount(3);
 await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:'../outputs/correctness02-choices-mobile.png',fullPage:true});
 await page.reload();await expect(page.getByText('Saved choices are read-only. Ask again to refresh medicine options.')).toBeVisible();await expect(choices).toHaveCount(0);
 await input.fill('What is this medicine for?');await page.getByRole('button',{name:'Send',exact:true}).click();await expect(choices.getByRole('button')).toHaveCount(3);
 const before=sent.length;await choices.getByRole('button',{name:/Amlodipine 10 mg/}).evaluate(button=>{(button as HTMLButtonElement).click();(button as HTMLButtonElement).click();});
 await expect(page.locator('.transcript')).toContainText('hypertension');expect(sent.length-before).toBe(1);
 await page.setViewportSize({width:1280,height:1000});await page.screenshot({path:'../outputs/correctness02-choices-desktop.png',fullPage:true});
 const preference=await page.request.put('/api/me/preferences',{headers:{Authorization:'Bearer DEMO.correctness02-synthetic-token'},data:{preferred_language:'zh',text_scale_percent:150}});expect(preference.ok()).toBe(true);
 await page.reload();await page.getByRole('textbox').fill('查看我的健康观察');await page.getByRole('button',{name:'发送',exact:true}).click();await expect(page.locator('.transcript')).toContainText('DEMO felt well');
 await page.getByRole('textbox').fill('这个药有什么作用？');await page.getByRole('button',{name:'发送',exact:true}).click();const chineseChoices=page.getByRole('region',{name:'选择药物'});await expect(chineseChoices.getByRole('button')).toHaveCount(3);
 await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);expect(await page.locator('.conversation-scroll').evaluate(element=>element.clientHeight)).toBeGreaterThan(90);await chineseChoices.getByRole('button',{name:/Metformin/}).scrollIntoViewIfNeeded();await page.screenshot({path:'../outputs/correctness02-choices-zh150-mobile.png',fullPage:true});
 await chineseChoices.getByRole('button',{name:/Metformin/}).click();await expect(page.locator('.transcript')).toContainText('血糖');
 await page.setViewportSize({width:1280,height:1000});await page.screenshot({path:'../outputs/correctness02-choices-zh150-desktop.png',fullPage:true});
 expect(sent.at(-1)?.conversation_id).toBeTruthy();
 const sharedConversation=sent.at(-1)?.conversation_id;
 await page.locator('[data-guide="today"]').click();await page.getByRole('textbox').fill('查看我的健康观察');await page.getByRole('button',{name:'发送',exact:true}).click();await expect(page.locator('.transcript')).toContainText('DEMO felt well');
 await page.getByRole('textbox').fill('这个药有什么作用？');await page.getByRole('button',{name:'发送',exact:true}).click();const todayChoices=page.getByRole('region',{name:'选择药物'});await expect(todayChoices.getByRole('button')).toHaveCount(3);
 await todayChoices.getByRole('button',{name:/Amlodipine 10 mg/}).click();await expect(page.locator('.transcript')).toContainText('高血压');expect(sent.at(-1)?.conversation_id).toBe(sharedConversation);
 const authorization={Authorization:'Bearer DEMO.correctness02-synthetic-token'};
 const savedBefore=await(await page.request.get(`/api/agent/conversations/${String(sharedConversation)}`,{headers:authorization})).json() as {entries:unknown[]};
 const off=await page.request.put('/api/me/preferences',{headers:authorization,data:{conversation_history_enabled:false}});expect(off.ok()).toBe(true);
 await page.reload();await page.getByRole('textbox').fill('查看我的健康观察');await page.getByRole('button',{name:'发送',exact:true}).click();await expect(page.locator('.transcript')).toContainText('DEMO felt well');
 await page.getByRole('textbox').fill('这个药有什么作用？');await page.getByRole('button',{name:'发送',exact:true}).click();await expect(page.getByRole('region',{name:'选择药物'}).getByRole('button')).toHaveCount(3);
 await page.getByRole('region',{name:'选择药物'}).getByRole('button',{name:/Metformin/}).click();await expect(page.locator('.transcript')).toContainText('血糖');
 const savedAfter=await(await page.request.get(`/api/agent/conversations/${String(sharedConversation)}`,{headers:authorization})).json() as {entries:unknown[]};expect(savedAfter.entries).toEqual(savedBefore.entries);
 expect(errors).toEqual([]);
 }finally{
  const lines=['# Actual App Browser E2E — Correctness 02','','Mode: Browser E2E -> actual local FastAPI/Agent/application, DEMO_ONLY patient and cached public labels; no Gemini. Every recorded request/reply below is actual browser traffic. Assertions validate dynamic labels, typed selection, source link, same-thread continuation, refresh safe expiry, keyboard selection and duplicate-click suppression.',''];
  for(const [index,reply] of replies.entries())lines.push(`## Turn ${index+1}`,'','User:',`> ${String(sent[index]?.text??'')}`,'','Actual Assistant:',...String(reply.message??'').split('\n').map(line=>'> '+line),'','Actual structured selection: '+JSON.stringify(sent[index]?.medication_selection??null),'','Tool evidence: '+JSON.stringify(reply.tool_traces),'');
  await writeFile('../outputs/correctness02-browser-conversations.md',lines.join('\n'),'utf8');
  await writeFile('../outputs/correctness02-browser-conversations.json',JSON.stringify({sent,replies,errors},null,2),'utf8');
 }
});

test('exact product clarification resumes reviewed personal instructions without a knowledge substitution',async({page,baseURL})=>{
 test.setTimeout(30000);page.setDefaultTimeout(10000);expect(new URL(baseURL!).port).toBe('5191');
 const {errors}=await mockPatientApp(page,true,{token:'DEMO.correctness02-synthetic-token',owner:'de020000-0000-4000-8000-000000000001'});
 await page.route(url=>new URL(url).pathname.startsWith('/api/'),route=>route.continue());await page.clock.install({time:new Date('2026-10-18T04:00:00Z')});
 await page.request.put('/api/me/preferences',{headers:{Authorization:'Bearer DEMO.correctness02-synthetic-token'},data:{preferred_language:'en',text_scale_percent:100,conversation_history_enabled:true}});
 const replies:Array<Record<string,unknown>>=[];const sent:Array<Record<string,unknown>>=[];
 page.on('request',request=>{if(request.method()==='POST'&&new URL(request.url()).pathname==='/api/agent/messages')sent.push(request.postDataJSON() as Record<string,unknown>);});
 page.on('response',async response=>{if(response.request().method()==='POST'&&new URL(response.url()).pathname==='/api/agent/messages')replies.push(await response.json() as Record<string,unknown>);});
 try{
  await page.goto('/');await page.getByRole('button',{name:'Open full chat',exact:true}).click();await page.getByRole('textbox').fill('How should I take Amlodipine?');await page.getByRole('button',{name:'Send',exact:true}).click();
  const choices=page.getByRole('region',{name:'Choose a medicine'});await expect(choices.getByRole('button')).toHaveCount(2);await expect(choices).not.toContainText('Metformin');
  await choices.getByRole('button',{name:/5 mg/}).click();await expect(page.locator('.transcript')).toContainText('0.5 tablet');await expect(page.locator('.transcript')).toContainText('20:00');
  expect(sent[1]?.conversation_id).toBeTruthy();expect(sent[1]?.medication_selection).toBeTruthy();expect(errors).toEqual([]);
  await page.screenshot({path:'../outputs/correctness02-personal-plan-mobile.png',fullPage:true});
 }finally{
  const lines=['# Browser increment — exact-product personal instructions','','Actual App -> latest local Backend/Application, DEMO_ONLY patient; no Gemini or external knowledge calls required. Ground truth: Amlodipine 5 mg current reviewed plan = 0.5 tablet at 20:00. The ambiguous name must show only its two products, not Metformin.',''];
  for(const [i,reply] of replies.entries())lines.push(`## Turn ${i+1}`,'','User:',`> ${String(sent[i]?.text??'')}`,'','Actual Assistant:',...String(reply.message??'').split('\n').map(line=>'> '+line),'','Actual selection: '+JSON.stringify(sent[i]?.medication_selection??null),'','Tool evidence: '+JSON.stringify(reply.tool_traces),'');
  await writeFile('../outputs/correctness02-browser-product-conversations.md',lines.join('\n'),'utf8');
 }
});
