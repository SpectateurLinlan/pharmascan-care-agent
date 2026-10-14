// @vitest-environment jsdom
import {afterEach,it,expect,vi} from 'vitest';
import {cleanup,render,screen,waitFor} from '@testing-library/react';
import {App} from './App';
import {api} from './api/client';
vi.mock('./api/client',()=>({ApiError:class extends Error{},api:{health:vi.fn(),startDemo:vi.fn(),preferences:vi.fn().mockResolvedValue({preferred_language:'en'}),listMedications:vi.fn(),regimenHistory:vi.fn()}}));
afterEach(()=>{cleanup();localStorage.clear();vi.resetAllMocks();});
it('refuses stale backend before any authenticated setup or business query',async()=>{
 vi.mocked(api.health).mockResolvedValue({status:'ok',service:'pharmascan-care-agent',database:'supabase',llm:'unavailable_deterministic_degraded',stage2_vision:'simulated'});
 render(<App/>);await screen.findByText(/app connection needs a restart/);
 expect(api.startDemo).not.toHaveBeenCalled();expect(api.listMedications).not.toHaveBeenCalled();expect(screen.queryByText(/No dose due right now/)).toBeNull();
});
it('failed medication read is shown as unavailable instead of zero active medicines',async()=>{
 vi.mocked(api.health).mockResolvedValue({status:'ok',service:'pharmascan-care-agent',database:'supabase',llm:'unavailable_deterministic_degraded',stage2_vision:'live',runtime_contract:'session03-manual-acceptance-v2'});
 vi.mocked(api.preferences).mockResolvedValue({patient_id:'demo-patient',preferred_language:'en',speech_locale:'en-SG',text_size:'standard',voice_enabled:true,tts_autoplay:false,reminder_lead_minutes:0,timezone:'Asia/Singapore',created_at:'2026-10-14T00:00:00Z',updated_at:'2026-10-14T00:00:00Z'});
 vi.mocked(api.startDemo).mockResolvedValue({patient_id:'demo-patient',session_id:'demo-session',demo_only:true,seeded_medication_count:0,note:'demo_only'});
 vi.mocked(api.listMedications).mockRejectedValue(new Error('Records unavailable'));vi.mocked(api.regimenHistory).mockResolvedValue([]);
 render(<App/>);await waitFor(()=>expect(screen.getByText(/unavailable record is not an empty medication list/)).toBeTruthy());expect(screen.queryByRole('button',{name:'Compare a pill photo'})).toBeNull();
});
