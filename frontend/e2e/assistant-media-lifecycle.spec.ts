/** DEMO_ONLY lifecycle acceptance using actual local memory APIs and synthetic bytes. */
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {test,expect} from '@playwright/test';

for(const language of ['en','zh'] as const){
 test(`six independent photo and PDF lifecycle actions in ${language}`,async({page,baseURL})=>{
  expect(new URL(baseURL!).hostname).toBe('127.0.0.1');
  expect((await(await page.request.get('/api/health')).json()).database).toBe('simulated_in_memory');
  if(language==='en')await page.setViewportSize({width:1280,height:900});
  await page.route('**/*',route=>{const url=new URL(route.request().url());return !['http:','https:'].includes(url.protocol)||url.hostname==='127.0.0.1'?route.continue():route.abort('blockedbyclient');});
  const client=`DEMO-media-lifecycle-${crypto.randomUUID()}`,say=(en:string,zh:string)=>language==='zh'?zh:en;
  async function call(method:string,path:string,data?:unknown){const response=await page.request.fetch(`${path}${path.includes('?')?'&':'?'}client_id=${client}`,{method,...(data?{data}:{})});expect(response.ok(),await response.text()).toBe(true);return response.json();}
  const session=await call('POST','/api/demo/start',{client_id:client});
  await call('PUT','/api/me/preferences',{preferred_language:language,voice_enabled:false,tts_autoplay:false});
  const med=await call('POST','/api/medications/drafts',{medication_name:'DEMO lifecycle medicine',dose_amount:1,dose_unit:'tablet',is_prn:true,food_instruction:'DEMO reviewed instructions'});
  await call('POST',`/api/medications/drafts/${med.source_id}/review`,{field_ids:null});
  const summary=await call('POST',`/api/medications/drafts/${med.regimen_id}/challenge?session_id=${session.session_id}`,{});
  await call('POST','/api/medications/activate',{regimen_id:med.regimen_id,...Object.fromEntries(['challenge_id','session_id','session_state','session_state_version'].map(key=>[key,summary[key]]))});
  const photos=[];
  for(const [name,fixture] of [['DEMO package','DEMO_workflow_photo.png'],['DEMO delete package','DEMO_workflow_photo_unavailable.png']]){
   const image=await page.request.post(`/api/evidence/gallery/${med.medication_id}/images?client_id=${client}&image_kind=package&source_description=${encodeURIComponent(name!)}&reviewed=true`,{headers:{'Content-Type':'image/png','X-Stage2-Consent':'true','X-Demo-Only':'true'},data:readFileSync(resolve(`../tests/backend/fixtures/${fixture}`))});
   expect(image.ok(),await image.text()).toBe(true);photos.push((await image.json()).photo);
  }
  const bytes=Buffer.from('%PDF-1.7\n1 0 obj<</Type/Catalog>>endobj\n%%EOF');
  const uploaded=await page.request.post(`/api/evidence/gallery/${med.medication_id}/pdfs?client_id=${client}&filename=DEMO_original.pdf&description=DEMO%20old%20PDF`,{headers:{'Content-Type':'application/pdf'},data:bytes});
  expect(uploaded.ok(),await uploaded.text()).toBe(true);const file=(await uploaded.json()).file;
  const original=await(await page.request.get(`/api/evidence/images/${photos[0].id}?client_id=${client}`)).body();
  await page.addInitScript(({client,owner})=>{localStorage.setItem('pharmascan.client_id',client);localStorage.setItem(`pharmascan.quick-start.v4:${owner}`,JSON.stringify({version:4,status:'skipped',step:0}));},{client,owner:session.patient_id});
  await page.goto('/');
  const panel=page.getByRole('region',{name:say('Current task','当前办理任务'),exact:true}),composer=page.locator('.composer-row').getByRole('textbox');
  const entries:Record<string,[string,string]>={
   'gallery.photo.edit':['edit a medication photo','编辑药物照片'],'gallery.photo.remove':['remove a medication photo from gallery','移出药物图库照片'],
   'gallery.photo.delete':['delete a medication photo','删除药物照片'],'gallery.photo.retire':['stop comparing a medication photo','停用药物照片比对'],
   'library.pdf.edit':['edit a medication PDF','编辑药物PDF'],'library.pdf.delete':['delete a medication PDF','删除药物PDF'],
  };
  const visited=new Set<string>();let writes=0;
  page.on('request',request=>{const path=new URL(request.url()).pathname;if(path.startsWith('/api/evidence/')&&['POST','PATCH','DELETE'].includes(request.method()))writes++;});
  async function start(id:string,target:string){const phrase=entries[id]!;const response=page.waitForResponse(row=>new URL(row.url()).pathname==='/api/agent/workflows/messages');await composer.fill(say(phrase[0],phrase[1]));await composer.press('Enter');const actual=await response;expect(actual.ok(),await actual.text()).toBe(true);expect((await actual.json()).workflow.capability_id).toBe(id);visited.add(id);await select('DEMO lifecycle medicine');await select(target);}
  const select=(text:string)=>panel.getByRole('button',{name:`${say('Select','选择')}: ${text}`,exact:true}).click();
  async function prepare(){const before=writes;await panel.getByRole('button',{name:say('Prepare file review','准备文件核对'),exact:true}).click();await panel.getByRole('button',{name:say('Review file action','核对文件操作'),exact:true}).click();expect(writes).toBe(before);await expect(page.getByRole('dialog')).toContainText('DEMO lifecycle medicine');}
  async function confirm(){await page.getByRole('dialog').locator('button.primary').click();await expect(panel).toContainText(say('The file action result was verified.','已核查文件操作结果。'));await expect(page.getByRole('dialog')).toBeHidden();}
  await start('gallery.photo.edit','DEMO package');await panel.getByRole('combobox').selectOption('blister');await panel.getByRole('textbox').fill('DEMO revised photo');await panel.getByRole('button',{name:say('Apply file details','使用文件资料'),exact:true}).click();await prepare();await page.getByRole('dialog').getByRole('button',{name:say('Cancel','取消'),exact:true}).click();expect(writes).toBe(0);await panel.getByRole('button',{name:say('Review file action','核对文件操作'),exact:true}).click();await confirm();expect(writes).toBe(1);
  await start('gallery.photo.retire','DEMO revised photo');await prepare();await confirm();
  let gallery=await call('GET','/api/evidence/gallery');expect(gallery[0].images.find((row:{id:string})=>row.id===photos[0].id).eligibility).toBe('ineligible');
  await start('gallery.photo.remove','DEMO revised photo');await prepare();await confirm();gallery=await call('GET','/api/evidence/gallery');expect(gallery[0].images.some((row:{id:string})=>row.id===photos[0].id)).toBe(false);
  const retained=await page.request.get(`/api/evidence/images/${photos[0].id}?client_id=${client}`);expect((await retained.body()).equals(original)).toBe(true);
  await start('gallery.photo.delete','DEMO delete package');await prepare();await confirm();expect((await page.request.get(`/api/evidence/images/${photos[1].id}?client_id=${client}`)).status()).toBe(404);
  await start('library.pdf.edit','DEMO_original');await panel.getByRole('textbox').nth(0).fill('DEMO revised PDF');await panel.getByRole('textbox').nth(1).fill('DEMO reviewed PDF note');await panel.getByRole('button',{name:say('Apply file details','使用文件资料'),exact:true}).click();await prepare();
  await expect(page.getByRole('dialog').getByRole('button',{name:say('Save changes','保存更改'),exact:true})).toBeVisible();
  await page.screenshot({path:`../outputs/assistant-workflows/media-lifecycle-review-${language}.png`,fullPage:true});
  if(language==='en'){
   await page.route(`**/api/evidence/library-files/${file.id}?*`,async route=>{if(route.request().method()!=='PATCH')return route.continue();const actual=await route.fetch();expect(actual.ok(),await actual.text()).toBe(true);await route.abort('failed');},{times:1});
   await page.getByRole('dialog').locator('button.primary').click();await expect(page.getByRole('dialog').getByRole('alert')).toContainText('The result is unknown');await page.getByRole('dialog').getByRole('button',{name:'Check file result',exact:true}).click();await expect(panel).toContainText('The file action result was verified.');
  }else await confirm();
  expect(writes).toBe(5);const preserved=await page.request.get(`/api/evidence/library-files/${file.id}?client_id=${client}`);expect((await preserved.body()).equals(bytes)).toBe(true);
  await start('library.pdf.delete','DEMO revised PDF');await prepare();await confirm();expect((await page.request.get(`/api/evidence/library-files/${file.id}?client_id=${client}`)).status()).toBe(404);
  expect(writes).toBe(6);expect(visited.size).toBe(6);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 });
}
