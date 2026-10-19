// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {api} from '../api/client';
import {LanguageProvider,useLanguage} from '../language';
import {PatientHub} from './PatientHub';
import type {AccountPort} from '../api/auth';

afterEach(()=>{cleanup();vi.restoreAllMocks();});
function LanguageToggle(){const {setLanguage}=useLanguage();return <button onClick={()=>setLanguage('zh')}>DEMO Chinese</button>;}
it('renders the approved three two-entry settings cards and full-width help links',async()=>{
 const auth:AccountPort={available:true,account:vi.fn().mockResolvedValue({kind:'member',email:'member@example.test',verified:true}),requestEmail:vi.fn(),verifyEmail:vi.fn(),passwordLogin:vi.fn(),setPassword:vi.fn(),signOut:vi.fn()};
 render(<LanguageProvider><PatientHub auth={auth} onOpen={vi.fn()} onGuide={vi.fn()}/></LanguageProvider>);
 await screen.findByText(/member@example\.test/);
 for(const title of ['Care and reminders','Personalisation','Privacy & Data']){
  const group=screen.getByRole('heading',{name:title}).closest('.entry-group');expect(group).toBeTruthy();expect(within(group as HTMLElement).getAllByRole('button')).toHaveLength(2);
 }
 const help=screen.getByRole('heading',{name:'Help & application information'}).closest('.entry-group');expect(within(help as HTMLElement).getAllByRole('button')).toHaveLength(3);
});
it('localises the settings groups and guest identity in Chinese',async()=>{
 vi.spyOn(api,'updatePreferences').mockResolvedValue({patient_id:'DEMO-owner',preferred_language:'zh',speech_locale:'zh-CN',text_size:'standard',voice_enabled:true,tts_autoplay:false,reminder_lead_minutes:0,timezone:'Asia/Singapore',created_at:'2026-10-20T00:00:00Z',updated_at:'2026-10-20T00:00:00Z'});
 const auth:AccountPort={available:true,account:vi.fn().mockResolvedValue({kind:'guest',email:null,verified:false}),requestEmail:vi.fn(),verifyEmail:vi.fn(),passwordLogin:vi.fn(),setPassword:vi.fn(),signOut:vi.fn()};
 render(<LanguageProvider><LanguageToggle/><PatientHub auth={auth} onOpen={vi.fn()}/></LanguageProvider>);
 await screen.findAllByText('Guest Mode');fireEvent.click(screen.getByRole('button',{name:'DEMO Chinese'}));
 await waitFor(()=>expect(screen.getByRole('heading',{name:'照护与提醒'})).toBeTruthy());
 expect(screen.getByRole('heading',{name:'个性化'})).toBeTruthy();expect(screen.getByRole('heading',{name:'隐私与数据'})).toBeTruthy();
});
it('does not present an unconfigured local demo session as a guest account',async()=>{
 const auth:AccountPort={available:false,account:vi.fn().mockResolvedValue({kind:'local',email:null,verified:false}),requestEmail:vi.fn(),verifyEmail:vi.fn(),passwordLogin:vi.fn(),setPassword:vi.fn(),signOut:vi.fn()};
 render(<LanguageProvider><PatientHub auth={auth} onOpen={vi.fn()}/></LanguageProvider>);
 await screen.findByText('Local demo');expect(screen.queryByRole('button',{name:'Manage guest account'})).toBeNull();
});
