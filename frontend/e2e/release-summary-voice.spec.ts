/** Actual App/FastAPI/synthetic records; browser speech events explicitly simulated. */
import {expect,test} from '@playwright/test';
import {mockPatientApp} from './polish-a1-fixture';

test('summary exposes factual overview, numeric health evidence and recoverable cancelled speech',async({page,baseURL})=>{
 test.setTimeout(60000);expect(new URL(baseURL!).port).toBe('5191');
 const {errors}=await mockPatientApp(page,true,{token:'DEMO.correctness02-synthetic-token',owner:'de020000-0000-4000-8000-000000000001'});
 await page.route(url=>new URL(url).pathname.startsWith('/api/'),route=>route.continue());
 await page.addInitScript(()=>{
  class Speech {
   lang='en';continuous=false;interimResults=false;onstart:(()=>void)|null=null;onend:(()=>void)|null=null;
   onerror:((event:{error:string})=>void)|null=null;onresult:((event:unknown)=>void)|null=null;
   start(){this.onstart?.();window.addEventListener('release-speech-abort',()=>this.onerror?.({error:'aborted'}),{once:true});}
   stop(){this.onend?.();}abort(){this.onend?.();}
  }
  Object.defineProperty(window,'webkitSpeechRecognition',{value:Speech});
  Object.defineProperty(window,'SpeechRecognition',{value:Speech});
 });
 const headers={Authorization:'Bearer DEMO.correctness02-synthetic-token'};
 await page.request.put('/api/me/preferences',{headers,data:{preferred_language:'en',text_scale_percent:100}});
 await page.goto('/');await page.locator('[data-guide="records"]').click();await page.getByRole('button',{name:'This week',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Overview',exact:true})).toBeVisible();
 await expect(page.locator('.summary-overview')).toContainText('3 health observations');
 await page.getByText('Detailed records and sources',{exact:true}).click();
 await expect(page.locator('.report-details')).toContainText('128/82 mmHg');
 for(const width of [390,1280]){
  await page.setViewportSize({width,height:900});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:`../outputs/release/summary-${width}.png`,fullPage:true});
 }
 await page.locator('[data-guide="records"]').click();await page.getByRole('button',{name:/Medication review preparation/}).click();
 await expect(page.getByRole('heading',{name:'Items to confirm and next steps'})).toBeVisible();
 await expect(page.locator('.summary-overview')).toContainText('Which scheduled doses');
 await page.getByText('Detailed records and sources',{exact:true}).click();await expect(page.locator('.report-details')).toContainText('128/82 mmHg');
 await page.locator('[data-guide="today"]').click();await page.getByRole('button',{name:'Open full chat',exact:true}).click();
 const input=page.getByRole('textbox');await input.fill('Keep this draft');
 const sends:string[]=[];page.on('request',r=>{if(r.method()==='POST'&&new URL(r.url()).pathname==='/api/agent/messages')sends.push(r.url());});
 await page.getByRole('button',{name:'Speak your message',exact:true}).click();
 await expect(page.getByRole('button',{name:'Stop listening',exact:true})).toBeVisible();
 await page.evaluate(()=>window.dispatchEvent(new Event('release-speech-abort')));
 await expect(page.getByText('Listening cancelled. You can still type.',{exact:true})).toBeVisible();
 await expect(page.getByText('Listening cancelled. You can still type.',{exact:true})).toHaveCount(0,{timeout:10000});
 await expect(input).toHaveValue('Keep this draft');expect(sends).toEqual([]);expect(errors).toEqual([]);
});
