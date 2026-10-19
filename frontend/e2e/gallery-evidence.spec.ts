import {skipInitialGuide} from './navigation-helpers';
/** REAL browser/Auth/RLS/Gemini/Stage2, synthetic labels/pill only. No provider interception. */
import {test,expect,type Page,type Response} from '@playwright/test';
import {readFileSync,writeFileSync} from 'node:fs';
// Observe JSON consumed by the browser: Chrome's inspector evicts upload response bodies.
// No interception, fixtures, auth headers or request payloads are recorded.
async function capture(page:Page,predicate:(response:Response)=>boolean){
 const before=await page.evaluate(()=>(window as unknown as {demoResponses:unknown[]}).demoResponses.length);
 const response=await page.waitForResponse(predicate);
 await page.waitForFunction(({url,before})=>(window as unknown as {demoResponses:Array<{url:string}>}).demoResponses.slice(before).some(row=>row.url===url),{url:response.url(),before});
 const body=await page.evaluate(url=>(window as unknown as {demoResponses:Array<{url:string;body:unknown}>}).demoResponses.filter(row=>row.url===url).at(-1)?.body,response.url());
 return {status:()=>response.status(),body};
}
test.skip(process.env.RUN_GALLERY_DEMOS!=='1','Bounded real-provider demo opt-in required');
test('Demo A/B/C: progressive evidence, actual personal match, persistent conflict and follow-up',async({page})=>{
 test.setTimeout(600000);
 const course=JSON.parse(readFileSync('../outputs/gallery-demo/fixture-course.json','utf8')) as {start:string;end:string;demo_only:boolean};
 expect(course.demo_only).toBe(true);
 await page.addInitScript(()=>{
  const observed: Array<{url:string;body:unknown}>=[];
  (window as unknown as {demoResponses:typeof observed}).demoResponses=observed;
  const original=window.fetch.bind(window);
  window.fetch=async(...args:Parameters<typeof fetch>)=>{
   const response=await original(...args);const request=args[0];const url=typeof request==='string'?request:request instanceof URL?request.href:request.url;
   if(args[1]?.method==='POST'&&(url.includes('/api/evidence/')||url.includes('/api/agent/messages'))){void response.clone().json().then((body:unknown)=>{observed.push({url:new URL(url,location.href).href,body});if(observed.length>20)observed.shift();}).catch(()=>undefined);}
   return response;
  };
 });
 await page.goto('/');await skipInitialGuide(page);await expect(page.getByRole('button',{name:'Medicines',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Medicines',exact:true}).click();await page.getByRole('heading',{name:/Add medication/}).waitFor();await page.getByRole('button',{name:/Scan medication document/}).click();
 await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:'../outputs/gallery-demo/add-source390.png'});
 const workspace=page.getByTestId('evidence-workspace');
 await workspace.getByLabel('Take or choose a photo').setInputFiles('../outputs/gallery-demo/package.png');
 await workspace.getByLabel('I agree to private storage and the selected image processing. Use synthetic files for this demo.').check();
 const savedPackage=capture(page,response=>response.request().method()==='POST'&&/\/api\/evidence\/tasks\/[^/]+\/sources/.test(response.url()));
 const packageAgent=capture(page,response=>response.request().method()==='POST'&&response.url().includes('/api/agent/messages'));
 await workspace.getByRole('button',{name:'Read and save source'}).click();
 const packageResponse=await savedPackage;expect(packageResponse.status()).toBe(200);
 const first=packageResponse.body as {id:string;source_ids:string[];missing:string[];medication_id:string};expect(first.source_ids).toHaveLength(1);expect(first.missing.length).toBeGreaterThan(0);
 const firstAgent=await packageAgent;expect(firstAgent.status()).toBe(200);const firstReply=firstAgent.body as {mode:string;tool_traces:Array<{tool_name:string}>};expect(firstReply.mode).toBe('gemini');expect(firstReply.tool_traces.some(row=>row.tool_name==='reconcile_medication_sources')).toBe(true);
 await expect(workspace.getByText(/Dose or schedule instructions are still missing/)).toBeVisible();await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:'../outputs/gallery-demo/demoA-package390.png',fullPage:true});
 // Restore the durable task through patient UI, not Gemini's temporary text.
 await page.reload();await page.getByRole('button',{name:'Medicines',exact:true}).click();await page.getByRole('button',{name:/Finish medication setup/}).click();await page.getByRole('button',{name:/Metformin|metformin/}).first().click();
 await expect(workspace.getByRole('button',{name:'Review product and medication plan'})).toBeVisible();
 await workspace.getByLabel('Source type').selectOption('pharmacy_label');await workspace.getByLabel('Take or choose a photo').setInputFiles('../outputs/gallery-demo/label.png');
 await workspace.getByLabel('I agree to private storage and the selected image processing. Use synthetic files for this demo.').check();
 const savedLabel=capture(page,response=>response.request().method()==='POST'&&/\/api\/evidence\/tasks\/[^/]+\/sources/.test(response.url()));const labelAgent=capture(page,response=>response.request().method()==='POST'&&response.url().includes('/api/agent/messages'));
 await workspace.getByRole('button',{name:'Read and save source'}).click();const labelResponse=await savedLabel;expect(labelResponse.status()).toBe(200);const supplemented=labelResponse.body as {id:string;source_ids:string[];conflicts:string[]};expect(supplemented.id).toBe(first.id);expect(supplemented.source_ids).toHaveLength(2);expect(supplemented.conflicts).toHaveLength(0);expect((await labelAgent).status()).toBe(200);
 await expect(workspace.getByRole('button',{name:'Review product and medication plan'})).toBeEnabled();
 await workspace.getByRole('button',{name:'Review product and medication plan'}).click();
 await workspace.getByLabel('Dose amount',{exact:true}).fill('1');await workspace.getByLabel('Unit',{exact:true}).fill('tablet');await workspace.getByLabel('Scheduled times',{exact:true}).fill('20:00');await workspace.getByLabel('Food or PRN instructions').fill('with food');
 await workspace.getByLabel('Course start date').fill(course.start);await workspace.getByLabel('Course end date').fill(course.end);
 await workspace.getByLabel('I reviewed these details against my medication instructions.').check();await workspace.getByRole('button',{name:'Prepare activation confirmation'}).click();
 await page.getByRole('button',{name:'Yes, save this medication'}).click();await expect(workspace.getByText('Your medication plan is active.')).toBeVisible();
 await page.getByRole('button',{name:'Today',exact:true}).click();await expect(page.getByText(/metformin/i).first()).toBeVisible();await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:'../outputs/gallery-demo/demoA-today390.png',fullPage:true});
 // Demo B: own private reference -> actual embedding -> reload -> actual /match.
 await page.getByRole('button',{name:'Medicines',exact:true}).click();await page.getByRole('button',{name:/Personal gallery/}).click();await expect(page.locator('.gallery-entry')).toHaveCount(1);await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:'../outputs/gallery-demo/gallery-list390.png'});await page.locator('.gallery-entry').first().click();
 await page.getByLabel('Take or choose a photo').filter({visible:true}).setInputFiles('../outputs/gallery-demo/pill.png');await page.getByLabel('Where is this reference from?').fill('DEMO generated pill from reviewed product');await page.getByLabel('I reviewed this photo against the selected product and its source.').check();await page.getByLabel('I agree to private storage and the selected image processing. Use synthetic files for this demo.').filter({visible:true}).check();
 const upload=capture(page,response=>response.request().method()==='POST'&&/\/api\/evidence\/gallery\/[^/]+\/images/.test(response.url()));await page.getByRole('button',{name:'Save reference photo'}).click();const uploaded=await upload;expect(uploaded.status()).toBe(200);const reference=uploaded.body as {id:string;eligibility:string};expect(reference.eligibility).toBe('eligible');
 await expect(page.getByText(/Available for visual comparison/)).toBeVisible();await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:'../outputs/gallery-demo/demoB-reference390.png',fullPage:true});
 await page.reload();await page.getByRole('button',{name:'Medicines',exact:true}).click();await page.getByRole('button',{name:/Personal gallery/}).click();await page.locator('.gallery-entry').first().click();await expect(page.getByText(/Available for visual comparison/)).toBeVisible();
 await page.getByRole('button',{name:'Source information and review',exact:true}).click();await workspace.getByText(/Linked source information/).click();await expect(workspace.getByText('Reviewed against source by you',{exact:false})).toHaveCount(2);await page.getByRole('button',{name:'Medicines',exact:true}).click();await page.getByRole('button',{name:/Personal gallery/}).click();await page.locator('.gallery-entry').first().click();
 await expect(page.getByRole('button',{name:'Check this dose',exact:true})).toHaveCount(0);await page.locator('[data-guide="medicines"]').click();await page.locator('.medication-list-row').first().click();await page.getByRole('button',{name:'Compare a pill photo',exact:true}).click();await page.getByRole('button',{name:'Check this dose',exact:true}).click();await page.getByLabel('Take or choose a photo').filter({visible:true}).setInputFiles('../outputs/gallery-demo/pill.png');await page.getByLabel('This is a synthetic demo image. I agree to send it for visual evidence.').check();
 const matched=capture(page,response=>response.url().includes('/api/evidence/check-dose'));await page.getByRole('button',{name:'Check photo'}).click();const matchedResponse=await matched;expect(matchedResponse.status()).toBe(200);const result=matchedResponse.body as {decision:string;reference_ids:string[];outcome:unknown;safe_to_take:boolean};expect(result.reference_ids).toContain(reference.id);expect(result.outcome).not.toBeNull();expect(result.safe_to_take).toBe(false);await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:'../outputs/gallery-demo/demoB-result390.png',fullPage:true});await page.screenshot({path:'../outputs/gallery-demo/demoB-result-viewport390.png'});
 // Demo C: explicitly selected existing identity + conflicting new label.
 await page.getByRole('button',{name:'Medicines',exact:true}).click();await page.getByRole('heading',{name:/Add medication/}).waitFor();await page.getByRole('button',{name:/Scan medication document/}).click();await workspace.getByRole('button',{name:'Start a different registration'}).click();
 await expect(workspace.getByRole('option',{name:/metformin/i})).toHaveCount(1);await workspace.getByLabel('Link to a registered product').selectOption(first.medication_id);await workspace.getByLabel('Source type').selectOption('pharmacy_label');await workspace.getByLabel('Take or choose a photo').setInputFiles('../outputs/gallery-demo/conflict.png');
 await workspace.getByLabel('I agree to private storage and the selected image processing. Use synthetic files for this demo.').check();const conflict=capture(page,response=>response.request().method()==='POST'&&/\/api\/evidence\/tasks\/[^/]+\/sources/.test(response.url()));const conflictAgent=capture(page,response=>response.request().method()==='POST'&&response.url().includes('/api/agent/messages'));await workspace.getByRole('button',{name:'Read and save source'}).click();expect((await conflict).status()).toBe(200);expect((await conflictAgent).status()).toBe(200);
 await expect(workspace.getByText('Sources need clarification')).toBeVisible();await expect(workspace.getByRole('button',{name:'Review product and medication plan'})).toBeDisabled();await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:'../outputs/gallery-demo/demoC-conflict390.png',fullPage:true});
 await page.locator('[data-guide="today"]').click();await page.getByRole('button',{name:'Open full chat',exact:true}).click();await page.getByLabel('Review your message before sending').fill('The pharmacy label strength conflicts. What source should I provide?');const followup=capture(page,response=>response.request().method()==='POST'&&response.url().includes('/api/agent/messages'));await page.getByRole('button',{name:'Send',exact:true}).click();const followupReply=(await followup).body as {mode:string;tool_traces:Array<{tool_name:string}>};expect(followupReply.mode).toBe('gemini');expect(followupReply.tool_traces.some(row=>row.tool_name==='reconcile_medication_sources')).toBe(true);
 await page.reload();await page.getByRole('button',{name:'Medicines',exact:true}).click();await page.getByRole('button',{name:/Finish medication setup/}).click();await page.getByRole('button',{name:/Sources need clarification/}).click();await expect(workspace.getByText('Sources need clarification')).toBeVisible();
 await page.setViewportSize({width:430,height:932});await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:'../outputs/gallery-demo/demoC-restored430.png',fullPage:true});await page.setViewportSize({width:1280,height:900});await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:'../outputs/gallery-demo/demoC-desktop.png',fullPage:true});
 writeFileSync('../outputs/gallery-demo/live-demo-results.json',JSON.stringify({
  classification:'REAL_BROWSER_E2E_WITH_SYNTHETIC_INPUT',provider:firstReply.mode,
  tools:firstReply.tool_traces.map(row=>row.tool_name),sources:supplemented.source_ids.length,
  reference_eligibility:reference.eligibility,personal_match:result,conflict_followup:followupReply.mode,
  physical_camera:'MANUAL_PENDING',safety:'No intake action requested; safe_to_take=false',
 },null,2));
 // Persist the same language preference through the real Settings UI, then resume in Chinese.
 await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'Language and speech',exact:true}).click();
 await page.getByLabel('Settings language').selectOption('zh');await expect(page.getByRole('heading',{name:'语言与语音'})).toBeVisible();
 await page.reload();await page.getByRole('button',{name:'药物',exact:true}).click();await page.getByRole('button',{name:/完成药物设置/}).click();await page.getByRole('button',{name:/来源资料需要进一步核对/}).click();
 await expect(workspace.getByText('来源资料需要进一步核对')).toBeVisible();await expect(workspace.getByRole('button',{name:'核对药物与用药计划'})).toBeDisabled();
 await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:'../outputs/gallery-demo/demoC-restored-zh390.png',fullPage:true});await page.screenshot({path:'../outputs/gallery-demo/demoC-restored-zh-viewport390.png'});
 console.log('Demo A/B/C real browser synthetic-data journeys complete; physical camera acceptance pending.');
});
