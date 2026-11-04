// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {LanguageProvider} from '../language';
import type {WorkflowView} from '../api/assistantWorkflows';
import {AssistantWorkflow} from './AssistantWorkflow';

afterEach(cleanup);
it('shows reminder options without unrelated PDF instructions',async()=>{
 const reminder:WorkflowView={task_id:'DEMO-reminder',revision:0,capability_id:'notification.status',state:'ready_for_review',save_mode:'ephemeral',storage_state:'ephemeral',prompt_key:'assistant.reminder.device',visible_fields:{},missing_fields:[],explanations:[],result_ref:null,actions:[]};
 render(<LanguageProvider><AssistantWorkflow view={reminder} busy={false} onEvent={vi.fn()}/></LanguageProvider>);
 await screen.findByRole('button',{name:'Check device notification status'});
 await waitFor(()=>expect(screen.queryByText(/This PDF is stored as a document/)).toBeNull());
 expect(screen.getByRole('button',{name:'Save this query'})).toBeTruthy();
});
const view:WorkflowView={task_id:'DEMO-task',revision:3,capability_id:'medication.enroll',state:'choose_method',save_mode:'allowed',storage_state:'saved',prompt_key:'assistant.enrollment.choose_method',visible_fields:{},missing_fields:['method'],explanations:[],result_ref:null,actions:[{kind:'choice',action_id:'enrollment.method',options:[{value:'manual',label_key:'assistant.enrollment.manual'},{value:'photo',label_key:'assistant.enrollment.photo'}]}]};

it('prepares the original independent review only after saved collection is ready',()=>{
 const event=vi.fn();const ready={...view,state:'ready_for_review' as const,actions:[],missing_fields:[],visible_fields:{method:'manual'}};
 const {rerender}=render(<LanguageProvider><AssistantWorkflow view={ready} busy={false} onEvent={event}/></LanguageProvider>);
 fireEvent.click(screen.getByRole('button',{name:'Review this medication'}));
 expect(event).toHaveBeenCalledWith(expect.objectContaining({kind:'prepare_confirmation',expected_revision:3,values:{}}));
 rerender(<LanguageProvider><AssistantWorkflow view={{...ready,save_mode:'ephemeral',storage_state:'ephemeral'}} busy={false} onEvent={event}/></LanguageProvider>);
 expect(screen.queryByRole('button',{name:'Review this medication'})).toBeNull();
});

it('renders choices inside the conversation and binds the event to the visible revision',()=>{
 const event=vi.fn();
 render(<LanguageProvider><AssistantWorkflow view={view} busy={false} onEvent={event}/></LanguageProvider>);
 fireEvent.click(screen.getByRole('button',{name:'Enter manually'}));
 expect(event).toHaveBeenCalledWith(expect.objectContaining({expected_revision:3,kind:'choose_method',values:{method:'manual'}}));
 expect(screen.getByRole('button',{name:'Use a photo'})).toBeTruthy();
 expect(screen.queryByText(/到药物页面选择/)).toBeNull();
});

it('keeps preview and save permission separate and never invents an activation button',()=>{
 const event=vi.fn();
 render(<LanguageProvider><AssistantWorkflow view={{...view,save_mode:'ephemeral',storage_state:'ephemeral'}} busy={false} onEvent={event}/></LanguageProvider>);
 expect(screen.getByText('Details stay on this page. Refreshing loses them.')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'Save this medication and continue review'}));
 expect(event).toHaveBeenCalledWith(expect.objectContaining({kind:'allow_save',expected_revision:3}));
 expect(screen.queryByRole('button',{name:/activate|confirmed/i})).toBeNull();
});

it('keeps pending cleanup visible alongside a newly saved task',()=>{
 render(<LanguageProvider><AssistantWorkflow view={{...view,cleanup_pending:true}} busy={false} onEvent={vi.fn()}/></LanguageProvider>);
 expect(screen.getByText('Some originals are still waiting for cleanup.')).toBeTruthy();
});

it('explains that protected originals remain with their existing records',()=>{
 render(<LanguageProvider><AssistantWorkflow view={{...view,save_mode:'ephemeral',storage_state:'ephemeral',protected_originals:true,prompt_key:'assistant.workflow.source_retained'}} busy={false} onEvent={vi.fn()}/></LanguageProvider>);
 expect(screen.getByText('Referenced originals were retained.')).toBeTruthy();
});

it('offers metadata-only recovery of an interrupted no-save task',()=>{
 const event=vi.fn();
 render(<LanguageProvider><AssistantWorkflow view={{...view,save_mode:'ephemeral',storage_state:'ephemeral',state:'outcome_unknown'}} busy={false} onEvent={event}/></LanguageProvider>);
 fireEvent.click(screen.getByRole('button',{name:'Recover interrupted task'}));
 expect(event).toHaveBeenCalledWith(expect.objectContaining({kind:'retry',expected_revision:3,values:{}}));
});

it('shows the actual matching product label and sends the explicit existing-record selection',()=>{
 const event=vi.fn();const id='00000000-0000-4000-8000-000000000012';
 render(<LanguageProvider><AssistantWorkflow view={{...view,actions:[{kind:'choice',action_id:'enrollment.duplicate',options:[{value:id,label_key:'assistant.enrollment.reuse_existing',label_text:'DEMO Product 200mg'}]}]}} busy={false} onEvent={event}/></LanguageProvider>);
 fireEvent.click(screen.getByRole('button',{name:'Use existing record: DEMO Product 200mg'}));
 expect(event).toHaveBeenCalledWith(expect.objectContaining({kind:'select_candidate',values:{existing_medication_id:id}}));
});

it('renders the typed collection form in the current task',()=>{
 const event=vi.fn();
 render(<LanguageProvider><AssistantWorkflow view={{...view,visible_fields:{method:'manual'},actions:[{kind:'fields',schema_id:'medication.enroll:v1',field_names:['medication_name','dose_amount','dose_unit','frequency_rule']}]}} busy={false} onEvent={event}/></LanguageProvider>);
 fireEvent.change(screen.getByLabelText('Medication name'),{target:{value:'DEMO entered'}});
 fireEvent.click(screen.getByRole('button',{name:'Use these details'}));
 expect(event).toHaveBeenCalledWith(expect.objectContaining({kind:'provide_fields',values:expect.objectContaining({medication_name:'DEMO entered'})}));
});
