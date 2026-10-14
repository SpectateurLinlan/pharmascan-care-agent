// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {HealthTrackingScreen} from './HealthTrackingScreen';
import {PatientHub} from './PatientHub';
import {MedicinesHub,AddMethodScreen,isPastCourse} from './MedicinesHub';
import {ReviewSummaryScreen} from './ReviewSummaryScreen';
import {api,type HealthObservation,type MedicationSummary} from '../api/client';

vi.mock('../api/client',()=>({ApiError:class extends Error{},api:{observations:vi.fn(),saveObservation:vi.fn(),deleteObservation:vi.fn(),reviewSummary:vi.fn()}}));
vi.mock('../api/auth',()=>({accountAuth:{account:async()=>({kind:'guest',email:null,verified:false})}}));
afterEach(()=>{cleanup();vi.resetAllMocks();});
const medication:MedicationSummary={medication_id:'DEMO-med',regimen_id:'DEMO-regimen',display_name:'DEMO Metformin',is_prn:false,version_no:1,identity_status:'unverified',source_backed:true,dose_amount:500,dose_unit:'mg',frequency_rule:{kind:'daily',local_times:['20:00'],days_of_week:[]},food_instruction:'after food',course_start_date:'2026-10-14',course_end_date:'2099-10-20'};
it('Me is an entry hierarchy with a separate account destination, not an expanded email form',async()=>{
 const open=vi.fn();render(<PatientHub onOpen={open}/>);await screen.findByText('Guest demo');
 expect(screen.queryByLabelText('Email')).toBeNull();expect(screen.queryByRole('button',{name:/Singpass/})).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'Login or register'}));expect(open).toHaveBeenLastCalledWith('account');
 fireEvent.click(screen.getByRole('button',{name:/Personal profile/}));expect(open).toHaveBeenLastCalledWith('profile');
 fireEvent.click(screen.getByRole('button',{name:/Privacy and data/}));expect(open).toHaveBeenLastCalledWith('privacy');
});
it('Medicines has grouped database-backed entries and a separate add-method choice',()=>{
 const open=vi.fn();const {unmount}=render(<MedicinesHub medications={[medication]} drafts={[]} versions={[]} onOpen={open}/>);
 expect(screen.getByRole('heading',{name:'Currently taking'})).toBeTruthy();expect(screen.queryByLabelText('Medication name')).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:/DEMO Metformin/}));expect(open).toHaveBeenCalledWith('medicine-detail','DEMO-regimen');
 fireEvent.click(screen.getByRole('button',{name:/Add medication/}));expect(open).toHaveBeenCalledWith('add-method');
 unmount();render(<AddMethodScreen onOpen={open}/>);fireEvent.click(screen.getByRole('button',{name:/Read medication information/}));expect(open).toHaveBeenCalledWith('label');
 fireEvent.click(screen.getByRole('button',{name:/Add manually/}));expect(open).toHaveBeenCalledWith('manual');
 expect(isPastCourse({course_end_date:'2026-10-14'},'2026-10-14')).toBe(false);expect(isPastCourse({course_end_date:'2026-10-14'},'2026-10-15')).toBe(true);
});
it('health review cancellation never saves; confirmation, edit and deletion are explicit',async()=>{
 vi.mocked(api.observations).mockResolvedValue([]);const record:HealthObservation={id:'DEMO-note',patient_id:'DEMO-owner',description:'DEMO feeling dizzy',occurred_at:'2026-10-14T00:00:00Z',notes:null,severity:null,medication_id:null,source:'patient_reported',created_at:'2026-10-14T00:00:00Z',updated_at:'2026-10-14T00:00:00Z',demo_only:true};
 vi.mocked(api.saveObservation).mockResolvedValue(record);vi.mocked(api.deleteObservation).mockResolvedValue({deleted:true});
 render(<HealthTrackingScreen medications={[medication]}/>);await screen.findByText(/No health notes recorded/);
 fireEvent.change(screen.getByLabelText('Describe how you feel'),{target:{value:'DEMO feeling dizzy'}});fireEvent.click(screen.getByRole('button',{name:'Review health note'}));
 expect(api.saveObservation).not.toHaveBeenCalled();fireEvent.click(screen.getByRole('button',{name:'Cancel'}));expect(api.saveObservation).not.toHaveBeenCalled();
 vi.mocked(api.observations).mockResolvedValue([record]);fireEvent.click(screen.getByRole('button',{name:'Review health note'}));fireEvent.click(screen.getByRole('button',{name:'Confirm record'}));
 await waitFor(()=>expect(api.saveObservation).toHaveBeenCalledWith(expect.objectContaining({confirmed:true,description:'DEMO feeling dizzy',medication_id:null})));
 await screen.findByRole('button',{name:'Edit'});fireEvent.click(screen.getByRole('button',{name:'Edit'}));expect(screen.getByLabelText('Describe how you feel')).toHaveProperty('value','DEMO feeling dizzy');
 fireEvent.click(screen.getByRole('button',{name:'Delete'}));expect(api.deleteObservation).not.toHaveBeenCalled();
 const dialog=screen.getByRole('dialog',{name:'Delete this health note?'});expect(dialog).toBeTruthy();vi.mocked(api.observations).mockResolvedValue([]);
 fireEvent.click(dialog.querySelector('button:last-child')!);await waitFor(()=>expect(api.deleteObservation).toHaveBeenCalledWith('DEMO-note'));
});
it('periodic summary uses actual HTTP counts and patient descriptions instead of a static option card',async()=>{
 vi.mocked(api.reviewSummary).mockResolvedValue({period:'week',window_start:'2026-10-11T16:00:00Z',window_end:'2026-10-14T00:00:00Z',generated_at:'2026-10-14T00:00:00Z',timezone:'Asia/Singapore',medications:[],reported_taken:2,reported_not_taken:1,unsure:0,observations:[],questions:[],coverage_note:'No report is not a missed dose.'});
 render(<ReviewSummaryScreen period="week" regimens={[]}/>);await screen.findByText('No report is not a missed dose.');expect(api.reviewSummary).toHaveBeenCalledWith('week',undefined);
 expect(screen.getByText('2')).toBeTruthy();expect(screen.getByRole('button',{name:'Export summary'})).toBeTruthy();expect(screen.getByText(/does not mean no symptoms/)).toBeTruthy();
});
