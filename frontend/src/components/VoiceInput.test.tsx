// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import {StrictMode} from 'react';
import {act} from '@testing-library/react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { VoiceInput } from './VoiceInput';
import { LanguageProvider, useLanguage } from '../language';
import { AssistantScreen } from './AssistantScreen';
import {SettingsScreen} from './SettingsScreen';
import { api } from '../api/client';
import type { NativeRecognition, RecognitionResultEvent, RecognitionErrorEvent } from '../browserSpeech';
vi.mock('../api/client', () => ({ ApiError: class extends Error {}, api: {speechCapabilities:vi.fn(),recentTurns:vi.fn().mockResolvedValue([]), preferences:vi.fn(),updatePreferences:vi.fn(),sendMessage: vi.fn(), synthesize: vi.fn(), submitReport: vi.fn(), submitPrnReport: vi.fn() } }));
class Speech implements NativeRecognition {
  lang=''; continuous=false; interimResults=false; maxAlternatives=1;
  onstart: (() => void) | null=null; onaudioend: (() => void) | null=null; onend: (() => void) | null=null;
  onresult: ((event: RecognitionResultEvent) => void) | null=null;
  onerror: ((event: RecognitionErrorEvent) => void) | null=null;
  start=vi.fn(() => this.onstart?.()); stop=vi.fn(() => this.onend?.()); abort=vi.fn();
  result(text:string) { this.onresult?.({resultIndex:0,results:[{isFinal:true,0:{transcript:text,confidence:0.4}}]}); this.onend?.(); }
}
afterEach(() => { cleanup(); localStorage.clear(); vi.resetAllMocks();vi.mocked(api.recentTurns).mockResolvedValue([]); vi.unstubAllGlobals(); vi.useRealTimers(); });
it('Android aborted feedback expires and a retry accepts a transcript without auto-send',()=>{
 vi.useFakeTimers();const speech=new Speech(),callback=vi.fn();
 render(<VoiceInput provider={{create:()=>speech}} onTranscript={callback}/>);
 fireEvent.click(screen.getByRole('button',{name:'Speak your message'}));
 act(()=>speech.onerror?.({error:'aborted'}));
 expect(screen.getByText(/Listening cancelled/)).toBeTruthy();
 act(()=>vi.advanceTimersByTime(6001));expect(screen.queryByText(/Listening cancelled/)).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'Speak your message'}));act(()=>speech.result('DEMO patient question'));
 expect(callback).toHaveBeenCalledWith('DEMO patient question');expect(api.sendMessage).not.toHaveBeenCalled();
});
it('leaving the active conversation aborts the microphone and ignores its late result',()=>{
 const speech=new Speech(),callback=vi.fn();const view=render(<VoiceInput provider={{create:()=>speech}} onTranscript={callback}/>);
 fireEvent.click(screen.getByRole('button',{name:'Speak your message'}));view.rerender(<VoiceInput provider={{create:()=>speech}} onTranscript={callback} disabled/>);
 act(()=>speech.result('DEMO stale conversation'));expect(callback).not.toHaveBeenCalled();expect(speech.abort).toHaveBeenCalled();
});
it('browser autoplay, stop, replay and language change never call cloud synthesis',async()=>{
 const events=new EventTarget(),utterances:SpeechSynthesisUtterance[]=[];
 const synthesis={cancel:vi.fn(),getVoices:()=>[{lang:'en-SG',localService:true},{lang:'zh-CN',localService:true}],speak:vi.fn((utterance:SpeechSynthesisUtterance)=>utterances.push(utterance)),addEventListener:events.addEventListener.bind(events),removeEventListener:events.removeEventListener.bind(events)};
 vi.stubGlobal('speechSynthesis',synthesis);vi.stubGlobal('SpeechSynthesisUtterance',class {onend=null;onerror=null;constructor(public text:string){}});
 const profile={patient_id:'DEMO',preferred_language:'en',speech_locale:'en-SG',text_size:'standard',voice_enabled:true,tts_autoplay:true,reminder_lead_minutes:0,timezone:'Asia/Singapore',created_at:'2026-10-14T00:00:00Z',updated_at:'2026-10-14T00:00:00Z'} as const;
 vi.mocked(api.preferences).mockResolvedValue(profile);
 vi.mocked(api.sendMessage).mockResolvedValue({message:'DEMO reviewed Metformin 500 mg.',session_id:'demo',intent:'due_query',session_state:'idle',requires_confirmation:false,mode:'deterministic_degraded',tool_traces:[],pending_report:null});
 function Controls(){const {loadPreferences}=useLanguage();return <><button onClick={()=>void loadPreferences()}>Load speech preferences</button><AssistantScreen sessionId="demo" onSession={vi.fn()}/></>;}
 render(<LanguageProvider><Controls/></LanguageProvider>);
 fireEvent.click(screen.getByText('Load speech preferences'));await waitFor(()=>expect(api.preferences).toHaveBeenCalledOnce());
 fireEvent.change(screen.getByLabelText('Review your message before sending'),{target:{value:'What is due?'}});fireEvent.click(screen.getByRole('button',{name:'Send'}));
 await waitFor(()=>expect(synthesis.speak).toHaveBeenCalledOnce());expect(utterances[0]!.lang).toBe('en-SG');
 fireEvent.click(screen.getByRole('button',{name:'Stop audio'}));fireEvent.click(screen.getByRole('button',{name:'Play response'}));expect(synthesis.speak).toHaveBeenCalledTimes(2);
 vi.mocked(api.preferences).mockResolvedValue({...profile,preferred_language:'zh',speech_locale:'zh-CN',tts_autoplay:false});
 fireEvent.click(screen.getByText('Load speech preferences'));await screen.findByRole('button',{name:'播放回答'});expect(screen.queryByRole('button',{name:'停止语音'})).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'播放回答'}));expect(utterances[2]!.lang).toBe('zh-CN');expect(api.synthesize).not.toHaveBeenCalled();
});
it('cloud playback needs an explicit selection, failure preserves text, reload defaults to browser',async()=>{
 vi.mocked(api.speechCapabilities).mockResolvedValue({available:true,provider:'browser',cloud_tts_allowed:true,review_required:true,raw_audio_retained:false});
 vi.mocked(api.sendMessage).mockResolvedValue({message:'DEMO visible reply.',session_id:'demo',intent:'due_query',session_state:'idle',requires_confirmation:false,mode:'deterministic_degraded',tool_traces:[],pending_report:null});
 vi.mocked(api.synthesize).mockRejectedValue(new Error('SIMULATED cloud failure'));
 const view=render(<LanguageProvider><SettingsScreen section="language"/><AssistantScreen sessionId="demo" onSession={vi.fn()}/></LanguageProvider>);
 await waitFor(()=>expect((screen.getByRole('option',{name:'Cloud voice (usage charges may apply)'}) as HTMLOptionElement).disabled).toBe(false));
 expect((screen.getByLabelText('Speech playback') as HTMLSelectElement).value).toBe('browser');
 fireEvent.change(screen.getByLabelText('Review your message before sending'),{target:{value:'DEMO query'}});fireEvent.click(screen.getByRole('button',{name:'Send'}));await screen.findByText('DEMO visible reply.');expect(api.synthesize).not.toHaveBeenCalled();
 fireEvent.change(screen.getByLabelText('Speech playback'),{target:{value:'tencent'}});fireEvent.click(screen.getByRole('button',{name:'Play response'}));await screen.findByText(/Spoken playback is unavailable/);
 expect(api.synthesize).toHaveBeenCalledOnce();expect(screen.getByText('DEMO visible reply.')).toBeTruthy();
 view.unmount();render(<LanguageProvider><SettingsScreen section="language"/></LanguageProvider>);
 expect((screen.getByLabelText('Speech playback') as HTMLSelectElement).value).toBe('browser');
});
it('restores bounded recent chat under StrictMode without replaying an earlier confirmation',async()=>{
 vi.mocked(api.recentTurns).mockResolvedValue([{user:'DEMO what medicine tonight?',assistant:'DEMO reviewed schedule.'}]);
 render(<StrictMode><AssistantScreen sessionId="DEMO-session" onSession={vi.fn()}/></StrictMode>);
 await screen.findByText('DEMO what medicine tonight?');expect(screen.getByText('DEMO reviewed schedule.')).toBeTruthy();
 expect(screen.queryByRole('button',{name:'Confirm record'})).toBeNull();expect(api.submitReport).not.toHaveBeenCalled();
});
async function listen(speech: Speech) {
  const callback=vi.fn(); render(<VoiceInput provider={{create:()=>speech}} onTranscript={callback}/>);
  // One tap reaches the browser prompt; there is no in-app consent gate.
  fireEvent.click(screen.getByRole('button',{name:'Speak your message'})); return callback;
}
describe('native browser speech wiring (SIMULATED events)',()=>{
 it('loads one persisted Mandarin preference and configures zh-CN without auto submission',async()=>{
  const speech=new Speech(); const transcript=vi.fn();
  vi.mocked(api.updatePreferences).mockResolvedValue({preferred_language:'zh',speech_locale:'zh-CN'} as Awaited<ReturnType<typeof api.updatePreferences>>);
  vi.mocked(api.preferences).mockResolvedValue({preferred_language:'zh',speech_locale:'zh-CN'} as Awaited<ReturnType<typeof api.preferences>>);
  function Controls(){const {language,setLanguage,loadPreferences}=useLanguage();return <><button onClick={()=>setLanguage('zh')}>Choose Chinese</button><button onClick={()=>void loadPreferences()}>Load preference</button><output>{language}</output><VoiceInput key={language} provider={{create:()=>speech}} onTranscript={transcript}/></>;}
  const first=render(<LanguageProvider><Controls/></LanguageProvider>); fireEvent.click(screen.getByText('Choose Chinese'));
  await screen.findByText('zh'); expect(api.updatePreferences).toHaveBeenCalledWith({preferred_language:'zh'}); first.unmount();
  render(<LanguageProvider><Controls/></LanguageProvider>);fireEvent.click(screen.getByText('Load preference')); await screen.findByText('zh');
  fireEvent.click(screen.getByRole('button',{name:'语音输入'}));
  expect(speech.lang).toBe('zh-CN'); speech.result('今晚吃什么药？'); expect(transcript).toHaveBeenCalledWith('今晚吃什么药？');expect(api.sendMessage).not.toHaveBeenCalled();
 });
 it('detects unsupported browser and keeps typed fallback',()=>{ render(<AssistantScreen sessionId="demo" onSession={vi.fn()}/>); expect(screen.getByText(/unsupported/)).toBeTruthy(); expect(screen.getByLabelText('Review your message before sending')).toBeTruthy(); });
 it('one tap on the microphone starts recognition without a second in-app consent',()=>{
  const speech=new Speech(); const callback=vi.fn();
  render(<VoiceInput provider={{create:()=>speech}} onTranscript={callback}/>);
  fireEvent.click(screen.getByRole('button',{name:'Speak your message'}));
  // The browser prompt is the only authorisation: recognition starts immediately
  // and no checkbox dialog is interposed.
  expect(speech.start).toHaveBeenCalledOnce();
  expect(screen.queryByRole('checkbox')).toBeNull();
  expect(screen.getByRole('button',{name:'Stop listening'})).toBeTruthy();
 });
 it.each(['not-allowed','audio-capture','no-speech','network','aborted','service-not-allowed','unknown'])('handles recognition error %s without submitting',async code=>{ const speech=new Speech(); const callback=await listen(speech); speech.onerror?.({error:code}); await waitFor(()=>expect(screen.getByRole('button',{name:'Speak your message'})).toBeTruthy()); expect(callback).not.toHaveBeenCalled(); expect(api.sendMessage).not.toHaveBeenCalled(); });
 it('stop and cancel end listening without dispatching Agent',async()=>{ const speech=new Speech(); const callback=await listen(speech); fireEvent.click(screen.getByRole('button',{name:'Stop listening'})); expect(speech.stop).toHaveBeenCalledOnce(); expect(callback).not.toHaveBeenCalled(); });
 it('cancel aborts recognition',async()=>{ const speech=new Speech(); await listen(speech); fireEvent.click(screen.getByRole('button',{name:'Cancel'})); expect(speech.abort).toHaveBeenCalled(); });
 it('empty final result never becomes input',async()=>{ const speech=new Speech(); const callback=await listen(speech); speech.result(' '); await screen.findByText(/No usable words/); expect(callback).not.toHaveBeenCalled(); });
 it('times out stuck recognition',async()=>{ const speech=new Speech(); await listen(speech); vi.useFakeTimers(); // Timer starts before fake timers, so start a new attempt.
 fireEvent.click(screen.getByRole('button',{name:'Cancel'})); fireEvent.click(screen.getByRole('button',{name:'Speak your message'}));
 vi.advanceTimersByTime(30001); vi.useRealTimers(); await screen.findByText(/timed out/); expect(speech.abort).toHaveBeenCalled(); });
 it('transcript is editable, no auto-submit, and explicit Send uses Agent',async()=>{
  const speech=new Speech(); vi.stubGlobal('webkitSpeechRecognition',class { constructor(){return speech;} });
  vi.mocked(api.sendMessage).mockResolvedValue({message:'Please review your report.',session_id:'demo',intent:'dose_self_report',session_state:'awaiting_confirmation',requires_confirmation:true,mode:'deterministic_degraded',tool_traces:[],pending_report:{challenge_id:'challenge',occurrence_id:'occurrence',regimen_id:'regimen',idempotency_key:'turn',expires_at:'2099-10-14T10:00:00Z',summary:{medication_display_name:'DEMO Metformin',dose_amount:1,dose_unit:'tablet',regimen_version_no:1,occurrence_due_at:null,local_due_time:'20:00',local_timezone:'Asia/Singapore',intake_status:'reported_taken',intake_status_label:'You reported taking this dose',safety_notice:'This does not prove ingestion.',ingestion_proven:false,visual_status:'not_checked'}}});
  render(<AssistantScreen sessionId="demo" onSession={vi.fn()}/>);
  fireEvent.click(screen.getByRole('button',{name:'Speak your message'})); speech.result('I took it.');
  await waitFor(()=>expect((screen.getByLabelText('Review your message before sending') as HTMLInputElement).value).toBe('I took it.'));
  expect(api.sendMessage).not.toHaveBeenCalled(); fireEvent.change(screen.getByLabelText('Review your message before sending'),{target:{value:'I already took my evening medicine.'}}); fireEvent.click(screen.getByRole('button',{name:'Send'}));
  await screen.findByText('Just to confirm'); expect(api.submitReport).not.toHaveBeenCalled();
  vi.mocked(api.submitReport).mockResolvedValue({event_id:'event',intake_status:'reported_taken',visual_status:'not_checked',already_recorded:false,ingestion_proven:false,note:'demo_only'});
  fireEvent.click(screen.getByRole('button',{name:'Confirm record'})); await waitFor(()=>expect(api.submitReport).toHaveBeenCalledOnce());
 });
 it('TTS failure preserves the text response',async()=>{
  vi.mocked(api.sendMessage).mockResolvedValue({message:'No dose is due.',session_id:'demo',intent:'due_query',session_state:'idle',requires_confirmation:false,mode:'deterministic_degraded',tool_traces:[],pending_report:null});
  vi.mocked(api.synthesize).mockRejectedValue(new Error('SIMULATED TTS failure'));
  render(<AssistantScreen sessionId="demo" onSession={vi.fn()}/>); fireEvent.change(screen.getByLabelText('Review your message before sending'),{target:{value:'What is due now?'}}); fireEvent.click(screen.getByRole('button',{name:'Send'}));
  await screen.findByText('No dose is due.'); fireEvent.click(screen.getByRole('button',{name:'Play response'})); await screen.findByText(/Spoken playback is unavailable/); expect(screen.getByText('No dose is due.')).toBeTruthy();expect(api.synthesize).not.toHaveBeenCalled();
 });
});
