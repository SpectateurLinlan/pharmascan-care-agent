/** Real loopback App/API with DEMO_ONLY memory owners and frozen public labels. */
import {test,expect} from '@playwright/test';

for(const language of ['en','zh'] as const){
 test(`general knowledge and confirmed typo in ${language}`,async({page,baseURL})=>{
  expect(new URL(baseURL!).hostname).toBe('127.0.0.1');
  const health=await (await page.request.get('/api/health')).json();
  expect(health.database).toBe('simulated_in_memory');
  const client=`DEMO-knowledge-${language}-${Date.now()}`;
  const session=await (await page.request.post('/api/demo/start',{data:{client_id:client}})).json();
  const preferences=await page.request.put(`/api/me/preferences?client_id=${client}`,{data:{preferred_language:language,voice_enabled:false,tts_autoplay:false,conversation_history_enabled:false}});
  expect(preferences.ok()).toBe(true);
  await page.addInitScript(({client,owner})=>{
   localStorage.setItem('pharmascan.client_id',client);
   localStorage.setItem(`pharmascan.quick-start.v4:${owner}`,JSON.stringify({version:4,status:'skipped',step:0}));
  },{client,owner:session.patient_id});
  await page.goto('/');
  const composer=page.locator('.composer-row').getByRole('textbox');
  await expect(composer).toBeVisible();
  const question=language==='zh'?'布洛分是什么？':'What is ibuprofne?';
  await composer.fill(question);
  const waiting=page.waitForResponse(response=>['/api/agent/messages','/api/agent/workflows/messages'].includes(new URL(response.url()).pathname)&&response.request().method()==='POST');
  await composer.press('Enter');
  const first=await waiting;expect(first.status()).toBe(200);
  const body=await first.json();expect((body.reply??body).name_choice.options).toHaveLength(1);
  const latest=page.locator('.turn').last();
  await latest.getByRole('button',{name:'IBUPROFEN',exact:true}).click();
  const answered=page.locator('.turn').last();
  await expect(answered.locator('.answer-sources')).toBeVisible();
  await answered.locator('.answer-sources>summary').click();
  await expect(answered.locator('.answer-sources a').first()).toHaveAttribute('href',/^https:\/\/dailymed\.nlm\.nih\.gov\//);
  await expect(answered).not.toContainText('get_medication_understanding: success');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  await page.screenshot({path:`../outputs/assistant-knowledge/${language}.png`,fullPage:true});
  expect((await (await page.request.get(`/api/me/medications?client_id=${client}`)).json()).medications).toEqual([]);
 });
}

test('failed message delivery preserves the question and can retry against the real local API',async({page,baseURL})=>{
 expect(new URL(baseURL!).hostname).toBe('127.0.0.1');
 const client=`DEMO-knowledge-retry-${Date.now()}`;
 const session=await (await page.request.post('/api/demo/start',{data:{client_id:client}})).json();
 await page.request.put(`/api/me/preferences?client_id=${client}`,{data:{preferred_language:'en',voice_enabled:false,tts_autoplay:false}});
 await page.addInitScript(({client,owner})=>{
  localStorage.setItem('pharmascan.client_id',client);
  localStorage.setItem(`pharmascan.quick-start.v4:${owner}`,JSON.stringify({version:4,status:'skipped',step:0}));
 },{client,owner:session.patient_id});
 let fail=true;
 await page.route('**/api/**/messages?*',route=>{if(fail){fail=false;return route.abort('failed');}return route.continue();});
 await page.goto('/');
 const composer=page.locator('.composer-row').getByRole('textbox');
 await composer.fill('What is ibuprofen?');await composer.press('Enter');
 await expect(page.getByRole('alert')).toContainText('Failed to fetch');
 await expect(composer).toHaveValue('What is ibuprofen?');
 await page.getByRole('button',{name:'Dismiss',exact:true}).click();
 await page.getByRole('button',{name:'Send',exact:true}).click();
 await expect(page.locator('.turn').last().locator('.answer-sources')).toBeVisible();
 await expect(composer).toHaveValue('');
});
