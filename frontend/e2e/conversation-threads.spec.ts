/** DEMO_ONLY Auth; real application HTTP and isolated PostgreSQL/RLS persistence. */
import {test,expect} from '@playwright/test';
import {mockPatientApp} from './polish-a1-fixture';

test('persist A/B, continue and reload A through actual HTTP/SQL, keep drafts and responsive composer',async({page,baseURL})=>{
 test.setTimeout(120000);page.setDefaultTimeout(10000);
 expect(new URL(baseURL!).origin).toBe('http://127.0.0.1:5181');
 const {errors}=await mockPatientApp(page);
 await page.route(url=>new URL(url).pathname.startsWith('/api/'),route=>route.continue());
 const headers={Authorization:'Bearer DEMO.synthetic-session-token'};
 async function openHistory(){const toggle=page.locator('.conversation-brand button');if(await toggle.getAttribute('aria-expanded')==='false')await toggle.click();}
 const run=Date.now();
 expect((await page.request.put('/api/me/preferences',{headers,data:{conversation_history_enabled:true,preferred_language:'en',text_scale_percent:100,voice_enabled:false}})).ok()).toBe(true);
 await page.goto('/');
 const composer=page.getByRole('textbox');
 async function send(text:string){await composer.fill(text);const response=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/agent/messages');await composer.press('Enter');const r=await response;expect(r.status()).toBe(200);const body=await r.json();expect(body.history_saved).toBe(true);await expect(composer).toHaveValue('');return body;}
 const a=await send(`DEMO conversation A first question ${run}`);
 await page.getByRole('button',{name:'Open full chat',exact:true}).click();
 await composer.fill('DEMO draft A');
 await page.getByRole('button',{name:'New conversation',exact:true}).click();
 await expect(composer).toHaveValue('');
 const b=await send('DEMO conversation B first question');expect(b.conversation_id).not.toBe(a.conversation_id);
 await composer.fill('DEMO draft B');
 await openHistory();
 await page.getByRole('button',{name:new RegExp(`DEMO conversation A first question ${run}`)}).click();
 await expect(composer).toHaveValue('DEMO draft A');
 const continued=await send('DEMO A second question');expect(continued.conversation_id).toBe(a.conversation_id);
 await openHistory();
 await page.getByRole('button',{name:/DEMO conversation B first question/}).first().click();
 await expect(composer).toHaveValue('DEMO draft B');
 await openHistory();
 await page.getByRole('button',{name:new RegExp(`DEMO conversation A first question ${run}`)}).click();
 await expect(composer).toHaveValue('');
 const read=await page.request.get(`/api/agent/conversations/${a.conversation_id}`,{headers});
 expect((await read.json()).entries.map((r:{user_text:string})=>r.user_text)).toEqual([`DEMO conversation A first question ${run}`,'DEMO A second question']);
 await page.reload();
 await expect(page.getByText('DEMO A second question',{exact:true})).toBeVisible();
 const restored=await send('DEMO A after reload');expect(restored.conversation_id).toBe(a.conversation_id);
 expect(restored.tool_traces.some((row:{tool_name:string;status:string})=>row.tool_name==='list_active_medications'&&row.status==='success')).toBe(true); // DEMO stateless model asserts SQL-restored A context and triggers a fresh real read.
 const untouched=await page.request.get(`/api/agent/conversations/${b.conversation_id}`,{headers});expect((await untouched.json()).entries).toHaveLength(1);
 await page.locator('[data-guide="records"]').click();
 await page.locator('.assistant-header-shortcut').click();
 await expect(page.locator('.assistant-source')).toContainText('Records');
 await page.locator('.assistant-source summary').click();
 await page.getByRole('button',{name:'Return to source',exact:true}).click();
 await expect(page.locator('.record-history')).toBeVisible();
 await page.locator('.assistant-header-shortcut').click();
 for(const [language,scale] of [['en',100],['en',150],['zh',100],['zh',150]] as const){
  expect((await page.request.put('/api/me/preferences',{headers,data:{preferred_language:language,text_scale_percent:scale}})).ok()).toBe(true);
  await page.reload();await expect(page.locator('.conversation-workspace')).toBeVisible();
  for(const width of [390,430,768,1024,1280,1600,1920]){
   await page.setViewportSize({width,height:1000});
   expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
   await expect(composer).toBeVisible();
   const box=await composer.boundingBox();expect(box!.x).toBeGreaterThanOrEqual(0);expect(box!.x+box!.width).toBeLessThanOrEqual(width);expect(box!.y+box!.height).toBeLessThanOrEqual(1000);
   if(width>=1024){
    await openHistory();
    await expect(page.locator('.conversation-history-browser')).toBeVisible();await expect(composer).toBeVisible();
    expect(await page.locator('.history-current').evaluate(element=>element.scrollHeight<=element.clientHeight+1)).toBe(true);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    const narrow=await composer.boundingBox();expect(narrow!.width).toBeGreaterThan(100);expect(narrow!.y+narrow!.height).toBeLessThanOrEqual(1000);
    await page.locator('.conversation-brand button').click();
   }
   if([390,1280,1920].includes(width))await page.screenshot({path:`../outputs/conversation-${language}-${scale}-${width}.png`});
  }
 }
 expect((await page.request.put('/api/me/preferences',{headers,data:{preferred_language:'en',text_scale_percent:100}})).ok()).toBe(true);
 await page.reload();await openHistory();
 await expect(page.getByRole('button',{name:new RegExp(`DEMO conversation A first question ${run}`)})).toBeVisible();
 await expect(composer).toBeVisible();
 await expect(page.getByText('DEMO A after reload',{exact:true})).toBeVisible();
 await page.screenshot({path:'../outputs/conversation-history-en-100-1920.png'});
 await page.setViewportSize({width:390,height:844});await openHistory();
 await expect(page.locator('.conversation-history-browser')).toBeVisible();
 await expect(composer).not.toBeVisible();
 await page.getByRole('button',{name:new RegExp(`DEMO conversation A first question ${run}`)}).click();
 await expect(composer).toBeVisible();
 await page.getByLabel('Choose a photo',{exact:true}).setInputFiles({name:'DEMO_only.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=','base64')});
 await expect(page.getByAltText('Selected photo preview')).toBeVisible();
 const photoComposer=await composer.boundingBox();expect(photoComposer!.y+photoComposer!.height).toBeLessThanOrEqual(844);
 await page.getByRole('button',{name:'Remove photo',exact:true}).click();
 expect(errors).toEqual([]);
});
