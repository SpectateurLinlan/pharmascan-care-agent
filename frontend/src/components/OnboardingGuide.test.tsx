// @vitest-environment jsdom
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen} from '@testing-library/react';
import {OnboardingGuide, guideWasDismissed, rememberGuideDismissal} from './OnboardingGuide';
import {HeaderAccountButton} from './HeaderAccountButton';
import {LanguageProvider, useLanguage} from '../language';
import {api, type PatientPreferences} from '../api/client';
import {accountAuth} from '../api/auth';

vi.mock('../api/client',()=>({api:{preferences:vi.fn(),updatePreferences:vi.fn()}}));
beforeEach(()=>{
  vi.stubGlobal('ResizeObserver',class {observe(){} disconnect(){}});
});
afterEach(()=>{cleanup();localStorage.clear();vi.restoreAllMocks();vi.unstubAllGlobals();});

it('remembers dismissal locally and safely handles unavailable browser storage',()=>{
  expect(guideWasDismissed()).toBe(false);
  expect(rememberGuideDismissal()).toBe(true);
  expect(guideWasDismissed()).toBe(true);
  vi.spyOn(Storage.prototype,'getItem').mockImplementation(()=>{throw new Error('Unavailable');});
  vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw new Error('Unavailable');});
  expect(guideWasDismissed()).toBe(false);expect(rememberGuideDismissal()).toBe(false);
});

it('explains explicit Send, actual defaults and confirmation without enabling speech or changing preferences',()=>{
  const close=vi.fn(),settings=vi.fn();
  render(<OnboardingGuide onClose={close} onSettings={settings}/>);
  for(let i=0;i<3;i++)fireEvent.click(screen.getByRole('button',{name:'Next'}));
  expect(screen.getByText(/Send is on the right/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Next'}));
  expect(screen.getByText(/confirm the separate summary/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Next'}));
  expect(screen.getByText(/Automatic reading is off by default/)).toBeTruthy();
  expect(screen.getByText(/Voice On.*Read replies automatically Off/)).toBeTruthy();
  expect(api.updatePreferences).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'Open language and speech settings'}));
  expect(settings).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole('button',{name:'Next'}));
  fireEvent.click(screen.getByRole('button',{name:'Got it'}));expect(close).toHaveBeenCalledOnce();
});

it('supports previous, skipping, Escape and keyboard focus trapping',()=>{
  const close=vi.fn();render(<OnboardingGuide onClose={close} onSettings={vi.fn()}/>);
  const dialog=screen.getByRole('dialog',{name:'Quick start guide'});
  expect(document.activeElement).toBe(dialog);
  fireEvent.keyDown(dialog,{key:'Tab'});expect(document.activeElement).toBe(screen.getByRole('button',{name:'Skip for now'}));
  fireEvent.click(screen.getByRole('button',{name:'Next'}));
  fireEvent.click(screen.getByRole('button',{name:'Previous'}));expect(screen.getByText('1 / 7')).toBeTruthy();
  fireEvent.keyDown(dialog,{key:'Escape'});expect(close).toHaveBeenCalledOnce();
});

it('uses persisted Chinese preference and shows actual autoplay state rather than the default',async()=>{
  const preference:PatientPreferences={patient_id:'DEMO-owner',preferred_language:'zh',speech_locale:'zh-CN',text_size:'large',voice_enabled:true,tts_autoplay:true,reminder_lead_minutes:0,timezone:'Asia/Singapore',created_at:'2026-10-15T00:00:00Z',updated_at:'2026-10-15T00:00:00Z'};
  vi.mocked(api.preferences).mockResolvedValue(preference);
  function Loaded(){const {loadPreferences}=useLanguage();return <><button onClick={()=>void loadPreferences()}>Load</button><OnboardingGuide onClose={vi.fn()} onSettings={vi.fn()}/></>;}
  render(<LanguageProvider><Loaded/></LanguageProvider>);fireEvent.click(screen.getByRole('button',{name:'Load'}));
  await screen.findByRole('dialog',{name:'新手指南'});
  for(let i=0;i<5;i++)fireEvent.click(screen.getByRole('button',{name:'下一步'}));
  expect(screen.getByText(/自动朗读回答 开启/)).toBeTruthy();
  expect(screen.getByText(/当前设置: 语音 开启/)).toBeTruthy();
  expect(screen.getByRole('button',{name:'打开语言与语音设置'})).toBeTruthy();
});

it('header status derives from Auth and routes through Me, without displaying email',async()=>{
  const open=vi.fn();const account=vi.fn().mockResolvedValue({kind:'guest',email:null,verified:false});
  const auth={...accountAuth,account};
  const {rerender}=render(<HeaderAccountButton ready={false} onOpen={open} auth={auth}/>);
  expect(account).not.toHaveBeenCalled();
  rerender(<HeaderAccountButton ready onOpen={open} auth={auth}/>);
  fireEvent.click(await screen.findByRole('button',{name:'Me: Guest demo'}));expect(open).toHaveBeenCalledOnce();
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
