// @vitest-environment jsdom
import {afterEach,beforeEach,it,expect,vi} from 'vitest';
import {act,cleanup,render,screen,waitFor} from '@testing-library/react';
import {App} from './App';
import {api} from './api/client';
import {accountAuth} from './api/auth';
vi.mock('./api/client',()=>({ApiError:class extends Error{},api:{evidenceTasks:vi.fn(),refreshFollowUps:vi.fn(),doseFollowUps:vi.fn(),health:vi.fn(),startDemo:vi.fn(),preferences:vi.fn().mockResolvedValue({preferred_language:'en'}),listMedications:vi.fn(),regimenHistory:vi.fn()}}));
afterEach(()=>{cleanup();localStorage.clear();vi.restoreAllMocks();vi.resetAllMocks();});
beforeEach(()=>vi.mocked(api.evidenceTasks).mockResolvedValue([]));
it('loads essential records alongside session setup and does not wait for session or evidence tasks',async()=>{
 vi.mocked(api.health).mockResolvedValue({status:'ok',service:'pharmascan-care-agent',database:'supabase',llm:'unavailable_deterministic_degraded',stage2_vision:'live',runtime_contract:'patient-ux-reminders-v1'});
 vi.mocked(api.preferences).mockResolvedValue({patient_id:'demo-patient',preferred_language:'en',speech_locale:'en-SG',text_size:'standard',voice_enabled:true,tts_autoplay:false,reminder_lead_minutes:0,timezone:'Asia/Singapore',created_at:'2026-10-14T00:00:00Z',updated_at:'2026-10-14T00:00:00Z'});
 let rejectSession!:(reason:Error)=>void;
 vi.mocked(api.startDemo).mockReturnValue(new Promise((_resolve,reject)=>{rejectSession=reject;}));
 vi.mocked(api.evidenceTasks).mockReturnValue(new Promise(()=>{}));
 vi.mocked(api.listMedications).mockResolvedValue({item_count:0,medications:[],note:'demo_only'});
 vi.mocked(api.regimenHistory).mockResolvedValue([]);vi.mocked(api.refreshFollowUps).mockResolvedValue([]);
 render(<App/>);await screen.findByText('Your medication and self-care companion');
 expect(api.listMedications).toHaveBeenCalledOnce();expect(api.preferences).toHaveBeenCalledOnce();
 expect(api.startDemo).toHaveBeenCalledOnce();expect(api.evidenceTasks).toHaveBeenCalledOnce();
 expect(screen.queryByText('Your records could not be loaded')).toBeNull();
 await act(async()=>{rejectSession(new Error('DEMO session unavailable'));});
 expect(screen.getByText('Your medication and self-care companion')).toBeTruthy();
 expect(screen.queryByText('Your records could not be loaded')).toBeNull();
});
it('refuses stale backend before any authenticated setup or business query',async()=>{
 vi.mocked(api.health).mockResolvedValue({status:'ok',service:'pharmascan-care-agent',database:'supabase',llm:'unavailable_deterministic_degraded',stage2_vision:'simulated'});
 render(<App/>);await screen.findByText(/app connection needs a restart/);
 expect(api.startDemo).not.toHaveBeenCalled();expect(api.listMedications).not.toHaveBeenCalled();expect(screen.queryByText(/No dose due right now/)).toBeNull();
});
it('failed medication read is shown as unavailable instead of zero active medicines',async()=>{
 vi.mocked(api.health).mockResolvedValue({status:'ok',service:'pharmascan-care-agent',database:'supabase',llm:'unavailable_deterministic_degraded',stage2_vision:'live',runtime_contract:'patient-ux-reminders-v1'});
 vi.mocked(api.preferences).mockResolvedValue({patient_id:'demo-patient',preferred_language:'en',speech_locale:'en-SG',text_size:'standard',voice_enabled:true,tts_autoplay:false,reminder_lead_minutes:0,timezone:'Asia/Singapore',created_at:'2026-10-14T00:00:00Z',updated_at:'2026-10-14T00:00:00Z'});
 vi.mocked(api.startDemo).mockResolvedValue({patient_id:'demo-patient',session_id:'demo-session',demo_only:true,seeded_medication_count:0,note:'demo_only'});
 vi.mocked(api.listMedications).mockRejectedValue(new Error('Records unavailable'));vi.mocked(api.regimenHistory).mockResolvedValue([]);
 render(<App/>);await waitFor(()=>expect(screen.getByText(/unavailable record is not an empty medication list/)).toBeTruthy());expect(screen.queryByRole('button',{name:'Compare a pill photo'})).toBeNull();
});

it('unavailable greeting account metadata does not block authenticated business records',async()=>{
 vi.mocked(api.refreshFollowUps).mockResolvedValue([]);
 vi.spyOn(accountAuth,'account').mockRejectedValue(new Error('DEMO account metadata unavailable'));
 vi.mocked(api.health).mockResolvedValue({status:'ok',service:'pharmascan-care-agent',database:'supabase',llm:'unavailable_deterministic_degraded',stage2_vision:'live',runtime_contract:'patient-ux-reminders-v1'});
 vi.mocked(api.preferences).mockResolvedValue({patient_id:'demo-patient',preferred_language:'en',speech_locale:'en-SG',text_size:'standard',voice_enabled:true,tts_autoplay:false,reminder_lead_minutes:0,timezone:'Asia/Singapore',created_at:'2026-10-14T00:00:00Z',updated_at:'2026-10-14T00:00:00Z'});
 vi.mocked(api.startDemo).mockResolvedValue({patient_id:'demo-patient',session_id:'demo-session',demo_only:true,seeded_medication_count:0,note:'demo_only'});
 vi.mocked(api.listMedications).mockResolvedValue({item_count:0,medications:[],note:'demo_only'});vi.mocked(api.regimenHistory).mockResolvedValue([]);
 localStorage.setItem('pharmascan.quick-start.v4:demo-patient',JSON.stringify({version:4,status:'skipped',step:0}));
 render(<App/>);await screen.findByText('Your medication and self-care companion');
 expect(screen.getByText(/Guest!/)).toBeTruthy();expect(screen.queryByText('Your records could not be loaded')).toBeNull();
});
