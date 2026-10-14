/** REAL Auth/application; AUTOMATED SYNTHETIC STT and browser synthesis events, no billable speech calls. */
import { test, expect } from '@playwright/test';
test.skip(process.env.RUN_LIVE_BROWSER !== '1', 'Explicit live browser opt-in required');
test('mobile companion synthetic speech -> real Agent -> consent -> synthetic browser playback',async({page})=>{
  let cloudRequests=0;
  await page.route('**/api/speech/synthesize*',route=>{cloudRequests++;return route.abort();});
  let reportWrites=0;
  page.on('request',request=>{if(request.method()==='POST' && /\/report(?:\?|$)/.test(request.url())) reportWrites++;});
  await page.addInitScript(()=>{
    class SyntheticSpeech {
      lang='';continuous=false;interimResults=false;maxAlternatives=1;
      onstart:(()=>void)|null=null;onaudioend:(()=>void)|null=null;onend:(()=>void)|null=null;
      onerror:((event:{error:string})=>void)|null=null;
      onresult:((event:{resultIndex:number;results:{isFinal:boolean;0:{transcript:string;confidence:number}}[]})=>void)|null=null;
      start(){document.documentElement.dataset.recognitionLanguage=this.lang;this.onstart?.();window.addEventListener('synthetic-speech',this.result,{once:true});}
      result=(event:Event)=>{this.onresult?.({resultIndex:0,results:[{isFinal:true,0:{transcript:(event as CustomEvent<string>).detail,confidence:0.5}}]});this.onend?.();};
      stop(){this.onend?.();} abort(){window.removeEventListener('synthetic-speech',this.result);this.onend?.();}
    }
    Object.defineProperty(window,'webkitSpeechRecognition',{value:SyntheticSpeech});
    Object.defineProperty(window,'SpeechRecognition',{value:SyntheticSpeech});
    const events=new EventTarget();
    Object.defineProperty(window,'SpeechSynthesisUtterance',{value:class {onend=null;onerror=null;constructor(public text:string){}}});
    Object.defineProperty(window,'speechSynthesis',{value:{
      getVoices:()=>[{lang:'en-SG',localService:true},{lang:'zh-CN',localService:true}],cancel:()=>undefined,
      addEventListener:events.addEventListener.bind(events),removeEventListener:events.removeEventListener.bind(events),
      speak:(utterance:{lang:string})=>{document.documentElement.dataset.audioPlayed='true';document.documentElement.dataset.spokenLanguage=utterance.lang;}
    }});
  });
  await page.goto('/'); await expect(page.getByRole('button',{name:'Compare a pill photo'})).toBeVisible();
  await expect(page.getByRole('button',{name:'Speak your message'})).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page.locator('h2:visible')).toHaveCount(1);
  await expect(page.getByText(/No dose due right now/)).toBeVisible();
  await page.screenshot({path:'../outputs/home390.png'});
  const composer=await page.locator('.composer-row').boundingBox(); expect(composer?.y).toBeLessThan(720);
  await page.getByRole('button',{name:'My Medicines',exact:true}).click();
  await page.getByRole('button',{name:/Add medication/}).click();await page.getByRole('button',{name:/Add manually/}).click();
  await page.getByLabel('Medication name', {exact:true}).fill('DEMO Metformin synthetic');
  await page.getByLabel('Dose amount',{exact:true}).fill('1'); await page.getByLabel('Unit',{exact:true}).fill('tablet');
  const time=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Singapore',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(Date.now()+120000));
  await page.locator('#med-time-0').fill(time);
  await page.getByRole('button',{name:'Add another time',exact:true}).click();
  await page.locator('#med-time-1').fill('20:00');
  await page.getByRole('button',{name:'Create draft',exact:true}).click();
  await expect(page.getByText('Step 2 of 3: review, then activate. Drafts are not active medications.')).toBeVisible();
  await page.reload(); await page.getByRole('button',{name:'My Medicines',exact:true}).click();
  await page.getByRole('button',{name:/Finish medication setup/}).click();await page.getByRole('button',{name:/DEMO Metformin synthetic/}).click();
  await page.getByRole('button',{name:'I have reviewed these details'}).click();
  await page.getByRole('button',{name:'Show me the summary to confirm'}).click();
  const activation=page.waitForResponse(response=>response.url().includes('/medications/activate'));
  await page.getByRole('button',{name:'Yes, save this medication'}).click();
  expect((await activation).status()).toBe(200);
  await expect(page.getByText(/Regimen activated/)).toBeVisible({timeout:30000});
  await page.reload();
  await page.getByRole('button',{name:'My Medicines',exact:true}).click();
  await expect(page.getByText('DEMO Metformin synthetic',{exact:true}).first()).toBeVisible();
  await page.getByRole('button',{name:'Today',exact:true}).click();
  const messageBox=page.getByLabel('Review your message before sending');
  await messageBox.fill('What medicine should I take tonight?'); await page.getByRole('button',{name:'Send',exact:true}).click();
  await expect(page.getByText(/Your reviewed schedule tonight:.*DEMO Metformin synthetic.*20:00/)).toBeVisible();
  await messageBox.fill("I'm not sure whether I took it."); await page.getByRole('button',{name:'Send',exact:true}).click();
  await expect(page.getByText(/No dose will be marked as taken/)).toBeVisible(); expect(reportWrites).toBe(0);
  const now=new Date(); const parts=time.split(':').map(Number); const singapore=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Singapore',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(now).split(':').map(Number);
  let wait=(parts[0]! * 3600 + parts[1]! * 60 - (singapore[0]! * 3600 + singapore[1]! * 60 + singapore[2]!)) * 1000; if(wait < -60000) wait+=86400000;
  while(wait > 0) { const slice=Math.min(wait,10000); await page.waitForTimeout(slice); wait-=slice; }
  await expect(page.getByRole('dialog',{name:'Medication reminder'})).toBeVisible({timeout:30000});
  expect(reportWrites).toBe(0);await page.getByRole('button',{name:'Dismiss',exact:true}).click();
  await expect(page.getByRole('button',{name:'Taken',exact:true})).toBeVisible({timeout:30000});
  await expect(page.locator('.dose-name')).toHaveText('DEMO Metformin synthetic',{timeout:30000});
  console.log('QA: reviewed active dose available; synthetic recognition next');
  await page.screenshot({path:'../outputs/home390-dose.png'});
  await page.getByRole('button',{name:'Speak your message'}).click(); await page.getByRole('checkbox').click(); await page.getByRole('button',{name:'Speak your message'}).click();
  await page.evaluate(()=>window.dispatchEvent(new CustomEvent('synthetic-speech',{detail:'I took it.'})));
  const message=page.getByLabel('Review your message before sending'); await expect(message).toHaveValue('I took it.'); expect(reportWrites).toBe(0);
  await message.fill('I already took my evening medicine.'); const agentReply=page.waitForResponse(response=>response.url().includes('/agent/message')); await page.getByRole('button',{name:'Send',exact:true}).click();
  const agentResponse=await agentReply; expect(agentResponse.status()).toBe(200); console.log('QA: real Agent response returned');
  await expect(page.getByText('Just to confirm')).toBeVisible({timeout:30000}); expect(reportWrites).toBe(0);
  await page.getByRole('button',{name:'Play response'}).last().click();expect(cloudRequests).toBe(0);
  await expect(page.locator('html')).toHaveAttribute('data-audio-played','true');
  await page.getByRole('button',{name:'Stop audio'}).last().click();
  const reportSaved=page.waitForResponse(response=>/\/report(?:\?|$)/.test(response.url()));
  await page.getByRole('button',{name:'Confirm record'}).click(); expect((await reportSaved).status()).toBe(200);
  await expect(page.getByText(/Your report was saved/)).toBeVisible({timeout:30000}); expect(reportWrites).toBe(1);
  await page.getByRole('button',{name:'History',exact:true}).click(); await expect(page.getByText(/reported taking/).first()).toBeVisible({timeout:30000});

  await page.getByRole('button',{name:'Today',exact:true}).click();
  await page.getByRole('button',{name:'Compare a pill photo'}).click();
  await expect(page.getByLabel('Take or choose a photo')).toBeVisible();
  const png=await page.evaluate(()=>{const canvas=document.createElement('canvas');canvas.width=320;canvas.height=320;const c=canvas.getContext('2d');if(!c)throw new Error('Canvas unavailable');c.fillStyle='white';c.fillRect(0,0,320,320);c.fillStyle='#eee';c.strokeStyle='#777';c.beginPath();c.ellipse(160,160,60,40,0,0,Math.PI*2);c.fill();c.stroke();return canvas.toDataURL('image/png').split(',')[1]!;});
  await page.getByLabel('Take or choose a photo').setInputFiles({name:'synthetic-pill.png',mimeType:'image/png',buffer:Buffer.from(png,'base64')});
  await expect(page.getByAltText('Selected image preview')).toBeVisible();await page.getByRole('checkbox').click();
  const checked=page.waitForResponse(response=>response.url().includes('/visual-check'));
  await page.getByRole('button',{name:'Check photo',exact:true}).click();expect((await checked).status()).toBe(200);
  await expect(page.getByText(/Medicine remains unverified|Photo needs another look/)).toBeVisible();expect(reportWrites).toBe(1);
  await page.getByRole('button',{name:'Back to Today'}).click();
  const languageSaved=page.waitForResponse(r=>r.url().includes('/me/preferences')&&r.request().method()==='PUT');
  await page.getByRole('button',{name:'Settings',exact:true}).click();await page.getByRole('button',{name:/Language and speech/}).last().click();await page.getByLabel('Settings language',{exact:true}).selectOption('zh');expect((await languageSaved).status()).toBe(200);
  await page.reload();await page.getByRole('button',{name:'设置',exact:true}).click();await page.getByRole('button',{name:/语言与语音/}).last().click();
  await expect(page.getByLabel('Settings language',{exact:true})).toHaveValue('zh');
  await page.getByRole('button',{name:'今日',exact:true}).click();
  await page.getByRole('button',{name:'语音输入'}).click();await page.getByRole('checkbox').click();await page.getByRole('button',{name:'语音输入'}).click();
  await expect(page.locator('html')).toHaveAttribute('data-recognition-language','zh-CN');
  await page.evaluate(()=>window.dispatchEvent(new CustomEvent('synthetic-speech',{detail:'今晚吃什么药？'})));
  await page.getByRole('button',{name:'发送',exact:true}).click();
  await expect(page.getByText(/DEMO Metformin synthetic.*20:00/)).toBeVisible();
  await page.getByRole('button',{name:'播放回答'}).last().click();await expect(page.locator('html')).toHaveAttribute('data-spoken-language','zh-CN');expect(cloudRequests).toBe(0);expect(reportWrites).toBe(1);
});
