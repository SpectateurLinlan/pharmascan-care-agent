// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import type {WorkflowView} from '../api/assistantWorkflows';
import {AssistantWorkflow} from './AssistantWorkflow';
import {workflowChoice} from '../assistantWorkflowActions';

afterEach(()=>{cleanup();vi.restoreAllMocks();});
const id='00000000-0000-4000-8000-000000000099';
const fields={method:'manual',medication_name:'DEMO recovered medicine',dose_unit:'tablet',dose_amount:1,existing_medication_id:id,frequency_rule:{kind:'daily',local_times:['20:00']}};
const base:WorkflowView={task_id:'DEMO-recovery',revision:2,capability_id:'medication.draft.resume',state:'ready_for_review',save_mode:'allowed',storage_state:'saved',prompt_key:'assistant.enrollment.review_inputs',visible_fields:{...fields,recovery_inputs:fields},input_fields:{regimen_id:id,expected_version:3,page:0},missing_fields:[],actions:[],explanations:[],result_ref:null};

it('offers only the owned versioned draft and the separate original-task resume action',()=>{
 const submit=vi.fn(),resume=vi.fn();
 const picker={...base,actions:[{kind:'choice' as const,action_id:'medication.resume_target',options:[{value:`${id}:3`,label_key:'assistant.medication.select_draft',label_text:'DEMO recovered medicine · v3'}]}]};
 const {rerender}=render(<AssistantWorkflow view={picker} busy={false} onEvent={submit} onResumeDraft={resume}/>);
 fireEvent.click(screen.getByRole('button',{name:'Choose draft: DEMO recovered medicine · v3'}));
 expect(submit).toHaveBeenCalledWith(expect.objectContaining({values:{regimen_id:id,expected_version:3,page:0,details:null}}));
 expect(()=>workflowChoice(picker,picker.actions[0]!,`${id}:4`)).toThrow();
 const linked:WorkflowView={...base,state:'collecting',prompt_key:'assistant.medication.resume_original',actions:[{kind:'resume_task',owned_ref:{kind:'regimen',id,version:3},expected_version:3}]};
 rerender(<AssistantWorkflow view={linked} busy={false} onEvent={submit} onResumeDraft={resume}/>);
 fireEvent.click(screen.getByRole('button',{name:'Continue original enrollment'}));
 expect(resume).toHaveBeenCalledOnce();
 rerender(<AssistantWorkflow view={{...linked,save_mode:'ephemeral'}} busy={false} onEvent={submit} onResumeDraft={resume}/>);
 expect(screen.queryByRole('button',{name:'Continue original enrollment'})).toBeNull();
});

it('collects missing saved-draft details through the existing form without creating or confirming a plan',async()=>{
 const submit=vi.fn();
 render(<AssistantWorkflow view={{...base,state:'collecting',missing_fields:['dose_amount'],actions:[{kind:'fields',schema_id:'medication.enroll:v1',field_names:['dose_amount']}]}} busy={false} onEvent={submit}/>);
 fireEvent.change(screen.getByRole('spinbutton',{name:'Amount per dose'}),{target:{value:'2'}});
 fireEvent.click(screen.getByRole('button',{name:'Use these details'}));
 await waitFor(()=>expect(submit).toHaveBeenCalledWith(expect.objectContaining({kind:'provide_fields',expected_revision:2,values:{details:expect.objectContaining({method:'manual',medication_name:'DEMO recovered medicine',dose_amount:2,existing_medication_id:id})}})));
 expect(screen.queryByRole('button',{name:'Confirm and add'})).toBeNull();
});

it('prepares an unchanged existing draft only through the explicit review action',()=>{
 const submit=vi.fn();render(<AssistantWorkflow view={base} busy={false} onEvent={submit}/>);
 expect(submit).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'Review this medication'}));
 expect(submit).toHaveBeenCalledWith(expect.objectContaining({kind:'prepare_confirmation',values:{}}));
});
