// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {AssistantEnrollmentFields} from './AssistantEnrollmentFields';
import type {WorkflowView} from '../api/assistantWorkflows';

afterEach(cleanup);
const view:WorkflowView={task_id:'DEMO-task',revision:3,capability_id:'medication.enroll',state:'collecting',save_mode:'allowed',storage_state:'saved',visible_fields:{method:'manual',medication_name:'DEMO product',dose_amount:1,dose_unit:'tablet',dose_basis:{strength_text:'200mg'},times_per_day:2,frequency_rule:{kind:'daily',local_times:[]}},missing_fields:['frequency_local_times'],prompt_key:'assistant.enrollment.provide_fields',actions:[],explanations:[],result_ref:null};

it('collects missing times while keeping product strength separate from the per-dose amount',async()=>{
 const submit=vi.fn().mockResolvedValue(undefined);
 render(<AssistantEnrollmentFields view={view} fieldNames={view.missing_fields} busy={false} onEvent={submit}/>);
 fireEvent.change(screen.getByLabelText('Dose time 1'),{target:{value:'08:00'}});
 fireEvent.click(screen.getByRole('button',{name:'Add another time'}));
 fireEvent.change(screen.getByLabelText('Dose time 2'),{target:{value:'20:00'}});
 fireEvent.click(screen.getByRole('button',{name:'Use these details'}));
 await waitFor(()=>expect(submit).toHaveBeenCalled());
 expect(submit.mock.calls[0]![0]).toMatchObject({kind:'provide_fields',expected_revision:3,values:{medication_name:'DEMO product',dose_amount:1,dose_unit:'tablet',dose_basis:{strength_text:'200mg',patient_checked:false},frequency_rule:{kind:'daily',local_times:['08:00','20:00']}}});
 expect(screen.queryByRole('button',{name:/activate|confirm/i})).toBeNull();
});

it('keeps edited values on an unavailable response and only clears them when explicitly undone',async()=>{
 const submit=vi.fn().mockRejectedValue(new Error('DEMO request lost'));
 render(<AssistantEnrollmentFields view={view} fieldNames={['medication_name']} busy={false} onEvent={submit}/>);
 fireEvent.change(screen.getByLabelText('Medication name'),{target:{value:'DEMO corrected product'}});
 fireEvent.click(screen.getByRole('button',{name:'Use these details'}));
 await screen.findByText('The details were not accepted. Your input is still here.');
 expect(screen.getByLabelText('Medication name')).toHaveProperty('value','DEMO corrected product');
 fireEvent.click(screen.getByRole('button',{name:'Undo unsent changes'}));
 expect(screen.getByLabelText('Medication name')).toHaveProperty('value','DEMO product');
});

it('records PRN guidance without adding any fixed times',async()=>{
 const submit=vi.fn().mockResolvedValue(undefined);
 render(<AssistantEnrollmentFields view={{...view,visible_fields:{method:'manual',medication_name:'DEMO PRN',dose_amount:1,dose_unit:'tablet'}}} fieldNames={['frequency_rule']} busy={false} onEvent={submit}/>);
 fireEvent.change(screen.getByLabelText('Schedule'),{target:{value:'prn'}});
 fireEvent.change(screen.getByLabelText('Recorded as-needed guidance'),{target:{value:'DEMO recorded condition'}});
 fireEvent.click(screen.getByRole('button',{name:'Use these details'}));
 await waitFor(()=>expect(submit).toHaveBeenCalled());
 expect(submit.mock.calls[0]![0].values).toMatchObject({is_prn:true,frequency_rule:null,food_instruction:'DEMO recorded condition'});
});

it('keeps a default first-dose time distinct from a time entered by the patient when editing another detail',async()=>{
 const submit=vi.fn().mockResolvedValue(undefined);
 const prepared={...view,visible_fields:{method:'manual',medication_name:'DEMO interval',dose_amount:1,dose_unit:'tablet',course_start_date:'2026-11-01',frequency_rule:{kind:'interval',every_hours:6,local_times:['08:00'],interval_anchor:{local_date:'2026-11-01',local_time:'08:00',time_source:'default_0800'}}}};
 render(<AssistantEnrollmentFields view={prepared} fieldNames={['dose_amount','frequency_rule']} busy={false} onEvent={submit}/>);
 expect(screen.getByLabelText('First dose time')).toHaveProperty('value','');
 fireEvent.change(screen.getByLabelText('Amount per dose'),{target:{value:'2'}});
 fireEvent.click(screen.getByRole('button',{name:'Use these details'}));
 await waitFor(()=>expect(submit).toHaveBeenCalled());
 expect(submit.mock.calls[0]![0].values.frequency_rule).toMatchObject({kind:'interval',local_times:[]});
});
