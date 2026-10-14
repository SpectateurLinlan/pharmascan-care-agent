import {afterEach,expect,it,vi} from 'vitest';
import {BrowserTts,selectVoice} from './browserTts';
const voice=(lang:string,localService=true)=>({lang,localService,name:lang} as SpeechSynthesisVoice);
function fixture(voices:SpeechSynthesisVoice[]=[voice('en-SG'),voice('zh-CN')]) {
  const events=new EventTarget();
  const synth={getVoices:vi.fn(()=>voices),cancel:vi.fn(),speak:vi.fn(),addEventListener:events.addEventListener.bind(events),removeEventListener:events.removeEventListener.bind(events)};
  const make=vi.fn(text=>({text,onend:null,onerror:null} as SpeechSynthesisUtterance));
  const tts=new BrowserTts(synth as unknown as SpeechSynthesis,make);
  return {synth,make,tts,events};
}
afterEach(()=>vi.useRealTimers());
it('selects actual English/Mandarin voices, prefers local, and never substitutes Cantonese or another language',()=>{
 expect(selectVoice([voice('en-US'),voice('en-SG')],'en')?.lang).toBe('en-SG');
 expect(selectVoice([voice('en-SG',false),voice('en-GB')],'en')?.lang).toBe('en-GB');
 expect(selectVoice([voice('zh-CN'),voice('zh-SG')],'zh')?.lang).toBe('zh-SG');
 expect(selectVoice([voice('zh-HK'),voice('en-SG')],'zh')).toBeUndefined();
});
it.each(['en','zh'] as const)('plays %s at clear slow speed and completes once',language=>{
 const {tts,make,synth}=fixture(),ended=vi.fn(),failed=vi.fn();
 tts.play('DEMO Metformin 500 mg',language,.9,ended,failed);
 const utterance=make.mock.results[0]!.value;
 expect(utterance.lang).toBe(language==='en'?'en-SG':'zh-CN');expect(utterance.rate).toBe(.9);
 expect(synth.speak).toHaveBeenCalledTimes(1);utterance.onend?.(new Event('end') as SpeechSynthesisEvent);
 expect(ended).toHaveBeenCalledTimes(1);expect(failed).not.toHaveBeenCalled();
});
it('waits for voiceschanged and removes listeners after selection',()=>{
 vi.useFakeTimers();const {tts,make,synth,events}=fixture([]),failed=vi.fn();
 tts.play('DEMO','zh',.9,vi.fn(),failed);expect(make).not.toHaveBeenCalled();
 synth.getVoices.mockReturnValue([voice('zh-CN')]);events.dispatchEvent(new Event('voiceschanged'));
 events.dispatchEvent(new Event('voiceschanged'));expect(make).toHaveBeenCalledTimes(1);tts.stop();vi.runAllTimers();expect(failed).not.toHaveBeenCalled();
});
it('missing language times out without speaking in the wrong language',()=>{
 vi.useFakeTimers();const {tts,synth}=fixture([voice('en-SG')]),failed=vi.fn();
 tts.play('DEMO','zh',.9,vi.fn(),failed);vi.advanceTimersByTime(3000);
 expect(failed).toHaveBeenCalledTimes(1);expect(synth.speak).not.toHaveBeenCalled();
});
it('stop/replay/language change invalidate earlier callbacks and pending loads',()=>{
 const {tts,make}=fixture(),ended=vi.fn(),failed=vi.fn();
 tts.play('DEMO old','en',.9,ended,failed);const oldCallback=make.mock.results[0]!.value.onend;
 tts.play('DEMO new','zh',.9,ended,failed);oldCallback?.(new Event('end') as SpeechSynthesisEvent);
 expect(ended).not.toHaveBeenCalled();tts.stop();expect(failed).not.toHaveBeenCalled();
});
it('unsupported and synthesis failure preserve a text fallback',()=>{
 const failed=vi.fn();new BrowserTts(undefined,undefined).play('DEMO','en',.9,vi.fn(),failed);
 const {tts,synth}=fixture();synth.speak.mockImplementation(()=>{throw new Error('SIMULATED');});
 tts.play('DEMO','en',.9,vi.fn(),failed);expect(failed).toHaveBeenCalledTimes(2);
});
