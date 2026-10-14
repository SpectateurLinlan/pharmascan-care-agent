/** AUTOMATED/SYNTHETIC: real browser capability, injected utterance/voice service; no audible acceptance or provider calls. */
import {test,expect} from '@playwright/test';
test('native synthesis capability and en/zh adapter lifecycle without any cloud request',async({page})=>{
  let requests=0;
  page.on('request',request=>{if(request.url().includes('/api/speech/'))requests++;});
  await page.route('**/tts-qa',route=>route.fulfill({contentType:'text/html',body:'<html><body>synthetic speech QA</body></html>'}));
  await page.goto('/tts-qa');
  const result=await page.evaluate(async()=>{
    const nativeSupported=Boolean(window.speechSynthesis&&window.SpeechSynthesisUtterance);
    const nativeVoices=window.speechSynthesis?.getVoices().map(v=>({lang:v.lang,local:v.localService}))??[];
    // Import the actual adapter through Vite; the service below is deliberately synthetic.
    const path='/src/browserTts.ts';
    const {BrowserTts}=await import(/* @vite-ignore */path) as typeof import('../src/browserTts');
    const events=new EventTarget(),utterances:SpeechSynthesisUtterance[]=[];
    let voices:SpeechSynthesisVoice[]=[];
    const voice=(lang:string)=>({lang,localService:true,name:`DEMO ${lang}`} as SpeechSynthesisVoice);
    const service={getVoices:()=>voices,cancel:()=>undefined,speak:(u:SpeechSynthesisUtterance)=>{utterances.push(u);},addEventListener:events.addEventListener.bind(events),removeEventListener:events.removeEventListener.bind(events)} as unknown as SpeechSynthesis;
    let ended=0,failed=0;
    const nativeUtterance=new SpeechSynthesisUtterance('DEMO capability check');
    const tts=new BrowserTts(service,text=>({text,onend:null,onerror:null} as SpeechSynthesisUtterance));
    tts.play('DEMO Metformin 500 mg','en',.9,()=>ended++,()=>failed++);
    const delayed=utterances.length===0;
    voices=[voice('en-SG'),voice('zh-CN')];events.dispatchEvent(new Event('voiceschanged'));
    const old=utterances[0]!,oldEnd=old.onend;
    tts.play('演示：二甲双胍 500 毫克','zh',.9,()=>ended++,()=>failed++);
    oldEnd?.call(old,new Event('end') as SpeechSynthesisEvent);
    const staleIgnored=ended===0;
    const current=utterances[1]!;current.onend?.call(current,new Event('end') as SpeechSynthesisEvent);
    tts.play('DEMO replay','en',.9,()=>ended++,()=>failed++);tts.stop();
    return {nativeSupported:nativeSupported&&nativeUtterance.text==='DEMO capability check',nativeVoices,delayed,staleIgnored,ended,failed,languages:utterances.map(u=>u.lang),rates:utterances.map(u=>u.rate)};
  });
  expect(result.nativeSupported).toBe(true);expect(result.delayed).toBe(true);expect(result.staleIgnored).toBe(true);
  expect(result.languages).toEqual(['en-SG','zh-CN','en-SG']);expect(result.rates).toEqual([.9,.9,.9]);
  expect(result.ended).toBe(1);expect(result.failed).toBe(0);expect(requests).toBe(0);
  console.log(`Native voices available: ${result.nativeVoices.length}; AUTOMATED/SYNTHETIC playback wiring only`);
});
