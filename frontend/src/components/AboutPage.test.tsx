// @vitest-environment jsdom
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import {InformationScreen} from './PatientHub';
import {api} from '../api/client';
import {aboutCopy} from '../aboutCopy';
import {appVersionLabel} from '../appMetadata';
import packageMetadata from '../../package.json';
import {LanguageProvider,useLanguage} from '../language';
import {useEffect,type ReactNode} from 'react';

vi.mock('../api/client',()=>({api:{agentUsage:vi.fn(),preferences:vi.fn()}}));
vi.mock('../api/auth',()=>({accountAuth:{account:async()=>({kind:'guest',email:null,verified:false})}}));

beforeEach(()=>vi.mocked(api.agentUsage).mockResolvedValue({llm_user_turns:2,model_requests:3,limit:20,usage_date:'2026-10-20',next_reset_at:'2026-10-20T16:00:00Z'}));
afterEach(()=>{cleanup();vi.resetAllMocks();});

it('presents six supported capabilities, a three-step workflow, trust guidance and roadmap states',async()=>{
 render(<InformationScreen kind="about" onHistory={vi.fn()} onPrivacy={vi.fn()} onFeedback={vi.fn()}/>);
 expect(screen.getByRole('heading',{name:'About MediThread'})).toBeTruthy();
 expect(document.querySelectorAll('.about-feature')).toHaveLength(6);
 expect(screen.getByRole('heading',{name:'How MediThread fits your day'})).toBeTruthy();
 expect(document.querySelectorAll('.about-workflow li')).toHaveLength(3);
 expect(screen.getByText('Planned')).toBeTruthy();expect(screen.getByText('Exploring')).toBeTruthy();
 expect(screen.getByText(/Current PDF storage does not read or verify prescriptions/)).toBeTruthy();
 expect(screen.queryByText(/PDF understanding is available/)).toBeNull();
 expect(await screen.findByText(/Daily limit: 20 conversations per day/)).toBeTruthy();
 expect(screen.getByText(/Singapore time/)).toBeTruthy();
 expect(screen.getByText(appVersionLabel)).toBeTruthy();
});

it('uses the package manifest as the single application version source',()=>{
 expect(appVersionLabel).toBe(`v${packageMetadata.version}`);
});

it('keeps privacy and feedback actions on existing destinations',()=>{
 const privacy=vi.fn(),feedback=vi.fn();render(<InformationScreen kind="about" onHistory={vi.fn()} onPrivacy={privacy} onFeedback={feedback}/>);
 fireEvent.click(screen.getByRole('button',{name:/Privacy controls/}));fireEvent.click(screen.getByRole('button',{name:/Send feedback/}));
 expect(privacy).toHaveBeenCalledOnce();expect(feedback).toHaveBeenCalledOnce();
});

it('provides Chinese copy for every About section and distinguishes released from future work',()=>{
 for(const key of ['About MediThread','Medication & regimen management','Medication evidence & photo review','Reminders & care tasks','Adherence & health records','AI assistant','Healthcare visit preparation','How MediThread fits your day','Trust & responsible AI','Future work','Planned','Exploring','Product & service information','Prescription PDF understanding','More languages & caregiver support']){
  expect(aboutCopy[key],`missing Chinese translation for ${key}`).toBeTruthy();
  expect(aboutCopy[key]).not.toBe(key);
 }
 expect(aboutCopy['Future work may add OCR and structured extraction of medication and instruction details, followed by your review. Current PDF storage does not read or verify prescriptions.']).toContain('OCR');
});

function LoadChinese({children}:{children:ReactNode}){const {loadPreferences}=useLanguage();useEffect(()=>{void loadPreferences();},[loadPreferences]);return children;}
it('renders the localized About hierarchy and roadmap in Chinese',async()=>{
 vi.mocked(api.preferences).mockResolvedValue({patient_id:'DEMO-owner',preferred_language:'zh',speech_locale:'zh-CN',text_size:'standard',voice_enabled:true,tts_autoplay:false,reminder_lead_minutes:0,timezone:'Asia/Singapore',created_at:'2026-10-20T00:00:00Z',updated_at:'2026-10-20T00:00:00Z'});
 render(<LanguageProvider><LoadChinese><InformationScreen kind="about" onHistory={vi.fn()}/></LoadChinese></LanguageProvider>);
 expect(await screen.findByRole('heading',{name:'关于 MediThread'})).toBeTruthy();
 expect(screen.getByRole('heading',{name:'用药与疗程管理'})).toBeTruthy();
 expect(screen.getByRole('heading',{name:'可信使用与负责任的 AI'})).toBeTruthy();
 expect(screen.getByRole('heading',{name:'未来规划'})).toBeTruthy();
 expect(screen.getByText('计划中')).toBeTruthy();expect(screen.getByText('探索中')).toBeTruthy();
});
