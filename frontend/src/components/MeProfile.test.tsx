// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {api} from '../api/client';
import {LanguageProvider} from '../language';
import {ProfileScreen} from './PatientHub';
import {MeScreen} from './MeScreen';
import type {AccountPort} from '../api/auth';

afterEach(()=>{cleanup();vi.restoreAllMocks();});
const prefs={patient_id:'00000000-0000-0000-0000-000000000101',preferred_language:'en',speech_locale:'en-SG',text_size:'standard',text_scale_percent:100,voice_enabled:true,tts_autoplay:false,reminder_lead_minutes:0,timezone:'Asia/Singapore',created_at:'2026-10-20T00:00:00Z',updated_at:'2026-10-20T00:00:00Z'} as const;

it('saves only a valid changed profile name and keeps entered text when persistence fails',async()=>{
 const saved=vi.spyOn(api,'updatePreferences').mockResolvedValue({...prefs,display_name:'DEMO Name'});
 render(<LanguageProvider><ProfileScreen/></LanguageProvider>);
 const input=screen.getByLabelText('Display name');expect((screen.getByRole('button',{name:'Save profile'}) as HTMLButtonElement).disabled).toBe(true);
 fireEvent.change(input,{target:{value:'DEMO Name'}});fireEvent.click(screen.getByRole('button',{name:'Save profile'}));await screen.findByText('Profile saved.');
 expect(saved).toHaveBeenCalledExactlyOnceWith({display_name:'DEMO Name'});
 cleanup();saved.mockRejectedValueOnce(new Error('SIMULATED offline'));
 render(<LanguageProvider><ProfileScreen/></LanguageProvider>);fireEvent.change(screen.getByLabelText('Display name'),{target:{value:'DEMO Retry'}});fireEvent.click(screen.getByRole('button',{name:'Save profile'}));
 await screen.findByRole('alert');expect((screen.getByLabelText('Display name') as HTMLInputElement).value).toBe('DEMO Retry');
});

it('keeps guest email linking and existing-account sign-in as separate explicit operations',async()=>{
 const auth:AccountPort={available:true,account:vi.fn().mockResolvedValue({kind:'guest',email:null,verified:false}),requestEmail:vi.fn().mockResolvedValue(undefined),verifyEmail:vi.fn().mockResolvedValue(undefined),passwordLogin:vi.fn().mockResolvedValue(undefined),setPassword:vi.fn().mockResolvedValue(undefined),signOut:vi.fn().mockResolvedValue(undefined)};
 render(<LanguageProvider><MeScreen auth={auth} onIdentityChanged={vi.fn()}/></LanguageProvider>);
 await screen.findByText(/Guest records are associated/);
 fireEvent.click(screen.getByRole('button',{name:'Link email and keep my records'}));
 fireEvent.change(screen.getByLabelText('Email'),{target:{value:'guest@example.test'}});fireEvent.click(screen.getByRole('button',{name:'Email code / Magic Link'}));
 await waitFor(()=>expect(auth.requestEmail).toHaveBeenCalledWith('guest@example.test','link'));
 fireEvent.click(screen.getByRole('button',{name:'Back to guest options'}));
 fireEvent.click(screen.getByRole('button',{name:'Sign in to an existing account'}));expect(screen.getByLabelText(/Signing in switches accounts/)).toBeTruthy();
 expect(auth.requestEmail).toHaveBeenCalledTimes(1);
});
it('does not offer account linking for a local demo identity',async()=>{
 const auth:AccountPort={available:false,account:vi.fn().mockResolvedValue({kind:'local',email:null,verified:false}),requestEmail:vi.fn(),verifyEmail:vi.fn(),passwordLogin:vi.fn(),setPassword:vi.fn(),signOut:vi.fn()};
 render(<LanguageProvider><MeScreen auth={auth} onIdentityChanged={vi.fn()}/></LanguageProvider>);
 await screen.findByText(/unavailable in this local demo/);expect(screen.queryByRole('button',{name:'Link email and keep my records'})).toBeNull();expect(screen.queryByText(/Guest records are associated/)).toBeNull();
});
