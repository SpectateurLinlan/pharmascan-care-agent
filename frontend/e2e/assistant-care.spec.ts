/** DEMO_ONLY real app services, all15 care capability IDs in each language. */
import {test,expect,type Locator} from '@playwright/test';

for(const language of ['en','zh'] as const){
 test(`care records, independently confirmed writes and all follow-up actions in ${language}`,async({page,baseURL})=>{
  expect(new URL(baseURL!).hostname).toBe('127.0.0.1');
  expect((await(await page.request.get('/api/health')).json()).database).toBe('simulated_in_memory');
  if(language==='en')await page.setViewportSize({width:1280,height:900});
  const client=`DEMO-care-${crypto.randomUUID()}`,say=(en:string,zh:string)=>language==='zh'?zh:en;
  async function call(method:string,path:string,data?:unknown){const response=await page.request.fetch(`${path}${path.includes('?')?'&':'?'}client_id=${client}`,{method,...(data?{data}:{})});expect(response.ok(),await response.text()).toBe(true);return response.json();}
  const session=await call('POST','/api/demo/start',{client_id:client});
  await call('PUT','/api/me/preferences',{preferred_language:language,voice_enabled:false,tts_autoplay:false});
  const med=await call('POST','/api/medications/drafts',{medication_name:'DEMO care medicine',dose_amount:1,dose_unit:'tablet',is_prn:true,food_instruction:'DEMO reviewed as-needed instructions'});
  await call('POST',`/api/medications/drafts/${med.source_id}/review`,{field_ids:null});
  const summary=await call('POST',`/api/medications/drafts/${med.regimen_id}/challenge?session_id=${session.session_id}`,{});
  await call('POST','/api/medications/activate',{regimen_id:med.regimen_id,...Object.fromEntries(['challenge_id','session_id','session_state','session_state_version'].map(key=>[key,summary[key]]))});
  const future=new Date(Date.now()+4*86400000).toISOString().slice(0,10);
  const cancelled=await call('POST','/api/me/care-tasks',{id:crypto.randomUUID(),category:'medication_review',title:'DEMO cancel this task',due_at:`${future}T12:00:00Z`,reminder_minutes:null,confirmed:true});
  await page.addInitScript(({client,owner})=>{localStorage.setItem('pharmascan.client_id',client);localStorage.setItem(`pharmascan.quick-start.v4:${owner}`,JSON.stringify({version:4,status:'skipped',step:0}));},{client,owner:session.patient_id});
  await page.goto('/');
  const panel=page.getByRole('region',{name:say('Current task','当前办理任务'),exact:true}),composer=page.locator('.composer-row').getByRole('textbox');
  const entries:Record<string,[string,string]>={
   'observation.add':['add a health note','添加健康观察'],'observation.list':['show health notes','查看健康观察'],'observation.edit':['edit a health note','编辑健康观察'],'observation.delete':['delete a health note','删除健康观察'],
   'inventory.count':['record medication stock','记录药物库存'],'inventory.view':['show medication inventory','查看药物库存'],
   'barrier.add':['record a medication difficulty','记录用药困难'],'barrier.list':['show medication difficulties','查看用药困难'],
   'followup.add':['add a medication followup','添加用药跟进'],'followup.list':['show medication followups','查看用药跟进'],'followup.edit':['edit a medication followup','编辑用药跟进'],
   'followup.contacted':['mark a followup contacted','标记跟进已联系'],'followup.defer':['defer a medication followup','延期用药跟进'],'followup.complete':['complete a medication followup','完成用药跟进'],'followup.cancel':['cancel a medication followup','取消用药跟进'],
  };
  const ids=new Set<string>();let writes=0;
  page.on('request',request=>{if(['POST','PUT','DELETE'].includes(request.method())&&/\/api\/me\/(?:health-observations|inventory\/|adherence-barriers|care-tasks(?:\?|$|\/[^/]+$))/.test(request.url())&&!request.url().includes('/refresh'))writes++;});
  async function start(id:string){const phrase=entries[id]!;const response=page.waitForResponse(row=>new URL(row.url()).pathname==='/api/agent/workflows/messages');await composer.fill(say(phrase[0],phrase[1]));await composer.press('Enter');const actual=await response;expect(actual.ok(),await actual.text()).toBe(true);expect((await actual.json()).workflow.capability_id).toBe(id);ids.add(id);}
  async function apply(){await panel.getByRole('button',{name:say('Apply care details','使用关怀资料'),exact:true}).click();await expect(panel.getByRole('button',{name:say('Prepare care review','准备关怀核对'),exact:true})).toBeEnabled();}
  async function review(){await panel.getByRole('button',{name:say('Prepare care review','准备关怀核对'),exact:true}).click();await panel.getByRole('button',{name:say('Review care record','核对关怀记录'),exact:true}).click();}
  async function confirm(sheet:Locator=page.getByRole('dialog')){await sheet.getByRole('button',{name:say('Confirm record','确认记录'),exact:true}).click();await expect(panel).toContainText(say('Your care record was saved','关怀记录已保存'));await expect(sheet).toBeHidden();}
  const select=(name:string)=>panel.getByRole('button',{name:new RegExp(say('Select record','选择记录')+': '+name)}).click();
  await start('observation.add');await panel.getByRole('textbox',{name:say('Describe how you feel (required)','描述您的感受（必填）'),exact:true}).fill('DEMO care observation');await apply();expect(writes).toBe(0);await review();expect(writes).toBe(0);await confirm();
  await start('observation.list');await expect(panel).toContainText('DEMO care observation');
  await start('observation.edit');await select('DEMO care observation');await panel.getByRole('textbox',{name:say('Describe how you feel (required)','描述您的感受（必填）'),exact:true}).fill('DEMO explicitly edited observation');await apply();await review();await confirm();
  await start('observation.delete');await select('DEMO explicitly edited observation');await review();await page.getByRole('dialog').getByRole('button',{name:say('Delete','删除'),exact:true}).click();await expect(panel).toContainText(say('Your care record was saved','关怀记录已保存'));expect(await call('GET','/api/me/health-observations')).toEqual([]);
  await start('inventory.count');await panel.getByRole('button',{name:new RegExp(say('View record','查看记录')+': DEMO care medicine')}).click();await panel.getByRole('spinbutton',{name:say('Quantity','数量'),exact:true}).fill('12');await apply();await review();const sheet=page.getByRole('dialog');await sheet.getByRole('button',{name:say('Cancel','取消'),exact:true}).click();await panel.getByRole('button',{name:say('Review care record','核对关怀记录'),exact:true}).click();
  await expect(sheet).toContainText('DEMO care medicine');
  await page.screenshot({path:`../outputs/assistant-workflows/care-review-${language}.png`,fullPage:true});
  if(language==='en')await page.route('**/api/me/inventory/*?*',async route=>{if(route.request().method()!=='POST')return route.continue();const actual=await route.fetch();expect(actual.ok()).toBe(true);await route.abort('failed');},{times:1});
  await sheet.getByRole('button',{name:say('Confirm record','确认记录'),exact:true}).click();if(language==='en')await sheet.getByRole('button',{name:'Check care result',exact:true}).click();await expect(panel).toContainText(say('Your care record was saved','关怀记录已保存'));
  const stock=await call('GET',`/api/me/inventory/${med.medication_id}`);expect(stock.last_confirmed_stock).toBe(12);expect(stock.transactions).toHaveLength(1);
  await start('inventory.view');await panel.getByRole('button',{name:new RegExp(say('View record','查看记录')+': DEMO care medicine')}).click();await expect(panel).toContainText('12');
  await start('barrier.add');await panel.getByRole('textbox',{name:say('Your description','您的描述'),exact:true}).fill('DEMO self-reported difficulty');await panel.getByRole('textbox',{name:say('Chosen support action','选择的支持措施'),exact:true}).fill('DEMO ask pharmacy about timing');await apply();await review();await confirm();
  await start('barrier.list');await expect(panel).toContainText('DEMO self-reported difficulty');
  await start('followup.add');await panel.getByRole('textbox',{name:say('Title (required)','事项名称（必填）'),exact:true}).fill('DEMO independent followup');await panel.getByLabel(say('Date','日期'),{exact:true}).fill(future);await panel.getByLabel(say('Time','时间'),{exact:true}).fill('20:00');await apply();await review();await confirm();
  await start('followup.list');await expect(panel).toContainText('DEMO independent followup');
  for(const id of ['followup.edit','followup.contacted','followup.defer','followup.complete']){
   await start(id);await select(id==='followup.edit'?'DEMO independent followup':'DEMO edited followup');
   if(id==='followup.edit'){await panel.getByRole('textbox',{name:say('Title (required)','事项名称（必填）'),exact:true}).fill('DEMO edited followup');await apply();}
   if(id==='followup.defer'){await panel.getByLabel(say('Date','日期'),{exact:true}).fill(future);await panel.getByLabel(say('Time','时间'),{exact:true}).fill('21:00');await apply();}
   await review();await confirm();
  }
  await start('followup.cancel');await select('DEMO cancel this task');await review();await confirm();
  const tasks=await call('GET','/api/me/care-tasks');const actual=tasks.find((row:{title:string})=>row.title==='DEMO edited followup');expect(actual.version).toBe(5);expect(actual.status).toBe('completed');expect(tasks.find((row:{id:string})=>row.id===cancelled.id).status).toBe('cancelled');
  expect((await call('GET','/api/me/adherence-barriers')).length).toBe(1);expect(ids.size).toBe(15);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 });
}
