// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,within} from '@testing-library/react';
import {api} from '../api/client';
import {LanguageProvider,useLanguage} from '../language';
import {RecordsOverview} from './RecordsOverview';

vi.mock('../api/client',()=>({api:{updatePreferences:vi.fn()}}));
vi.mock('./LateDoseFollowUps',()=>({LateDoseFollowUps:({showHeading}:{showHeading?:boolean})=><div data-testid="pending-records" data-heading={String(showHeading)}/> }));
afterEach(()=>{cleanup();vi.resetAllMocks();});

function SelectChinese(){const {setLanguage}=useLanguage();return <button onClick={()=>setLanguage('zh')}>Set Chinese</button>;}
function fixture(){return {lateReportsEnabled:true,onOpenSummary:vi.fn(),onOpenMedicationRecords:vi.fn(),onOpenArea:vi.fn()};}

it('puts the pale-green summary first and keeps pending reports collapsed until requested',()=>{
 const props=fixture();const {container}=render(<LanguageProvider><RecordsOverview {...props}/></LanguageProvider>);
 const summary=container.querySelector('.records-summary--highlight')!;const pending=container.querySelector<HTMLDetailsElement>('.records-pending-disclosure')!;
 expect(container.firstElementChild).toBe(summary);expect(pending.open).toBe(false);
 expect(screen.getByText('Open to review scheduled doses from the past 7 days; eligibility still applies.')).toBeTruthy();
 expect(pending.querySelector('.records-pending-disclosure__chevron svg')).toBeTruthy();
 expect(screen.getByTestId('pending-records').getAttribute('data-heading')).toBe('false');
 fireEvent.click(within(pending).getByText('Open to review scheduled doses from the past 7 days; eligibility still applies.'));
 expect(pending.open).toBe(true);
});

it('shows Chinese summary period labels and opens the medication-records destination from its card',async()=>{
 vi.mocked(api.updatePreferences).mockResolvedValue({patient_id:'DEMO',preferred_language:'zh',speech_locale:'zh-CN',text_size:'standard',voice_enabled:true,tts_autoplay:false,reminder_lead_minutes:0,timezone:'Asia/Singapore',created_at:'2026-01-01T00:00:00Z',updated_at:'2026-01-01T00:00:00Z'});
 const props=fixture();render(<LanguageProvider><SelectChinese/><RecordsOverview {...props}/></LanguageProvider>);
 fireEvent.click(screen.getByText('Set Chinese'));
 expect(await screen.findByText('点击查看近 7 天的计划剂次；是否可补记仍取决于计划状态。')).toBeTruthy();
 expect(await screen.findByRole('heading',{name:'用药与健康总结'})).toBeTruthy();
 expect(await screen.findByRole('button',{name:'本周'})).toBeTruthy();
 expect(screen.getByRole('button',{name:'本月'})).toBeTruthy();expect(screen.getByRole('button',{name:'按用药计划'})).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:/我的用药记录/}));expect(props.onOpenMedicationRecords).toHaveBeenCalledOnce();
 fireEvent.click(screen.getByRole('button',{name:'本周'}));expect(props.onOpenSummary).toHaveBeenCalledWith('week');
});
