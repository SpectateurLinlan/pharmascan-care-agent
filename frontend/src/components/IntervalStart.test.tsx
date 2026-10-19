// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {EnrollScreen} from './EnrollScreen';
import {api,type RegimenHistoryItem} from '../api/client';

afterEach(()=>{cleanup();vi.restoreAllMocks();});

it.each(['','07:00'])('asks for a first time, labels the default and preserves review before creating a draft (%s)',async(time)=>{
 const create=vi.spyOn(api,'createDraft').mockResolvedValue({medication_id:'DEMO-m',regimen_id:'DEMO-r',source_id:'DEMO-s',state:'draft',missing_instructions:['dose_amount'],reviewable_field_ids:[],note:'DEMO_ONLY'});
 const activate=vi.spyOn(api,'activate');
 render(<EnrollScreen sessionId="DEMO-session" medications={null} onChanged={()=>undefined}/>);
 fireEvent.change(screen.getByLabelText('Medication name'),{target:{value:'DEMO interval'}});
 fireEvent.change(screen.getByLabelText('Schedule'),{target:{value:'interval'}});
 expect(screen.getByText(/When is the first dose/).textContent).toContain('08:00');
 expect(screen.getByLabelText('First dose time (optional)')).toHaveProperty('value','');
 fireEvent.change(screen.getByLabelText('Interval in hours'),{target:{value:'8'}});
 fireEvent.change(screen.getByLabelText('Course start date'),{target:{value:'2026-10-18'}});
 if(time)fireEvent.change(screen.getByLabelText('First dose time (optional)'),{target:{value:time}});
 fireEvent.click(screen.getByRole('button',{name:'Review and add'}));
 expect(create).not.toHaveBeenCalled();
 expect(screen.getByText(`Every N hours: 8; First dose time: ${time||'Default 08:00'}`)).toBeTruthy();
 fireEvent.click(screen.getByRole('checkbox',{name:'I have checked these details against my original instructions.'}));
 fireEvent.click(screen.getByRole('button',{name:'Add this medication'}));
 await waitFor(()=>expect(create).toHaveBeenCalledWith(expect.objectContaining({frequency_kind:'interval',frequency_every_hours:8,frequency_local_times:time?[time]:[],course_start_date:'2026-10-18'}),undefined));
 expect(activate).not.toHaveBeenCalled();
});

it('requires a date and valid interval rather than guessing today',()=>{
 render(<EnrollScreen sessionId="DEMO-session" medications={null} onChanged={()=>undefined}/>);
 fireEvent.change(screen.getByLabelText('Medication name'),{target:{value:'DEMO interval'}});
 fireEvent.change(screen.getByLabelText('Schedule'),{target:{value:'interval'}});
 fireEvent.change(screen.getByLabelText('Interval in hours'),{target:{value:'8'}});
 expect(screen.getByRole('button',{name:'Review and add'})).toHaveProperty('disabled',true);
});

it('resumes an interval draft without converting it to daily or resetting a new first time on refresh',async()=>{
 vi.spyOn(api,'resumeDraft').mockResolvedValue({medication_id:'DEMO-m',regimen_id:'DEMO-r',source_id:'DEMO-s',state:'draft',missing_instructions:[],reviewable_field_ids:[],note:'DEMO_ONLY'});
 const row:RegimenHistoryItem={regimen_id:'DEMO-r',medication_id:'DEMO-m',display_name:'DEMO interval resumed',version_no:1,state:'draft',effective_from:null,effective_to:null,course_start_date:'2026-10-18',course_end_date:null,dose_amount:1,dose_unit:'tablet',food_instruction:null,is_prn:false,local_times:['08:00'],frequency_rule:{kind:'interval',local_times:['08:00'],days_of_week:[],every_hours:8,interval_anchor:{local_date:'2026-10-18',local_time:'08:00',time_source:'default_0800'}}};
 const props={resumeRegimenId:row.regimen_id,resumeRow:row,sessionId:'DEMO-session',medications:null,onChanged:()=>undefined};
 const {rerender}=render(<EnrollScreen {...props}/>);
 await waitFor(()=>expect(screen.getByLabelText('Interval in hours')).toHaveProperty('value','8'));
 expect(screen.getByLabelText('Schedule')).toHaveProperty('value','interval');
 expect(screen.getByLabelText('First dose time (optional)')).toHaveProperty('value','');
 fireEvent.change(screen.getByLabelText('First dose time (optional)'),{target:{value:'07:00'}});
 rerender(<EnrollScreen {...props} resumeRow={{...row}}/>);
 expect(screen.getByLabelText('First dose time (optional)')).toHaveProperty('value','07:00');
});
