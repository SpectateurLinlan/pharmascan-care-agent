/** Actual React + local FastAPI/services, synthetic patient, cached labels; no Gemini. */
import {expect,test} from '@playwright/test';
import {mockPatientApp} from './polish-a1-fixture';

for(const width of [390,1280])for(const language of ['en','zh'] as const)test(`patient clarification and source scope at ${width}px ${language}`,async({page})=>{
 test.setTimeout(60000);page.setDefaultTimeout(10000);
 const {errors}=await mockPatientApp(page,true,{token:'DEMO.correctness02-synthetic-token',owner:'de020000-0000-4000-8000-000000000001'});
 await page.route(url=>new URL(url).pathname.startsWith('/api/'),route=>route.continue());
 await page.clock.install({time:new Date('2026-10-18T04:00:00Z')});
 await page.setViewportSize({width,height:900});
 await page.request.put('/api/me/preferences',{headers:{Authorization:'Bearer DEMO.correctness02-synthetic-token'},data:{preferred_language:language,text_scale_percent:100,conversation_history_enabled:true}});
 await page.goto('/');await page.getByRole('button',{name:language==='zh'?'打开完整聊天':'Open full chat',exact:true}).click();
 const input=page.getByRole('textbox');const send=page.getByRole('button',{name:language==='zh'?'发送':'Send',exact:true});
 await input.fill('What does my Amlodipine entry say about my dose?');await send.click();
 const choices=page.getByRole('region',{name:language==='zh'?'选择药物':'Choose a medicine'});
 await expect(choices.getByRole('button')).toHaveCount(2);await expect(choices).not.toContainText('Metformin');
 const selected=choices.getByRole('button',{name:/10 mg/});await selected.focus();await page.keyboard.press('Enter');
 await expect(page.locator('.transcript')).toContainText(language==='zh'?'每次服用 1 片；每天 08:00':'1 tablet per dose; daily at 08:00');
 await expect(page.locator('.transcript')).not.toContainText('DEMO_ONLY reviewed instructions');
 await input.fill('What are those medicines generally used for?');await send.click();
 const sources=page.locator('.answer-sources').last();await expect(sources).toBeVisible();
 await expect(sources).not.toHaveAttribute('open','');await sources.locator('summary').first().click();
 await expect(sources.getByRole('link')).toHaveCount(2);
 await expect(sources).toContainText('NORLIQVA');await expect(sources).toContainText(language==='zh'?'不代表您持有的具体产品':'do not identify your product');
 await sources.getByText(language==='zh'?'查看用途原文（来源标签适用范围）':'Original use excerpt (source label scope)',{exact:true}).first().click();
 await expect(sources).toContainText('6 years of age');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:`../outputs/patient-answer-refinement-${width}-${language}.png`,fullPage:true});
 expect(errors).toEqual([]);
});
