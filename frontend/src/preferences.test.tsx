// @vitest-environment jsdom
/** AUTOMATED/SIMULATED preference and quota display, no provider calls. */
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {cleanup,render,screen,fireEvent} from '@testing-library/react';
import {LanguageProvider,useLanguage} from './language';
import {AssistantScreen} from './components/AssistantScreen';
import {api} from './api/client';

vi.mock('./api/client',()=>({api:{preferences:vi.fn(),updatePreferences:vi.fn(),agentUsage:vi.fn()}}));
afterEach(cleanup);
function Harness(){const {loadPreferences,setLanguage,language}=useLanguage();return <><button onClick={()=>void loadPreferences()}>Load preference</button><button onClick={()=>setLanguage('zh')}>Save Chinese</button><span data-testid="language">{language}</span><AssistantScreen sessionId={null} onSession={()=>undefined}/></>;}
beforeEach(()=>{
 vi.resetAllMocks();
 vi.mocked(api.preferences).mockResolvedValue({patient_id:'00000000-0000-0000-0000-000000000100',preferred_language:'zh',speech_locale:'zh-CN',text_size:'standard',voice_enabled:false,tts_autoplay:false,reminder_lead_minutes:0,timezone:'Asia/Singapore',created_at:'2026-10-14T00:00:00Z',updated_at:'2026-10-14T00:00:00Z'});
 vi.mocked(api.agentUsage).mockResolvedValue({usage_date:'2026-10-14',llm_user_turns:18,model_requests:25,limit:20,next_reset_at:'2026-10-14T16:00:00Z'});
});
it('loads the persisted Chinese preference and readable daily quota/reset disclosure',async()=>{
 render(<LanguageProvider><Harness/></LanguageProvider>);fireEvent.click(screen.getByText('Load preference'));
 expect((await screen.findByText(/今日剩余 AI 对话次数: 2 \/ 20/)).textContent).toContain('新加坡时间凌晨零点重置');
 expect(screen.getByTestId('language').textContent).toBe('zh');
 expect((screen.getByLabelText('发送前检查或编辑内容') as HTMLInputElement).disabled).toBe(false);
});
it('retains the previous language if saving preferences fails',async()=>{
 vi.mocked(api.updatePreferences).mockRejectedValue(new Error('SIMULATED network failure'));
 render(<LanguageProvider><Harness/></LanguageProvider>);fireEvent.click(screen.getByText('Save Chinese'));
 expect(screen.getByTestId('language').textContent).toBe('en');
 expect(await screen.findByText(/Resets at midnight Singapore time/)).not.toBeNull();
});
