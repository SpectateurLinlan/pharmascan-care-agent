// @vitest-environment jsdom
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {useState} from 'react';
import {act, cleanup, fireEvent, render, screen} from '@testing-library/react';
import {OnboardingGuide} from './OnboardingGuide';
import {readTour,saveTour} from '../onboarding';
import {HeaderAccountButton} from './HeaderAccountButton';
import {LanguageProvider, useLanguage} from '../language';
import {api, type PatientPreferences} from '../api/client';
import {accountAuth} from '../api/auth';

vi.mock('../api/client',()=>({api:{preferences:vi.fn(),updatePreferences:vi.fn()}}));
beforeEach(()=>{
  vi.stubGlobal('ResizeObserver',class {observe(){} disconnect(){}});
  vi.stubGlobal('MutationObserver',class {observe(){} disconnect(){} takeRecords(){return []}});
});
afterEach(()=>{cleanup();localStorage.clear();vi.restoreAllMocks();vi.unstubAllGlobals();});

function GuideHarness({owner='A',replay=false,guest=false,originRoute='today',onClose=vi.fn()}:{owner?:string;replay?:boolean;guest?:boolean;originRoute?:string;onClose?: (restore:boolean)=>void}){
 const [route,setRoute]=useState('today');
 return <><main><div id="today-medication"><h2 className="today-attention__heading">Today</h2></div><div data-guide="medication-add"><h2>Add</h2></div><div data-guide="medication-records" className="records-summary--highlight"><div className="card__title">Records</div></div><div data-guide="assistant-conversation" className="conversation-toolbar">Assistant</div><div data-guide="assistant-composer">Composer</div><div data-guide="me-settings"><div className="card__title">Settings</div></div></main><output data-testid="guide-route">{route}</output><OnboardingGuide owner={owner} replay={replay} guest={guest} activeRoute={route} originRoute={originRoute} onNavigate={setRoute} onRestore={()=>setRoute(originRoute)} onClose={onClose}/></>;
}

it('migrates v4 progress to the six-step guide and preserves dismissed states per owner',()=>{
 expect(readTour('A').status).toBe('in_progress');
 localStorage.setItem('pharmascan.quick-start.v4:A',JSON.stringify({version:4,status:'in_progress',step:7}));
 expect(readTour('A')).toEqual({version:5,status:'in_progress',step:0});
 localStorage.removeItem('pharmascan.quick-start.v5:A');
 localStorage.setItem('pharmascan.quick-start.v4:A',JSON.stringify({version:4,status:'completed',step:7}));
 expect(readTour('A')).toEqual({version:5,status:'completed',step:0});
 saveTour('A',{version:5,status:'skipped',step:3});expect(readTour('A').status).toBe('skipped');expect(readTour('B').step).toBe(0);
 vi.spyOn(Storage.prototype,'getItem').mockImplementation(()=>{throw new Error('Unavailable');});
 expect(readTour('A').status).toBe('in_progress');
});

it('guides through the six real destinations and restores the origin before completion',()=>{
 const close=vi.fn();vi.spyOn(HTMLElement.prototype,'getBoundingClientRect').mockReturnValue({x:10,y:20,left:10,top:20,right:210,bottom:120,width:200,height:100,toJSON:()=>({})} as DOMRect);
 render(<GuideHarness onClose={close}/>);
 expect(screen.getByRole('dialog',{name:'Getting Started'})).toBeTruthy();
 expect(screen.getByRole('heading',{name:"Check Today's Schedule"})).toBeTruthy();
 expect(screen.getByRole('heading',{name:"Today's Medications"})).toBeTruthy();
 expect(screen.getByRole('heading',{name:'Care Tasks'})).toBeTruthy();
 const next=()=>fireEvent.click(screen.getByRole('button',{name:'Next'}));
 const expected=[['Add and Manage Medications','medicines'],['Review Medication and Health Records','records'],['Ask the AI Assistant','assistant'],['Use Text, Photos, or Voice','assistant'],['Manage Your Account and Settings','me']] as const;
 for(let i=0;i<expected.length;i++){const pair=expected[i]!;next();expect(screen.getByRole('heading',{name:pair[0]})).toBeTruthy();expect(screen.getByTestId('guide-route').textContent).toBe(pair[1]);expect(screen.getByText(new RegExp(`^${i+2} / 6`))).toBeTruthy();}
 fireEvent.click(screen.getByRole('button',{name:'Finish'}));
 expect(screen.getByRole('dialog',{name:"You're All Set!"})).toBeTruthy();expect(screen.getByRole('heading',{name:"You're All Set!",level:3})).toBeTruthy();expect(screen.getByTestId('guide-route').textContent).toBe('today');
 fireEvent.click(screen.getByRole('button',{name:'Start Using MediThread'}));expect(close).toHaveBeenCalledWith(false);
});

it('localizes the new guide using the saved Chinese preference',async()=>{
 const preference:PatientPreferences={patient_id:'DEMO-owner',preferred_language:'zh',speech_locale:'zh-CN',text_size:'large',voice_enabled:true,tts_autoplay:true,reminder_lead_minutes:0,timezone:'Asia/Singapore',created_at:'2026-10-15T00:00:00Z',updated_at:'2026-10-15T00:00:00Z'};
 vi.mocked(api.preferences).mockResolvedValue(preference);
 function Loaded(){const {loadPreferences}=useLanguage();return <><button onClick={()=>void loadPreferences()}>Load</button><GuideHarness/></>;}
 render(<LanguageProvider><Loaded/></LanguageProvider>);fireEvent.click(screen.getByRole('button',{name:'Load'}));
 await screen.findByRole('dialog',{name:'\u65b0\u624b\u6307\u5f15'});
 expect(screen.getByRole('heading',{name:'\u67e5\u770b\u4eca\u65e5\u5b89\u6392'})).toBeTruthy();
 expect(screen.getByText('\u5728\u8fd9\u91cc\u67e5\u770b\u4eca\u5929\u7684\u8ba1\u5212\u5242\u6b21\uff0c\u5e76\u6839\u636e\u5b9e\u9645\u60c5\u51b5\u8bb0\u5f55\u662f\u5426\u670d\u836f\u3002')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'\u4e0b\u4e00\u6b65'}));
 expect(screen.getByRole('heading',{name:'\u6dfb\u52a0\u4e0e\u7ba1\u7406\u836f\u7269'})).toBeTruthy();
});

it('localizes the guest account step without implying a personal profile page',async()=>{
 const preference:PatientPreferences={patient_id:'DEMO-owner',preferred_language:'zh',speech_locale:'zh-CN',text_size:'standard',voice_enabled:true,tts_autoplay:false,reminder_lead_minutes:0,timezone:'Asia/Singapore',created_at:'2026-10-15T00:00:00Z',updated_at:'2026-10-15T00:00:00Z'};
 vi.mocked(api.preferences).mockResolvedValue(preference);
 function Loaded(){const {loadPreferences}=useLanguage();return <><button onClick={()=>void loadPreferences()}>Load</button><GuideHarness guest/></>;}
 render(<LanguageProvider><Loaded/></LanguageProvider>);fireEvent.click(screen.getByRole('button',{name:'Load'}));
 await screen.findByRole('dialog',{name:'\u65b0\u624b\u6307\u5f15'});
 for(let step=0;step<5;step++)fireEvent.click(screen.getByRole('button',{name:'\u4e0b\u4e00\u6b65'}));
 expect(screen.getByText('\u5728\u300c\u6211\u300d\u4e2d\u7ba1\u7406\u8d26\u6237\u8bbf\u95ee\u65b9\u5f0f\u548c\u7167\u62a4\u8054\u7cfb\u4eba\u3002')).toBeTruthy();
 expect(screen.getByText('\u8bbf\u5ba2\u6a21\u5f0f\u4e0b\uff0c\u60a8\u53ef\u4ee5\u7ed1\u5b9a\u90ae\u7bb1\u4ee5\u4fdd\u7559\u5f53\u524d\u8bb0\u5f55\u7684\u8bbf\u95ee\u6743\u9650\uff0c\u4e5f\u53ef\u4ee5\u767b\u5f55\u5df2\u6709\u8d26\u6237\u3002\u4e24\u79cd\u8d26\u6237\u4e0d\u4f1a\u5408\u5e76\u3002')).toBeTruthy();
 expect(screen.queryByText(/\u4e2a\u4eba\u8d44\u6599/)).toBeNull();
});

it('speaks the localized step and can stop browser speech',()=>{
 const events=new EventTarget(),utterances:SpeechSynthesisUtterance[]=[];
 const synthesis={cancel:vi.fn(),getVoices:()=>[{lang:'en-SG',localService:true}],speak:vi.fn((utterance:SpeechSynthesisUtterance)=>utterances.push(utterance)),addEventListener:events.addEventListener.bind(events),removeEventListener:events.removeEventListener.bind(events)};
 vi.stubGlobal('speechSynthesis',synthesis);
 vi.stubGlobal('SpeechSynthesisUtterance',class {onend=null;onerror=null;voice?:SpeechSynthesisVoice;lang='';rate=1;constructor(public text:string){}});
 render(<GuideHarness/>);
 fireEvent.click(screen.getByRole('button',{name:'Read Aloud'}));
 expect(synthesis.speak).toHaveBeenCalledOnce();expect(utterances[0]!.text).toContain("Check Today's Schedule");expect(utterances[0]!.lang).toBe('en-SG');
 expect(screen.getByRole('button',{name:'Stop Reading'}).getAttribute('aria-pressed')).toBe('true');
 act(()=>utterances[0]!.onend?.call(utterances[0]!,{} as SpeechSynthesisEvent));
 expect(screen.getByRole('button',{name:'Stop Reading'}).getAttribute('aria-pressed')).toBe('true');
 fireEvent.click(screen.getByRole('button',{name:'Next'}));
 expect(synthesis.speak).toHaveBeenCalledTimes(2);expect(utterances[1]!.text).toContain('Add and Manage Medications');
 expect(screen.getByRole('button',{name:'Stop Reading'}).getAttribute('aria-pressed')).toBe('true');
 fireEvent.click(screen.getByRole('button',{name:'Back'}));expect(synthesis.speak).toHaveBeenCalledTimes(3);

 fireEvent.click(screen.getByRole('button',{name:'Stop Reading'}));expect(synthesis.cancel).toHaveBeenCalled();expect(screen.getByRole('button',{name:'Read Aloud'}).getAttribute('aria-pressed')).toBe('false');
 fireEvent.click(screen.getByRole('button',{name:'Next'}));expect(synthesis.speak).toHaveBeenCalledTimes(3);
 fireEvent.click(screen.getByRole('button',{name:'Read Aloud'}));expect(synthesis.speak).toHaveBeenCalledTimes(4);
 for(let step=1;step<5;step++)fireEvent.click(screen.getByRole('button',{name:'Next'}));
 expect(screen.getByRole('button',{name:'Stop Reading'}).getAttribute('aria-pressed')).toBe('true');
 const beforeFinish=synthesis.speak.mock.calls.length;
 fireEvent.click(screen.getByRole('button',{name:'Finish'}));
 expect(screen.queryByRole('button',{name:'Stop Reading'})).toBeNull();expect(synthesis.speak).toHaveBeenCalledTimes(beforeFinish);

});

it('supports back, skip, Escape, focus trapping and guest-only account help',()=>{
 const close=vi.fn();const rect=vi.spyOn(HTMLElement.prototype,'getBoundingClientRect').mockReturnValue({x:700,y:12,left:700,top:12,right:880,bottom:60,width:180,height:48,toJSON:()=>({})} as DOMRect);
 render(<GuideHarness guest onClose={close}/>);
 const dialog=screen.getByRole('dialog',{name:'Getting Started'});expect(document.activeElement).toBe(dialog);
 fireEvent.keyDown(dialog,{key:'Tab'});expect(document.activeElement).toBe(screen.getByRole('button',{name:'Close Guide'}));
 fireEvent.click(screen.getByRole('button',{name:'Next'}));fireEvent.click(screen.getByRole('button',{name:'Back'}));expect(screen.getByText(/^1 \/ 6/)).toBeTruthy();
 for(let step=0;step<5;step++)fireEvent.click(screen.getByRole('button',{name:'Next'}));
 expect(screen.getByText('Use Me to manage account access and care contacts.')).toBeTruthy();
 expect(screen.getByText('In Guest Mode, you can link an email to keep access to current records or sign in to an existing account. Accounts are not merged.')).toBeTruthy();
 expect(screen.queryByText(/manage your profile/)).toBeNull();
 fireEvent.keyDown(dialog,{key:'Escape'});expect(close).toHaveBeenCalledWith(true);expect(readTour('A').status).toBe('skipped');
 cleanup();localStorage.clear();rect.mockRestore();render(<GuideHarness guest={false}/>);for(let step=0;step<5;step++)fireEvent.click(screen.getByRole('button',{name:'Next'}));expect(screen.getByText('Use Me to manage your profile, sign-in options, and care contacts.')).toBeTruthy();expect(screen.queryByText(/keep access to current records/)).toBeNull();
});

it('restores saved progress and replay leaves a completed state unchanged',()=>{
 const close=vi.fn();const view=render(<GuideHarness onClose={close}/>);
 fireEvent.click(screen.getByRole('button',{name:'Next'}));view.unmount();
 expect(readTour('A').step).toBe(1);
 render(<GuideHarness onClose={close}/>);expect(screen.getByText(/^2 \/ 6/)).toBeTruthy();cleanup();
 saveTour('A',{version:5,status:'completed',step:5});render(<GuideHarness replay onClose={close}/>);
 fireEvent.click(screen.getByRole('button',{name:'Skip Guide'}));expect(readTour('A').status).toBe('completed');
});

it('header status derives from Auth and routes through Me, without displaying email',async()=>{
  const open=vi.fn();const account=vi.fn().mockResolvedValue({kind:'guest',email:null,verified:false});
  const auth={...accountAuth,account};
  const {rerender}=render(<HeaderAccountButton ready={false} onOpen={open} auth={auth}/>);
  expect(account).not.toHaveBeenCalled();
  rerender(<HeaderAccountButton ready onOpen={open} auth={auth}/>);
  fireEvent.click(await screen.findByRole('button',{name:'Me: Guest'}));expect(open).toHaveBeenCalledOnce();
  account.mockResolvedValue({kind:'member',email:'demo@example.test',verified:true});
  rerender(<HeaderAccountButton ready onOpen={open} auth={{...auth}}/>);
  await screen.findByRole('button',{name:'Me: Your account'});
  expect(screen.queryByText('demo@example.test')).toBeNull();
});

it('failed account read stays unknown rather than claiming a login',async()=>{
  const account=vi.fn().mockRejectedValue(new Error('Unavailable'));
  render(<HeaderAccountButton ready onOpen={vi.fn()} auth={{...accountAuth,account}}/>);
  await screen.findByRole('button',{name:'Me: Account and login'});
  expect(screen.queryByText('Guest')).toBeNull();
});
