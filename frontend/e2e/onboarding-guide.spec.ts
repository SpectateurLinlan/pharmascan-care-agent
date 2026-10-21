import {expect,test} from '@playwright/test';

for(const locale of ['en','zh'] as const){
 test(`six-step onboarding is navigable, localized and responsive (${locale})`,async({page},testInfo)=>{
  let preferenceLanguage=locale;
  const pageErrors:string[]=[];page.on('pageerror',error=>pageErrors.push(error.message));
  await page.addInitScript(()=>{
   class MockUtterance { text:string;lang='';rate=1;voice?:SpeechSynthesisVoice;onend:(()=>void)|null=null;onerror:(()=>void)|null=null;constructor(text:string){this.text=text;} }
   Object.defineProperty(window,'SpeechSynthesisUtterance',{configurable:true,value:MockUtterance});
   Object.defineProperty(window,'speechSynthesis',{configurable:true,value:{cancel(){},getVoices:()=>[],speak(){},addEventListener(){},removeEventListener(){}}});
  });
  await page.route(url=>url.pathname.startsWith('/api/')||url.pathname.endsWith('/auth/v1/signup'),async route=>{
   const url=new URL(route.request().url()),path=url.pathname,method=route.request().method();
   const json=(body:unknown)=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
   if(path.endsWith('/auth/v1/signup'))return json({access_token:'DEMO-onboarding-token',token_type:'bearer',expires_in:3600,expires_at:Math.floor(Date.now()/1000)+3600,refresh_token:'DEMO-onboarding-refresh',user:{id:'00000000-0000-4000-a000-000000000001',aud:'authenticated',role:'authenticated',email:null,app_metadata:{provider:'anonymous',providers:[]},user_metadata:{demo_only:true},created_at:'2026-10-20T00:00:00Z',is_anonymous:true}});
   if(path==='/api/health')return json({status:'ok',service:'medithread',database:'simulated_in_memory',llm:'unavailable_deterministic_degraded',stage2_vision:'simulated',runtime_contract:'patient-ux-reminders-v1'});
   if(path==='/api/demo/start')return json({patient_id:'DEMO-onboarding-owner',session_id:'DEMO-onboarding-session',demo_only:true,seeded_medication_count:0,note:'demo_only'});
   if(path==='/api/me/preferences'&&method==='PUT'){
    const changes=route.request().postDataJSON() as {preferred_language?:string};if(changes.preferred_language==='zh'||changes.preferred_language==='en')preferenceLanguage=changes.preferred_language;
   }
   if(path==='/api/me/preferences')return json({patient_id:'DEMO-onboarding-owner',preferred_language:preferenceLanguage,speech_locale:preferenceLanguage==='zh'?'zh-CN':'en-SG',text_size:'standard',voice_enabled:true,tts_autoplay:false,reminder_lead_minutes:0,reminders_enabled:false,timezone:'Asia/Singapore',created_at:'2026-10-20T00:00:00Z',updated_at:'2026-10-20T00:00:00Z'});
   if(path==='/api/me/medications')return json({item_count:0,medications:[],note:'demo_only'});
   if(path==='/api/me/regimens'||path==='/api/evidence/tasks')return json([]);
   return json([]);
  });
  await page.setViewportSize({width:390,height:844});
  await page.goto('/#today?search=preserve-me');
  const dialogName=locale==='zh'?'新手指引':'Getting Started';
  const dialog=page.getByRole('dialog',{name:dialogName});
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText(locale==='zh'?'查看今日安排':"Check Today's Schedule",{exact:true})).toBeVisible();
  await expect(dialog.getByText(locale==='zh'?'未记录不代表未服药。':'Not recorded does not mean not taken.',{exact:true})).toBeVisible();
  const todayTarget=page.locator('#today-medication');await expect(todayTarget).toBeVisible();
  expect(await todayTarget.evaluate(element=>element.classList.contains('today-medication-anchor'))).toBe(true);
  const historyLength=await page.evaluate(()=>history.length);
  const nextName=locale==='zh'?'下一步':'Next';
  const readButton=dialog.getByRole('button',{name:locale==='zh'?'朗读':'Read Aloud'});
  await expect(readButton).toBeEnabled();
  const readStyle=await readButton.evaluate(element=>({background:getComputedStyle(element).backgroundColor,color:getComputedStyle(element).color,border:getComputedStyle(element).borderColor}));
  expect(readStyle.background).not.toBe('rgba(0, 0, 0, 0)');expect(readStyle.background).not.toBe('rgb(255, 255, 255)');
  await readButton.click();const stopButton=dialog.getByRole('button',{name:locale==='zh'?'停止':'Stop Reading'});await expect(stopButton).toHaveAttribute('aria-pressed','true');
  const activeReadStyle=await stopButton.evaluate(element=>getComputedStyle(element).backgroundColor);expect(activeReadStyle).not.toBe(readStyle.background);
  await stopButton.click();await expect(dialog.getByRole('button',{name:locale==='zh'?'朗读':'Read Aloud'})).toHaveAttribute('aria-pressed','false');
  const initialDialog=await dialog.boundingBox(),initialNext=await dialog.getByRole('button',{name:nextName,exact:true}).boundingBox();
  expect(initialDialog).not.toBeNull();expect(initialNext).not.toBeNull();
  const titles=locale==='zh'?['添加与管理药物','回顾用药与健康记录','向 AI 助手提问','使用文字、照片或语音','管理账户与个人设置']:['Add and Manage Medications','Review Medication and Health Records','Ask the AI Assistant','Use Text, Photos, or Voice','Manage Your Account and Settings'];
  const routes=['medicines','records','assistant','assistant','me'];
  let summaryWidthDuring=0,summaryWidthBefore=0;
  await dialog.getByRole('button',{name:nextName,exact:true}).click();await expect(page).toHaveURL(/#medicines/);
  await dialog.getByRole('button',{name:locale==='zh'?'上一步':'Back',exact:true}).click();await expect(page).toHaveURL(/#today(?:\?|$)/);
  for(let i=0;i<titles.length;i++){
   await dialog.getByRole('button',{name:locale==='zh'?'下一步':'Next',exact:true}).click();
   await expect(dialog.getByRole('heading',{name:titles[i],exact:true})).toBeVisible();
   await expect(page).toHaveURL(new RegExp(`#${routes[i]}(?:\\?|$)`));
   expect(await page.evaluate(()=>history.length)).toBe(historyLength);
    const actionName=i===titles.length-1?(locale==='zh'?'完成':'Finish'):nextName;
    const stableDialog=await dialog.boundingBox(),stableNext=await dialog.getByRole('button',{name:actionName,exact:true}).boundingBox();
    expect(stableDialog).not.toBeNull();expect(stableNext).not.toBeNull();
    expect(stableDialog!.x).toBeCloseTo(initialDialog!.x,0);expect(stableDialog!.y).toBeCloseTo(initialDialog!.y,0);expect(stableDialog!.width).toBeCloseTo(initialDialog!.width,0);expect(stableDialog!.height).toBeCloseTo(initialDialog!.height,0);
    expect(stableNext!.x).toBeCloseTo(initialNext!.x,0);expect(stableNext!.y).toBeCloseTo(initialNext!.y,0);expect(stableNext!.width).toBeCloseTo(initialNext!.width,0);expect(stableNext!.height).toBeCloseTo(initialNext!.height,0);
    const targetSelector=['[data-guide="medication-add"]','.records-summary--highlight','[data-guide="assistant-conversation"]','[data-guide="assistant-composer"]','[data-guide="me-settings"]'][i]!;
    const target=page.locator(targetSelector);await expect(target).toBeVisible();
    const targetBox=await target.boundingBox(),dialogBox=await dialog.boundingBox();expect(targetBox).not.toBeNull();expect(dialogBox).not.toBeNull();
    const intersects=targetBox!.x<dialogBox!.x+dialogBox!.width&&targetBox!.x+targetBox!.width>dialogBox!.x&&targetBox!.y<dialogBox!.y+dialogBox!.height&&targetBox!.y+targetBox!.height>dialogBox!.y;
    if(!intersects){const highlight=page.locator('.guide-highlight');await expect(highlight).toBeVisible();const highlightBox=await highlight.boundingBox();expect(highlightBox!.width).toBeGreaterThanOrEqual(targetBox!.width);expect(highlightBox!.height).toBeGreaterThanOrEqual(targetBox!.height);}
    if(i===1)expect(intersects).toBe(false);
    if(i===0){const choiceCount=await target.locator('button,a,[role="button"]').count();expect(choiceCount).toBeGreaterThanOrEqual(2);}
    if(i===1){
     const recordsDuring=await target.evaluate(element=>({width:element.closest('.records-summary--highlight')!.getBoundingClientRect().width,display:getComputedStyle(element).display,style:element.getAttribute('style')}));
     expect(recordsDuring.width).toBeGreaterThan(await page.evaluate(()=>innerWidth*.7));expect(recordsDuring.display).not.toBe('contents');expect(recordsDuring.style).toBeNull();
     const summary=page.locator('.records-summary--highlight');summaryWidthDuring=await summary.evaluate(element=>element.getBoundingClientRect().width);
     expect(summaryWidthDuring).toBeGreaterThan(await page.evaluate(()=>innerWidth*.7));
     if(summaryWidthBefore)expect(summaryWidthDuring).toBeCloseTo(summaryWidthBefore,0);
     await page.screenshot({path:testInfo.outputPath(`records-guide-${locale}.png`)});
    }
    if(i===2)expect(await target.evaluate(element=>element.closest('.assistant-toolbar,.assistant-header,.app-header')===null)).toBe(true);
   if(i===0){
    for(const width of [390,768,1280]){
     await page.setViewportSize({width,height:900});
     const box=await dialog.boundingBox();expect(box).not.toBeNull();
     expect(box!.x).toBeGreaterThanOrEqual(0);expect(box!.x+box!.width).toBeLessThanOrEqual(width);
     expect(box!.height).toBeLessThanOrEqual(900);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
     await page.screenshot({path:testInfo.outputPath(`guide-${locale}-${width}.png`)});
    }
    await page.setViewportSize({width:390,height:844});
   }
  }
  await dialog.getByRole('button',{name:locale==='zh'?'完成':'Finish',exact:true}).click();
  const completionDialog=page.getByRole('dialog',{name:locale==='zh'?'准备就绪！':"You're All Set!"});
  await expect(completionDialog.getByRole('heading',{name:locale==='zh'?'准备就绪！':"You're All Set!",exact:true})).toBeVisible();
  await expect(completionDialog.getByRole('button',{name:locale==='zh'?'开始使用':'Start Using MediThread',exact:true})).toBeFocused();
  await page.screenshot({path:testInfo.outputPath(`guide-complete-${locale}.png`)});
  await expect(page).toHaveURL('/#today?search=preserve-me');
  expect(await page.evaluate(()=>history.length)).toBe(historyLength);
  await completionDialog.getByRole('button',{name:locale==='zh'?'开始使用':'Start Using MediThread',exact:true}).click();
  await expect(completionDialog).toHaveCount(0);
  await expect(page.locator('[data-guide="today"]')).toBeFocused();
  await page.locator('[data-guide="records"]').click();
  const recordsAfter=page.locator('.records-summary--highlight');await expect(recordsAfter).toBeVisible();
  const recordsGeometry=await recordsAfter.evaluate(element=>({width:element.closest('.records-summary--highlight')!.getBoundingClientRect().width,display:getComputedStyle(element).display,style:element.getAttribute('style')}));
  expect(recordsGeometry.width).toBeGreaterThan(await page.evaluate(()=>innerWidth*.7));expect(recordsGeometry.display).not.toBe('contents');expect(recordsGeometry.style).toBeNull();
  const summaryWidthAfter=await page.locator('.records-summary--highlight').evaluate(element=>element.getBoundingClientRect().width);
  expect(summaryWidthAfter).toBeCloseTo(summaryWidthDuring,0);
  await page.screenshot({path:testInfo.outputPath(`records-no-guide-${locale}.png`)});
  for(const origin of ['today','me','medicines','records']){
   const returnUrl=`/#${origin}?origin=return-test`;
   await page.goto(returnUrl);await page.reload();
   if(origin==='records'){
    await expect(page.locator('.records-summary--highlight')).toBeVisible();
    summaryWidthBefore=await page.locator('.records-summary--highlight').evaluate(element=>element.getBoundingClientRect().width);
    await page.screenshot({path:testInfo.outputPath(`records-before-guide-${locale}.png`)});
   }
   await page.evaluate(()=>localStorage.setItem('pharmascan.quick-start.v5:DEMO-onboarding-owner',JSON.stringify({version:5,status:'in_progress',step:0})));
   await page.reload();const returningGuide=page.getByRole('dialog',{name:dialogName});await expect(returningGuide).toBeVisible();
   for(let step=0;step<5;step++)await returningGuide.getByRole('button',{name:nextName,exact:true}).click();
   await returningGuide.getByRole('button',{name:locale==='zh'?'完成':'Finish',exact:true}).click();
   await expect(page).toHaveURL(`/#${origin}?origin=return-test`);
   const returnedCompletion=page.getByRole('dialog',{name:locale==='zh'?'准备就绪！':"You're All Set!"});await returnedCompletion.getByRole('button',{name:locale==='zh'?'开始使用':'Start Using MediThread',exact:true}).click();
   await expect(returnedCompletion).toHaveCount(0);await expect(page).toHaveURL(`/#${origin}?origin=return-test`);
   if(origin==='records'){
    const afterWidth=await page.locator('.records-summary--highlight').evaluate(element=>element.getBoundingClientRect().width);
    expect(afterWidth).toBeCloseTo(summaryWidthBefore,0);await page.screenshot({path:testInfo.outputPath(`records-after-guide-${locale}.png`)});
   }
  }
  await page.evaluate(()=>localStorage.setItem('pharmascan.quick-start.v5:DEMO-onboarding-owner',JSON.stringify({version:5,status:'in_progress',step:0})));
  await page.goto('/#medicines?origin=skip-test');await page.reload();await expect(page.getByRole('dialog',{name:dialogName})).toBeVisible();
  await page.getByRole('button',{name:locale==='zh'?'跳过指引':'Skip Guide'}).click();await expect(page).toHaveURL('/#medicines?origin=skip-test');
  await page.evaluate(()=>localStorage.setItem('pharmascan.quick-start.v5:DEMO-onboarding-owner',JSON.stringify({version:5,status:'in_progress',step:0})));
  await page.goto('/#records?origin=close-test');await page.reload();const closeGuide=page.getByRole('dialog',{name:dialogName});await expect(closeGuide).toBeVisible();
  await closeGuide.getByRole('button',{name:locale==='zh'?'关闭指引':'Close Guide'}).click();await expect(closeGuide).toHaveCount(0);await expect(page).toHaveURL('/#records?origin=close-test');
  expect(pageErrors).toEqual([]);
 });
}
