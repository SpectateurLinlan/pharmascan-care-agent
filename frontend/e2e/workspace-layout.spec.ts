/** Actual App route + local FastAPI/DEMO_ONLY memory persistence, not a preview. */
import {test,expect} from '@playwright/test';
import {mockPatientApp} from './polish-a1-fixture';

test('workspace layout, persistent desktop history and bottom interactions',async({page,baseURL})=>{
 test.setTimeout(180000);page.setDefaultTimeout(10000);
 expect(new URL(baseURL!).origin).toBe('http://127.0.0.1:5182');
 await page.setViewportSize({width:1280,height:1000});
 const {errors}=await mockPatientApp(page);
 await page.route(url=>new URL(url).pathname.startsWith('/api/'),route=>route.continue());
 const headers={Authorization:'Bearer DEMO.synthetic-session-token'};
 await page.request.put('/api/me/preferences',{headers,data:{preferred_language:'en',text_scale_percent:100,conversation_history_enabled:true,voice_enabled:true,tts_autoplay:false,reminders_enabled:false}});
 await page.goto('/');
 const composer=page.locator('.composer-row').getByRole('textbox');
 async function send(text:string){
  await composer.fill(text);const waiting=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/agent/messages'&&r.request().method()==='POST');
  await composer.press('Enter');const response=await waiting;expect(response.status()).toBe(200);
  const reply=await response.json() as {conversation_id:string;history_saved:boolean};expect(reply.history_saved).toBe(true);await expect(composer).toHaveValue('');return reply;
 }
 const a=await send('x');
 await page.getByRole('button',{name:'Open full chat',exact:true}).click();
 const workspace=page.locator('.conversation-workspace'),sidebar=workspace.locator('.conversation-history-browser');
 await page.screenshot({path:`../outputs/ux-c1/${process.env.QA_C1_LABEL??'after'}-1280.png`});
 await expect(sidebar).toBeVisible();
 await expect(sidebar.getByRole('button',{name:'New conversation',exact:true})).toBeVisible();
 await composer.fill('DEMO unsent A');await sidebar.getByRole('button',{name:'New conversation',exact:true}).click();
 const b=await send('DEMO C1 conversation B');expect(b.conversation_id).not.toBe(a.conversation_id);await composer.fill('DEMO unsent B');
 await sidebar.locator(`[data-conversation-id="${a.conversation_id}"]`).click();await expect(sidebar).toBeVisible();await expect(composer).toHaveValue('DEMO unsent A');
 await sidebar.locator(`[data-conversation-id="${b.conversation_id}"]`).click();await expect(composer).toHaveValue('DEMO unsent B');await expect(sidebar).toBeVisible();
 await composer.fill('');
 const before=await composer.boundingBox();await workspace.getByTitle('Hide conversation sidebar').click();await expect(sidebar).toHaveCount(0);
 const after=await composer.boundingBox();expect(after!.width).toBeGreaterThan(before!.width);
 await workspace.getByTitle('Show conversation sidebar').click();await expect(sidebar).toBeVisible();
 await sidebar.locator(`[data-conversation-id="${a.conversation_id}"]`).click();await composer.fill('');await send('x');
 for(const [language,scale] of [['en',100],['en',150],['zh',100],['zh',150]] as const){
  expect((await page.request.put('/api/me/preferences',{headers,data:{preferred_language:language,text_scale_percent:scale}})).ok()).toBe(true);
  await page.reload();await expect(workspace).toBeVisible();
  for(const width of [390,430,768,1024,1280,1600,1920]){
   await page.setViewportSize({width,height:1000});
   await expect(composer).toBeVisible();
   const tasks=workspace.locator('.workspace-tasks'),bottom=workspace.locator('.conversation-interaction'),timeline=workspace.locator('.conversation-scroll');
   await expect(tasks).toBeVisible();expect(await tasks.getByRole('button').count()).toBe(4);
   await expect(tasks.getByRole('button',{name:/View today’s medication|查看今日用药/})).toBeVisible();
   await expect(tasks.getByRole('button',{name:/Understand medicines|了解药物/})).toBeVisible();
   expect(await bottom.locator('.composer-row').count()).toBe(1);expect(await bottom.locator('.workspace-tasks').count()).toBe(1);
   const taskBox=await tasks.boundingBox(),composerBox=await workspace.locator('.composer-row').boundingBox();
   expect(composerBox!.y-taskBox!.y-taskBox!.height).toBeGreaterThanOrEqual(7);expect(composerBox!.y-taskBox!.y-taskBox!.height).toBeLessThanOrEqual(13);
   expect(composerBox!.y+composerBox!.height).toBeLessThanOrEqual(1000);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
   if(width>=1024)await expect(sidebar).toBeVisible();else await expect(sidebar).toHaveCount(0);
   const user=timeline.locator('.user-message').last(),bubble=await user.boundingBox(),column=await timeline.boundingBox();expect(bubble!.width).toBeLessThan(column!.width*.85);
   if([390,1920].includes(width))await page.screenshot({path:`../outputs/ux-c1/workspace-${language}-${scale}-${width}.png`});
  }
 }
 // Mobile history is a single view; selection returns to the same chat.
 await page.request.put('/api/me/preferences',{headers,data:{preferred_language:'en',text_scale_percent:100}});
 await page.setViewportSize({width:390,height:844});await page.reload();
 await workspace.getByRole('button',{name:'Conversation history'}).click();await expect(sidebar).toBeVisible();await expect(composer).not.toBeVisible();
 await sidebar.locator(`[data-conversation-id="${a.conversation_id}"]`).click();await expect(sidebar).toHaveCount(0);await expect(composer).toBeVisible();
 // Real shortcut prefills, multiline text, and long live messages all use the existing send path.
 const task=workspace.getByRole('button',{name:'Understand medicines',exact:true});await task.click();await expect(composer).toHaveValue(/general uses/);
 await composer.press('Shift+Enter');await expect(composer).toHaveValue(/\n$/);
 await composer.fill('');
 const dock=workspace.locator('.composer-row'),timeline=workspace.locator('.conversation-scroll');
 const dockBefore=await dock.boundingBox();
 for(let index=0;index<4;index++)await send(`DEMO long ${index} ${'LongUnbrokenWord'.repeat(30)} ${'症状'.repeat(30)}`);
 expect(await timeline.evaluate(el=>el.scrollHeight>el.clientHeight)).toBe(true);
 expect(Math.abs((await dock.boundingBox())!.y-dockBefore!.y)).toBeLessThan(2);
 await expect(workspace.locator('.turn > p:not(.user-message)').last()).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:'../outputs/ux-c1/long-mobile.png'});
 // Synthetic attachment preview, without pretending that live model inference ran.
 await page.getByLabel('Choose a photo',{exact:true}).setInputFiles({name:'DEMO_only.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aFh0AAAAASUVORK5CYII=','base64')});
 await expect(page.getByAltText('Selected photo preview')).toBeVisible();
 expect((await dock.boundingBox())!.y+(await dock.boundingBox())!.height).toBeLessThanOrEqual(844);
 await page.getByRole('button',{name:'Remove photo',exact:true}).click();
 // Real legacy append contract (omitting conversation_id) stays read-only in the UI.
 const legacy=await page.request.post('/api/agent/messages',{headers,data:{text:'DEMO C1 legacy read-only',client_turn_id:`legacy-${Date.now()}`,language:'en'}});expect(legacy.status()).toBe(200);
 await page.reload();await workspace.getByRole('button',{name:'Conversation history'}).click();
 await sidebar.getByRole('button',{name:/DEMO C1 legacy read-only/}).first().click();await expect(workspace.locator('.selected-history')).toBeVisible();
 await expect(workspace.locator('.workspace-tasks')).toHaveCount(0);await expect(composer).not.toBeVisible();
 await workspace.getByRole('button',{name:'Back to current conversation'}).click();await expect(composer).toBeVisible();
 expect(errors).toEqual([]);
});
