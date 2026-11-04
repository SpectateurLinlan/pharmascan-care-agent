// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import {AssistantWorkflow} from './AssistantWorkflow';
import {workflowChoice} from '../assistantWorkflowActions';
import type {WorkflowView} from '../api/assistantWorkflows';

afterEach(cleanup);
const view:WorkflowView={task_id:'DEMO-task',revision:3,capability_id:'medication.source.review',state:'ready_for_review',save_mode:'allowed',storage_state:'saved',prompt_key:'assistant.source.ready',visible_fields:{source_task_id:'00000000-0000-4000-8000-000000000012',expected_version:2},missing_fields:[],result_ref:null,actions:[],explanations:[]};
it('prepares the shared source review in chat and never shows enrollment collection fields',()=>{
 const event=vi.fn();render(<AssistantWorkflow view={view} busy={false} onEvent={event}/>);
 fireEvent.click(screen.getByRole('button',{name:'Review medication source'}));
 expect(event).toHaveBeenCalledWith(expect.objectContaining({kind:'prepare_confirmation',expected_revision:3,values:{}}));
 expect(screen.queryByRole('button',{name:'Edit details'})).toBeNull();
});
it('renders offered source choices and dispatches only the typed source reference and version',()=>{
 const option={value:'00000000-0000-4000-8000-000000000012:2',label_key:'assistant.source.select',label_text:'DEMO source 200mg'};
 const action={kind:'choice' as const,action_id:'source.target',options:[option]};
 const event=vi.fn();render(<AssistantWorkflow view={{...view,state:'collecting',actions:[action]}} busy={false} onEvent={event}/>);
 fireEvent.click(screen.getByRole('button',{name:'Choose source: DEMO source 200mg'}));
 expect(event).toHaveBeenCalledWith(expect.objectContaining({kind:'provide_fields',values:{source_task_id:'00000000-0000-4000-8000-000000000012',expected_version:2,page:0}}));
 expect(()=>workflowChoice(view,action,'00000000-0000-4000-8000-000000000099:2')).toThrow();
});
it('returns an owned saved source to its original task without opening another confirmation',()=>{
 const resume=vi.fn();render(<AssistantWorkflow view={{...view,state:'collecting',prompt_key:'assistant.source.resume_original',actions:[{kind:'resume_task',owned_ref:{kind:'enrollment_task',id:'DEMO-source',version:2},expected_version:2}]}} busy={false} onEvent={vi.fn()} onResumeDraft={resume}/>);
 fireEvent.click(screen.getByRole('button',{name:'Continue original enrollment'}));expect(resume).toHaveBeenCalledOnce();
});
