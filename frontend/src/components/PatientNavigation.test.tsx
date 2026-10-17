// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {HealthTrackingScreen} from './HealthTrackingScreen';
import {InformationScreen,PatientHub} from './PatientHub';
import {MedicinesHub,AddMethodScreen,isPastCourse} from './MedicinesHub';
import {ReviewSummaryScreen} from './ReviewSummaryScreen';
import {api,type HealthObservation,type MedicationSummary} from '../api/client';

vi.mock('../api/client',()=>({ApiError:class extends Error{},api:{observations:vi.fn(),saveObservation:vi.fn(),deleteObservation:vi.fn(),reviewSummary:vi.fn(),agentUsage:vi.fn().mockResolvedValue({limit:20})}}));
vi.mock('../api/auth',()=>({accountAuth:{account:async()=>({kind:'guest',email:null,verified:false})}}));
afterEach(()=>{cleanup();vi.resetAllMocks();});
const medication:MedicationSummary={medication_id:'DEMO-med',regimen_id:'DEMO-regimen',display_name:'DEMO Metformin',is_prn:false,version_no:1,identity_status:'unverified',source_backed:true,dose_amount:500,dose_unit:'mg',frequency_rule:{kind:'daily',local_times:['20:00'],days_of_week:[]},food_instruction:'after food',course_start_date:'2026-10-14',course_end_date:'2099-10-20'};
it('Me is an entry hierarchy with a separate account destination, not an expanded email form',async()=>{
 const open=vi.fn(),guide=vi.fn();render(<PatientHub onOpen={open} onGuide={guide}/>);await screen.findAllByText('Guest');
 expect(document.querySelectorAll('.me-category')).toHaveLength(3);
 for(const category of document.querySelectorAll('.me-category'))expect(category.querySelectorAll('.ui-row')).toHaveLength(2);
 expect(document.querySelectorAll('.me-app-info .ui-row')).toHaveLength(3);
 expect(screen.queryByLabelText('Email')).toBeNull();expect(screen.queryByRole('button',{name:/Singpass/})).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'Login or register'}));expect(open).toHaveBeenLastCalledWith('account');
 fireEvent.click(screen.getByRole('button',{name:/Personal profile/}));expect(open).toHaveBeenLastCalledWith('profile');
 fireEvent.click(screen.getByRole('button',{name:/Language and speech/}));expect(open).toHaveBeenLastCalledWith('language-settings');
 fireEvent.click(screen.getByRole('button',{name:/Text size/}));expect(open).toHaveBeenLastCalledWith('accessibility');
 fireEvent.click(screen.getByRole('button',{name:/Assistant and conversation saving/}));expect(open).toHaveBeenLastCalledWith('conversations');
 fireEvent.click(screen.getByRole('button',{name:/Privacy controls/}));expect(open).toHaveBeenLastCalledWith('privacy');
 fireEvent.click(screen.getByRole('button',{name:/Caregiver contacts/}));expect(open).toHaveBeenLastCalledWith('caregivers');
 fireEvent.click(screen.getByRole('button',{name:/Medication reminders/}));expect(open).toHaveBeenLastCalledWith('reminder-settings');
 fireEvent.click(screen.getByRole('button',{name:/Help \/ User Guide/}));expect(guide).toHaveBeenCalledOnce();
 fireEvent.click(screen.getByRole('button',{name:/About MediThread/}));expect(open).toHaveBeenLastCalledWith('about');
 fireEvent.click(screen.getByRole('button',{name:/Feedback/}));expect(open).toHaveBeenLastCalledWith('feedback');
});
it('Medicines has grouped database-backed entries and a separate add-method choice',()=>{
 const open=vi.fn();const {unmount}=render(<MedicinesHub medications={[medication]} drafts={[]} versions={[]} setupCount={1} onOpen={open}/>);
 expect(screen.getByRole('heading',{name:'Currently taking'})).toBeTruthy();expect(screen.queryByLabelText('Medication name')).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:/DEMO Metformin/}));expect(open).toHaveBeenCalledWith('medicine-detail','DEMO-regimen');
 fireEvent.click(screen.getByRole('button',{name:/Add medication/}));expect(open).toHaveBeenCalledWith('add-method');
 fireEvent.click(screen.getByRole('button',{name:/Past courses/}));expect(open).toHaveBeenCalledWith('past-medicines');
 fireEvent.click(screen.getByRole('button',{name:/Photos and evidence/}));expect(open).toHaveBeenCalledWith('gallery');
 fireEvent.click(screen.getByRole('button',{name:/Finish medication setup/}));expect(open).toHaveBeenCalledWith('unfinished');
 unmount();render(<AddMethodScreen onOpen={open}/>);fireEvent.click(screen.getByRole('button',{name:/Read medication information/}));expect(open).toHaveBeenCalledWith('label');
 fireEvent.click(screen.getByRole('button',{name:/Add manually/}));expect(open).toHaveBeenCalledWith('manual');
 expect(isPastCourse({course_end_date:'2026-10-14'},'2026-10-14')).toBe(false);expect(isPastCourse({course_end_date:'2026-10-14'},'2026-10-15')).toBe(true);
});
it.each([0,1,2,5,10])('Medicines shows all %i current plans and keeps three real shortcuts',count=>{
 const medications=Array.from({length:count},(_,index)=>({...medication,medication_id:`DEMO-med-${index}`,regimen_id:`DEMO-regimen-${index}`,display_name:`DEMO Medicine ${index+1}`}));
 render(<MedicinesHub medications={medications} drafts={[]} versions={[]} setupCount={1} onOpen={vi.fn()}/>);
 expect(screen.getByRole('navigation',{name:'Medication management shortcuts'}).querySelectorAll('button')).toHaveLength(3);
 expect(document.querySelectorAll('.medicines-courses .ui-row')).toHaveLength(count);
 for(let index=0;index<count;index++)expect(screen.getByText(`DEMO Medicine ${index+1}`,{exact:true})).toBeTruthy();
 if(count===0)expect(screen.getByText('No current medication plans.')).toBeTruthy();
});
it('About MediThread does not duplicate privacy navigation',()=>{
 vi.mocked(api.agentUsage).mockResolvedValue({limit:20} as never);
 render(<InformationScreen kind="about" onHistory={vi.fn()}/>);
 expect(screen.getByRole('heading',{name:'About MediThread'})).toBeTruthy();
 expect(screen.queryByRole('button',{name:'Privacy and data'})).toBeNull();
});
it('health review cancellation never saves; confirmation, edit and deletion are explicit',async()=>{
 vi.mocked(api.observations).mockResolvedValue([]);const record:HealthObservation={id:'DEMO-note',patient_id:'DEMO-owner',description:'DEMO feeling dizzy',occurred_at:'2026-10-14T00:00:00Z',notes:null,severity:null,medication_id:null,source:'patient_reported',created_at:'2026-10-14T00:00:00Z',updated_at:'2026-10-14T00:00:00Z',demo_only:true};
 vi.mocked(api.saveObservation).mockResolvedValue(record);vi.mocked(api.deleteObservation).mockResolvedValue({deleted:true});
 render(<HealthTrackingScreen medications={[medication]}/>);await screen.findByText(/No health notes yet/);
 fireEvent.change(screen.getByLabelText('Describe how you feel (required)'),{target:{value:'DEMO feeling dizzy'}});fireEvent.click(screen.getByRole('button',{name:'Review health note'}));
 expect(api.saveObservation).not.toHaveBeenCalled();fireEvent.click(screen.getByRole('button',{name:'Cancel'}));expect(api.saveObservation).not.toHaveBeenCalled();
 vi.mocked(api.observations).mockResolvedValue([record]);fireEvent.click(screen.getByRole('button',{name:'Review health note'}));fireEvent.click(screen.getByRole('button',{name:'Confirm record'}));
 await waitFor(()=>expect(api.saveObservation).toHaveBeenCalledWith(expect.objectContaining({confirmed:true,description:'DEMO feeling dizzy',medication_id:null})));
 await screen.findByRole('button',{name:'Edit'});fireEvent.click(screen.getByRole('button',{name:'Edit'}));expect(screen.getByLabelText('Describe how you feel (required)')).toHaveProperty('value','DEMO feeling dizzy');
 fireEvent.click(screen.getByRole('button',{name:'Delete'}));expect(api.deleteObservation).not.toHaveBeenCalled();
 const dialog=screen.getByRole('dialog',{name:'Delete this health note?'});expect(dialog).toBeTruthy();vi.mocked(api.observations).mockResolvedValue([]);
 fireEvent.click(dialog.querySelector('button:last-child')!);await waitFor(()=>expect(api.deleteObservation).toHaveBeenCalledWith('DEMO-note'));
});
it('periodic summary uses actual HTTP counts and patient descriptions instead of a static option card',async()=>{
 vi.mocked(api.reviewSummary).mockResolvedValue({period:'week',window_start:'2026-10-11T16:00:00Z',window_end:'2026-10-14T00:00:00Z',generated_at:'2026-10-14T00:00:00Z',timezone:'Asia/Singapore',medications:[],reported_taken:2,reported_not_taken:1,unsure:0,observations:[],questions:[],coverage_note:'No report is not a missed dose.'});
 render(<ReviewSummaryScreen period="week" regimens={[]}/>);await screen.findByText('No report is not a missed dose.');expect(api.reviewSummary).toHaveBeenCalledWith('week',undefined);
 expect(screen.getByText('2')).toBeTruthy();expect(screen.getByRole('button',{name:'Export summary'})).toBeTruthy();expect(screen.getByText(/No health notes yet/)).toBeTruthy();
});
