// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {AssistantWorkflow} from './AssistantWorkflow';
import {api} from '../api/client';
import type {WorkflowView} from '../api/assistantWorkflows';
afterEach(()=>{cleanup();vi.restoreAllMocks();});
const id='00000000-0000-4000-8000-000000000099';
const view:WorkflowView={task_id:'DEMO-delete',revision:2,capability_id:'medication.draft.delete',state:'awaiting_confirmation',save_mode:'allowed',storage_state:'saved',prompt_key:'assistant.medication.review_delete',visible_fields:{kind:'draft',target_id:id,expected_version:1,target_name:'DEMO pending draft',records:[],source_tasks:[]},missing_fields:[],explanations:[],result_ref:{kind:'regimen',id,version:1},actions:[{kind:'existing_review',component_key:'existing_draft_delete',owned_ref:{kind:'regimen',id,version:1},expected_version:1}]};

it.each(['draft','source'] as const)('keeps %s deletion behind the independent patient confirmation and binds its actual API request',async kind=>{
 const remove=vi.spyOn(api,'deleteDraft').mockResolvedValue({deleted:true,medication_deleted:true,cleanup_pending:false});
 const reference={kind:kind==='draft'?'regimen' as const:'enrollment_task' as const,id,version:1};
 const selected={...view,visible_fields:{...view.visible_fields,kind},result_ref:reference,actions:[{kind:'existing_review' as const,component_key:'existing_draft_delete' as const,owned_ref:reference,expected_version:1}]};
 const submit=vi.fn();render(<AssistantWorkflow view={selected} busy={false} onEvent={submit}/>);
 fireEvent.click(screen.getByRole('button',{name:'Delete draft'}));
 expect(remove).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'Cancel'}));expect(remove).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'Delete draft'}));
 fireEvent.click(screen.getByRole('button',{name:'Confirm delete'}));
 await waitFor(()=>expect(submit).toHaveBeenCalledWith(expect.objectContaining({kind:'report_business_result',values:{}})));
 expect(remove).toHaveBeenCalledWith(kind,id,{task_id:'DEMO-delete',expected_revision:2});
});

it('keeps an ambiguous failed deletion pending and offers a status check without claiming the draft survived',async()=>{
 vi.spyOn(api,'deleteDraft').mockRejectedValue(new Error('DEMO deletion response lost'));
 const submit=vi.fn(),refresh=vi.fn();render(<AssistantWorkflow view={view} busy={false} onEvent={submit} onRefresh={refresh}/>);
 fireEvent.click(screen.getByRole('button',{name:'Delete draft'}));fireEvent.click(screen.getByRole('button',{name:'Confirm delete'}));
 await screen.findByText('DEMO deletion response lost');
 expect(submit).not.toHaveBeenCalled();
 const dialog=screen.getByRole('dialog',{name:'Delete this draft?'});
 fireEvent.click(within(dialog).getByRole('button',{name:'Check deletion result'}));
 expect(refresh).toHaveBeenCalledOnce();
 expect(screen.queryByText(/The draft was not deleted. It is still saved/)).toBeNull();
});

it('retries only outstanding photo cleanup from a verified deletion receipt',async()=>{
 const remove=vi.spyOn(api,'deleteDraft').mockResolvedValue({deleted:true,medication_deleted:true,cleanup_pending:false});
 const submit=vi.fn();render(<AssistantWorkflow view={{...view,visible_fields:{...view.visible_fields,deleted:true,cleanup_pending:true},prompt_key:'assistant.medication.delete_cleanup'}} busy={false} onEvent={submit}/>);
 expect(screen.queryByRole('button',{name:'Delete draft'})).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'Retry photo cleanup'}));
 await waitFor(()=>expect(remove).toHaveBeenCalledWith('draft',id,{task_id:'DEMO-delete',expected_revision:2}));
 expect(submit).toHaveBeenCalledWith(expect.objectContaining({kind:'report_business_result'}));
});

it('offers rechecking changed records and never shows a no-save delete confirmation',()=>{
 const submit=vi.fn();const rendered=render(<AssistantWorkflow view={{...view,state:'failed_recoverable',actions:[],prompt_key:'assistant.medication.deletion_changed'}} busy={false} onEvent={submit}/>);
 fireEvent.click(screen.getByRole('button',{name:'Recheck draft before deleting'}));
 expect(submit).toHaveBeenCalledWith(expect.objectContaining({kind:'provide_fields',values:{}}));
 rendered.rerender(<AssistantWorkflow view={{...view,save_mode:'ephemeral',storage_state:'ephemeral'}} busy={false} onEvent={submit}/>);
 expect(screen.queryByRole('button',{name:'Delete draft'})).toBeNull();
});

it('shows how many unfinished versions and source registrations will be removed before confirmation',()=>{
 render(<AssistantWorkflow view={{...view,visible_fields:{...view.visible_fields,affected_plan_count:2,affected_source_registration_count:1,medication_record_removed:true}}} busy={false} onEvent={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'Delete draft'}));
 expect(within(screen.getByRole('dialog')).getByText(/2 unfinished plan versions/)).toBeTruthy();
 expect(within(screen.getByRole('dialog')).getByText(/1 source registration/)).toBeTruthy();
});
