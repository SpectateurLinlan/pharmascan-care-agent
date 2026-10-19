// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,within} from '@testing-library/react';
import type {RegimenHistoryItem} from '../api/client';
import {RegimenHistoryScreen} from './RegimenHistoryScreen';
import {LanguageProvider,useLanguage} from '../language';
import {api,type PatientPreferences} from '../api/client';

afterEach(()=>{cleanup();vi.restoreAllMocks();});
function regimen(overrides:Partial<RegimenHistoryItem>&Pick<RegimenHistoryItem,'regimen_id'|'display_name'|'state'>):RegimenHistoryItem{return Object.assign({medication_id:'DEMO-med',supersedes_id:null,version_no:1,effective_from:null,effective_to:null,course_start_date:null,course_end_date:null,dose_amount:1,dose_unit:'tablet',food_instruction:null,is_prn:false,local_times:[]},overrides);}

it('searches medication names case-insensitively, filters actual historical states and preserves same-name regimens',()=>{
 const rows=[regimen({regimen_id:'DEMO-amlodipine-1',display_name:'DEMO Amlodipine',state:'ended'}),regimen({regimen_id:'DEMO-amlodipine-2',display_name:'DEMO Amlodipine',state:'superseded',course_start_date:'2026-04-12',course_end_date:'2026-05-30'}),regimen({regimen_id:'DEMO-active',display_name:'DEMO Amlodipine',state:'active',course_end_date:'2020-01-01'}),regimen({regimen_id:'DEMO-future',display_name:'DEMO Future',state:'active',course_start_date:'2099-01-01'}),regimen({regimen_id:'DEMO-draft',display_name:'DEMO Draft',state:'draft'})];
 const onOpen=vi.fn();render(<RegimenHistoryScreen regimens={rows} onOpen={onOpen}/>);
 const cards=screen.getAllByRole('button',{name:/View Regimen Details/});expect(cards).toHaveLength(4);
 expect(screen.getAllByText('DEMO Amlodipine',{exact:true})).toHaveLength(3);expect(screen.getByText('DEMO Future')).toBeTruthy();
 fireEvent.change(screen.getByRole('searchbox',{name:'Search medication name'}),{target:{value:'AMLO'} });expect(screen.getAllByRole('button',{name:/View Regimen Details/})).toHaveLength(3);
 fireEvent.change(screen.getByLabelText('Filter by status'),{target:{value:'active'}});expect(screen.queryAllByRole('button',{name:/View Regimen Details/})).toHaveLength(0);
 fireEvent.change(screen.getByLabelText('Filter by status'),{target:{value:'ended'}});
 fireEvent.click(screen.getAllByRole('button',{name:/View Regimen Details/}).find(row=>row.textContent?.includes('Course Ended as Scheduled'))!);expect(onOpen).toHaveBeenCalledWith('DEMO-active');
});

it('collapses a supersession chain into its latest historical version and leaves version-effective timestamps out of course dates',()=>{
 const rows=[regimen({regimen_id:'DEMO-v1',display_name:'DEMO Metformin',state:'superseded',course_start_date:'2026-01-01',course_end_date:'2026-02-01',effective_from:'2026-10-01T00:00:00Z'}),regimen({regimen_id:'DEMO-v2',display_name:'DEMO Metformin',state:'ended',supersedes_id:'DEMO-v1',version_no:2,course_start_date:'2026-03-01',course_end_date:'2026-04-01',effective_from:'2026-10-10T00:00:00Z'})];
 render(<RegimenHistoryScreen regimens={rows} onOpen={vi.fn()}/>);
 expect(screen.getAllByRole('button',{name:/View Regimen Details/})).toHaveLength(1);
 expect(screen.getByText('2 plan versions')).toBeTruthy();expect(screen.getByText('2026-03-01 to 2026-04-01')).toBeTruthy();expect(screen.queryByText(/2026-10/)).toBeNull();
 expect(screen.getAllByText('Ended',{exact:true})).toHaveLength(2);
});

it('uses actual course dates, sorts missing dates last and has a neutral missing-date label',()=>{
 const rows=[regimen({regimen_id:'DEMO-no-date',display_name:'DEMO A',state:'ended'}),regimen({regimen_id:'DEMO-new',display_name:'DEMO B',state:'ended',course_start_date:'2026-06-01',course_end_date:'2026-07-01'}),regimen({regimen_id:'DEMO-old',display_name:'DEMO C',state:'ended',course_start_date:'2026-01-01',course_end_date:'2026-02-01'})];
 render(<RegimenHistoryScreen regimens={rows} onOpen={vi.fn()}/>);
 const cards=screen.getAllByRole('button',{name:/View Regimen Details/});expect(within(cards[0]!).getByText('2026-06-01 to 2026-07-01')).toBeTruthy();expect(within(cards[2]!).getByText(/Start date not recorded/)).toBeTruthy();
 expect(document.querySelectorAll('.regimen-history-card__date svg')).toHaveLength(3);
 fireEvent.change(screen.getByLabelText('Sort regimens'),{target:{value:'oldest-ended'}});const sorted=screen.getAllByRole('button',{name:/View Regimen Details/});expect(within(sorted[0]!).getByText(/2026-02-01/)).toBeTruthy();expect(within(sorted[2]!).getByText(/Start date not recorded/)).toBeTruthy();
});

it('localises the history title, status, controls and card action in Chinese',async()=>{
 vi.spyOn(api,'updatePreferences').mockResolvedValue({patient_id:'DEMO-patient',preferred_language:'zh',speech_locale:'zh-CN',text_size:'standard',voice_enabled:false,tts_autoplay:false,reminder_lead_minutes:0,timezone:'Asia/Singapore',created_at:'2026-10-19T00:00:00Z',updated_at:'2026-10-19T00:00:00Z'} satisfies PatientPreferences);
 function SwitchLanguage(){const {setLanguage}=useLanguage();return <button type="button" onClick={()=>setLanguage('zh')}>DEMO Chinese</button>;}
 render(<LanguageProvider><SwitchLanguage/><RegimenHistoryScreen regimens={[regimen({regimen_id:'DEMO-zh',display_name:'DEMO Amlodipine',state:'superseded'})]} onOpen={vi.fn()}/></LanguageProvider>);
 fireEvent.click(screen.getByRole('button',{name:'DEMO Chinese'}));
 await screen.findByRole('heading',{name:'疗程记录'});expect(screen.getAllByText('\u5df2\u88ab\u66ff\u4ee3',{exact:true})).toHaveLength(1);expect(screen.getByRole('button',{name:/\u67e5\u770b\u7597\u7a0b\u8be6\u60c5/})).toBeTruthy();expect(screen.getByRole('searchbox',{name:'\u641c\u7d22\u836f\u7269\u540d\u79f0'})).toBeTruthy();
});

it('keeps its controls mounted but hidden while the user opens a regimen',()=>{
 const onOpen=vi.fn();render(<RegimenHistoryScreen active={false} regimens={[regimen({regimen_id:'DEMO-ended',display_name:'DEMO Ended',state:'ended'})]} onOpen={onOpen}/>);
 const page=screen.getByTestId('regimen-history-page');expect(page.hasAttribute('hidden')).toBe(true);expect(page.querySelector('input[type="search"]')).toBeTruthy();
});

it('includes active past-date courses by default and filters lifecycle without mutation',()=>{
 const past=regimen({regimen_id:'DEMO-active',display_name:'DEMO tracked',state:'active',course_end_date:'2004-01-01'});
 render(<RegimenHistoryScreen regimens={[past,regimen({regimen_id:'DEMO-ended',display_name:'DEMO ended',state:'ended'})]} onOpen={vi.fn()}/>);
 expect(screen.getByLabelText('Filter by status')).toHaveProperty('value','all');
 expect(screen.getByText('Course Ended as Scheduled')).toBeTruthy();
 expect(screen.getAllByRole('button',{name:/View Regimen Details/})).toHaveLength(2);
 fireEvent.change(screen.getByLabelText('Filter by status'),{target:{value:'ended'}});
 expect(screen.getByText('DEMO tracked')).toBeTruthy();expect(screen.getByText('DEMO ended')).toBeTruthy();expect(past.state).toBe('active');
});
it('does not merge different registrations through invalid cross-medication links',()=>{
 const rows=[regimen({regimen_id:'DEMO-old',display_name:'DEMO same',state:'ended',medication_id:'DEMO-A'}),regimen({regimen_id:'DEMO-new',display_name:'DEMO same',state:'active',supersedes_id:'DEMO-old',version_no:2,medication_id:'DEMO-B'})];
 render(<RegimenHistoryScreen regimens={rows} onOpen={vi.fn()}/>);expect(screen.getAllByRole('button',{name:/View Regimen Details/})).toHaveLength(2);
});
