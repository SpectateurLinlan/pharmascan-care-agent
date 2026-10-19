/** Responsive Me page check with synthetic Auth and patient API responses only. */
import {test,expect,type Page} from '@playwright/test';

async function mockMe(page:Page){
 const token='DEMO.me-layout-token',owner='d00d0000-0000-4000-8000-000000000001';
 const user={id:owner,aud:'authenticated',role:'authenticated',email:null,phone:'',app_metadata:{provider:'anonymous',providers:['anonymous']},user_metadata:{demo_only:true},is_anonymous:true,created_at:'2026-10-16T00:00:00Z'};
 await page.addInitScript(({owner})=>localStorage.setItem(`pharmascan.quick-start.v2:${owner}`,JSON.stringify({version:2,status:'skipped',step:0})),{owner});
 await page.route(url=>new URL(url).pathname.includes('/auth/v1/'),async route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/signup')){await route.fulfill({json:{access_token:token,token_type:'bearer',expires_in:3600,refresh_token:'DEMO.refresh',user}});return;}
  if(path.endsWith('/user')){await route.fulfill({json:user});return;}
  throw new Error(`Unexpected synthetic Auth request: ${path}`);
 });
 await page.route(url=>new URL(url).pathname.startsWith('/api/'),async route=>{
  const path=new URL(route.request().url()).pathname;let body:unknown=[];
  if(path==='/api/health')body={status:'ok',runtime_contract:'patient-ux-reminders-v1'};
  else if(path==='/api/demo/start')body={session_id:'DEMO-session',patient_id:owner};
  else if(path==='/api/me/preferences')body={patient_id:owner,display_name:'DEMO Guest',preferred_language:'en',speech_locale:'en-SG',text_size:'standard',text_scale_percent:100,voice_enabled:false,tts_autoplay:false,conversation_history_enabled:false,reminder_lead_minutes:0,reminders_enabled:false,timezone:'Asia/Singapore',created_at:'2026-10-20T00:00:00Z',updated_at:'2026-10-20T00:00:00Z'};
  else if(path==='/api/me/medications')body={medications:[],item_count:0,note:'demo_only'};
  else if(path==='/api/evidence/tasks')body=[];
  else if(path==='/api/agent/conversations'||path.endsWith('/history'))body={entries:[],next_before:null};
  else if(path==='/api/reminders/push/config')body={available:false,public_key:null,test_available:false};
  else if(path==='/api/speech/capabilities')body={cloud_tts_allowed:false};
  await route.fulfill({json:body});
 });
}

test('Me cards fit mobile, tablet and desktop layouts',async({page})=>{
 const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
 await mockMe(page);await page.goto('/e2e/patient-feedback.html?shell=1');await page.locator('[data-guide="me"]').click();
 await expect(page.locator('.me-category')).toHaveCount(3);await expect(page.locator('.me-app-info .ui-row')).toHaveCount(3);
 for(const width of [390,768,1280]){
  await page.setViewportSize({width,height:900});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  const cards=await page.locator('.me-category').evaluateAll(rows=>rows.map(row=>{const box=row.getBoundingClientRect();return{x:box.x,y:box.y,width:box.width,height:box.height};}));
  expect(cards.every(card=>card.width>0&&card.height>0)).toBe(true);
  if(width===390)expect(new Set(cards.map(card=>Math.round(card.y))).size).toBe(3);
  if(width===768){expect(Math.round(cards[0]!.y)).toBe(Math.round(cards[1]!.y));expect(cards[2]!.y).toBeGreaterThan(cards[0]!.y);expect(cards[2]!.width).toBeGreaterThan(cards[0]!.width);}
  if(width===1280){expect(new Set(cards.map(card=>Math.round(card.y))).size).toBe(1);expect(Math.max(...cards.map(card=>card.height))-Math.min(...cards.map(card=>card.height))).toBeLessThan(2);}
  await page.screenshot({path:`../outputs/me-responsive-${width}.png`,fullPage:true});
 }
 expect(errors).toEqual([]);
});
