// @vitest-environment jsdom
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen} from '@testing-library/react';
import {OnboardingGuide} from './OnboardingGuide';
import {readTour,saveTour} from '../onboarding';
import {HeaderAccountButton} from './HeaderAccountButton';
import {LanguageProvider, useLanguage} from '../language';
import {api, type PatientPreferences} from '../api/client';
import {accountAuth} from '../api/auth';

vi.mock('../api/client',()=>({api:{preferences:vi.fn(),updatePreferences:vi.fn()}}));
beforeEach(()=>{
  vi.stubGlobal('ResizeObserver',class {observe(){} disconnect(){}});
});
afterEach(()=>{cleanup();localStorage.clear();vi.restoreAllMocks();vi.unstubAllGlobals();});

it('isolates owners and restores only valid bounded progress',()=>{
 expect(readTour('A').status).toBe('in_progress');
 saveTour('A',{version:2,status:'skipped',step:3});expect(readTour('A').status).toBe('skipped');expect(readTour('B').step).toBe(0);
 vi.spyOn(Storage.prototype,'getItem').mockImplementation(()=>{throw new Error('Unavailable');});
 expect(readTour('A').status).toBe('in_progress');
});

it('explains explicit Send, actual defaults and confirmation without enabling speech or changing preferences',()=>{
  const close=vi.fn();
  render(<OnboardingGuide owner="A" onClose={close}/>);
  for(let i=0;i<3;i++)fireEvent.click(screen.getByRole('button',{name:'Next'}));
  expect(screen.getByText(/Send is on the right/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Next'}));
  expect(screen.getByText(/confirm the separate summary/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Next'}));
  expect(screen.getByText(/Automatic reading is off by default/)).toBeTruthy();
  expect(screen.getByText(/Voice On.*Read replies automatically Off/)).toBeTruthy();
  expect(api.updatePreferences).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'Next'}));
  fireEvent.click(screen.getByRole('button',{name:'Finish'}));expect(close).toHaveBeenCalledOnce();
});

it('supports previous, skipping, Escape and keyboard focus trapping',()=>{
  const close=vi.fn();render(<OnboardingGuide owner="A" onClose={close}/>);
  const dialog=screen.getByRole('dialog',{name:'Quick start guide'});
  expect(document.activeElement).toBe(dialog);
  fireEvent.keyDown(dialog,{key:'Tab'});expect(document.activeElement).toBe(screen.getByRole('button',{name:'Skip for now'}));
  fireEvent.click(screen.getByRole('button',{name:'Next'}));
  fireEvent.click(screen.getByRole('button',{name:'Previous'}));expect(screen.getByText('1 / 7')).toBeTruthy();
  fireEvent.keyDown(dialog,{key:'Escape'});expect(close).not.toHaveBeenCalled();
  fireEvent.click(dialog.parentElement!);expect(close).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'Skip for now'}));expect(readTour('A').status).toBe('skipped');
});

it('uses persisted Chinese preference and shows actual autoplay state rather than the default',async()=>{
  const preference:PatientPreferences={patient_id:'DEMO-owner',preferred_language:'zh',speech_locale:'zh-CN',text_size:'large',voice_enabled:true,tts_autoplay:true,reminder_lead_minutes:0,timezone:'Asia/Singapore',created_at:'2026-10-15T00:00:00Z',updated_at:'2026-10-15T00:00:00Z'};
  vi.mocked(api.preferences).mockResolvedValue(preference);
  function Loaded(){const {loadPreferences}=useLanguage();return <><button onClick={()=>void loadPreferences()}>Load</button><OnboardingGuide owner="A" onClose={vi.fn()}/></>;}
  render(<LanguageProvider><Loaded/></LanguageProvider>);fireEvent.click(screen.getByRole('button',{name:'Load'}));
  await screen.findByRole('dialog',{name:'新手指南'});
  for(let i=0;i<5;i++)fireEvent.click(screen.getByRole('button',{name:'下一步'}));
  expect(screen.getByText(/自动朗读回答 开启/)).toBeTruthy();
  expect(screen.getByText(/当前设置: 语音 开启/)).toBeTruthy();
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

it('restores incomplete progress and replay does not overwrite completion',()=>{
 const close=vi.fn();const view=render(<OnboardingGuide owner="A" onClose={close}/>);
 fireEvent.click(screen.getByRole('button',{name:'Next'}));view.unmount();
 expect(readTour('A').step).toBe(1);
 const restored=render(<OnboardingGuide owner="A" onClose={close}/>);expect(screen.getByText('2 / 7')).toBeTruthy();restored.unmount();
 saveTour('A',{version:2,status:'completed',step:6});render(<OnboardingGuide owner="A" replay onClose={close}/>);
 fireEvent.click(screen.getByRole('button',{name:'Skip for now'}));expect(readTour('A').status).toBe('completed');
});
