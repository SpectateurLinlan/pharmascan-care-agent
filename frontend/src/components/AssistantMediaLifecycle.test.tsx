// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {api} from '../api/client';
import type {WorkflowView} from '../api/assistantWorkflows';
import {workflowChoice} from '../assistantWorkflowActions';
import {AssistantWorkflow} from './AssistantWorkflow';

afterEach(()=>{cleanup();vi.restoreAllMocks();});
const id='00000000-0000-4000-8000-000000000099';
const reference={kind:'media_review' as const,id,version:1};
const target={id,version:1,media_kind:'pdf',display_title:'DEMO file',category:'other',description:'DEMO old note',original_filename:'DEMO_original.pdf'};
const payload={expected_version:1,title:'DEMO revised',category:'other',description:'DEMO reviewed note'};
const base:WorkflowView={task_id:'DEMO-media-change',revision:2,capability_id:'library.pdf.edit',state:'awaiting_confirmation',save_mode:'allowed',storage_state:'saved',prompt_key:'assistant.media.patient_review',visible_fields:{media_review:{target_id:id,target,payload,medication_name:'DEMO medicine',cleanup_retry:false}},input_fields:{medication_id:id,file_id:id,...payload},missing_fields:[],actions:[{kind:'existing_review',component_key:'existing_media_management',owned_ref:reference,expected_version:1}],explanations:[],result_ref:reference};

const cases=[
 ['gallery.photo.edit','manageReference','Save changes'],['gallery.photo.remove','manageReference','Remove photo'],
 ['gallery.photo.delete','manageReference','Delete photo'],['gallery.photo.retire','retireReference','Stop comparison'],
 ['library.pdf.edit','updateLibraryPdf','Save changes'],['library.pdf.delete','deleteLibraryPdf','Delete file'],
] as const;

it('offers independent cleanup recovery for a typed tombstone without claiming physical success',async()=>{
 const ref={kind:'file' as const,id,version:2};
 const view:WorkflowView={...base,capability_id:'library.pdf.delete',revision:3,state:'outcome_unknown',storage_state:'cleanup_pending',result_ref:ref,
  visible_fields:{media_review:{target_id:id,target:{...target,version:2,deleted:true,cleanup_pending:true},payload:{},cleanup_retry:true}},
  actions:[{kind:'existing_review',component_key:'existing_media_management',owned_ref:ref,expected_version:2}]};
 const write=vi.spyOn(api,'deleteLibraryPdf').mockResolvedValue({deleted:true}),send=vi.fn().mockResolvedValue({...view,revision:4,state:'completed'});
 render(<AssistantWorkflow view={view} busy={false} onEvent={send}/>);
 expect(write).not.toHaveBeenCalled();
 fireEvent.click(await screen.findByRole('button',{name:'Review file action'}));
 expect(screen.getByRole('dialog').textContent).toContain('remaining private-file cleanup');
 fireEvent.click(screen.getByRole('button',{name:'Delete file'}));
 await waitFor(()=>expect(write).toHaveBeenCalledWith(id,{task_id:view.task_id,expected_revision:3}));
});

it('does not describe an unavailable historical read as an actual checked result',async()=>{
 render(<AssistantWorkflow view={{...base,state:'completed',result_ref:{kind:'file',id,version:2},visible_fields:{actual_result_available:false}}} busy={false} onEvent={vi.fn()}/>);
 await waitFor(()=>expect(screen.queryByText('The actual file result was checked.')).toBeNull());
 expect(await screen.findByText('This action was saved earlier. Its current file details cannot be checked right now.')).toBeTruthy();
});

it.each(cases)('independently confirms %s through its native API without a mount or preparation write',async(capability,method,label)=>{
 const write=vi.spyOn(api,method).mockResolvedValue({} as never),send=vi.fn().mockResolvedValue({...base,revision:3,state:'completed'});
 const photo=capability.startsWith('gallery.');
 const proposed=photo&&!capability.endsWith('retire')?{action:capability.split('.').at(-1)!,expected_version:1,image_kind:capability.endsWith('edit')?'blister':null,source_description:capability.endsWith('edit')?'DEMO revised photo':null,confirmed:true}:capability==='library.pdf.edit'?payload:{};
 const view={...base,capability_id:capability,visible_fields:{media_review:{target_id:id,target:photo?{...target,media_kind:'photo',source_description:'DEMO package',image_kind:'package'}:target,payload:proposed,medication_name:'DEMO medicine',cleanup_retry:false}}};
 render(<AssistantWorkflow view={view} busy={false} onEvent={send}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Review file action'}));expect(write).not.toHaveBeenCalled();
 const sheet=screen.getByRole('dialog');expect(sheet.textContent).toContain('DEMO medicine');expect(sheet.textContent).toContain(photo?'DEMO package':'DEMO file');
 fireEvent.click(screen.getByRole('button',{name:label}));
 await waitFor(()=>expect(write).toHaveBeenCalledTimes(1));
 const binding={task_id:base.task_id,expected_revision:2};
 expect(write).toHaveBeenCalledWith(...(method==='deleteLibraryPdf'||method==='retireReference'?[id,binding]:[id,proposed,binding]));
 await waitFor(()=>expect(send).toHaveBeenCalledWith(expect.objectContaining({kind:'report_business_result',values:{}})));
});

it('cancels without writing and hides independent review after saving is revoked',async()=>{
 const write=vi.spyOn(api,'updateLibraryPdf'),mounted=render(<AssistantWorkflow view={base} busy={false} onEvent={vi.fn()}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Review file action'}));fireEvent.click(screen.getByRole('button',{name:'Cancel'}));
 expect(write).not.toHaveBeenCalled();
 mounted.rerender(<AssistantWorkflow view={{...base,revision:3,save_mode:'ephemeral'}} busy={false} onEvent={vi.fn()}/>);
 expect(screen.queryByRole('button',{name:'Review file action'})).toBeNull();
});

it('retains a failed review and checks the real result before permitting another write',async()=>{
 const write=vi.spyOn(api,'updateLibraryPdf').mockRejectedValue(new Error('DEMO lost response'));
 const send=vi.fn().mockResolvedValue({...base,revision:3,state:'completed'});
 render(<AssistantWorkflow view={base} busy={false} onEvent={send}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Review file action'}));fireEvent.click(screen.getByRole('button',{name:'Save changes'}));
 expect(await screen.findByRole('alert')).toBeTruthy();expect(screen.getByRole('dialog').textContent).toContain('DEMO reviewed note');
 expect(screen.getByRole('button',{name:'Save changes'})).toHaveProperty('disabled',true);
 fireEvent.click(screen.getByRole('button',{name:'Check file result'}));
 await waitFor(()=>expect(send).toHaveBeenCalledWith(expect.objectContaining({kind:'report_business_result',values:{}})));
 expect(write).toHaveBeenCalledTimes(1);
});

it('collects existing native PDF fields and retains edits when applying a draft fails',async()=>{
 const send=vi.fn().mockRejectedValue(new Error('DEMO draft unavailable'));
 const view={...base,state:'collecting' as const,result_ref:null,actions:[],input_fields:{medication_id:id,file_id:id,expected_version:1},visible_fields:{media_target:target,medication_name:'DEMO medicine'},missing_fields:['title','category','description']};
 render(<AssistantWorkflow view={view} busy={false} onEvent={send}/>);
 const title=await screen.findByRole('textbox',{name:'File title'});expect(title).toHaveProperty('value','DEMO file');
 fireEvent.change(title,{target:{value:'DEMO entered title'}});fireEvent.click(screen.getByRole('button',{name:'Apply file details'}));
 expect(await screen.findByRole('alert')).toBeTruthy();expect(title).toHaveProperty('value','DEMO entered title');
 expect(send).toHaveBeenCalledWith(expect.objectContaining({kind:'provide_fields',values:{title:'DEMO entered title',category:'other',description:'DEMO old note'}}));
});

it('dispatches a paired version only for a currently offered lifecycle target',()=>{
 const action={kind:'choice' as const,action_id:'media.pdf_target',options:[{value:`${id}:7`,label_key:'assistant.media.select',label_text:'DEMO target'}]};
 expect(workflowChoice(base,action,`${id}:7`)).toMatchObject({kind:'provide_fields',values:{file_id:id,expected_version:7,page:0}});
 expect(()=>workflowChoice({...base,capability_id:'gallery.photo.delete'},action,`${id}:7`)).toThrow();
});

it('shows the exact native metadata version in the independent review',async()=>{
 render(<AssistantWorkflow view={base} busy={false} onEvent={vi.fn()}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Review file action'}));
 expect(screen.getByRole('dialog').textContent).toContain('File version: 1');
 expect(screen.getByRole('dialog').textContent).toContain('Other document');
});

it('describes an earlier file action without claiming the file still has the saved version',async()=>{
 render(<AssistantWorkflow view={{...base,state:'completed',prompt_key:'assistant.media.historical',result_ref:{kind:'file',id,version:2},visible_fields:{historical_result:true}}} busy={false} onEvent={vi.fn()}/>);
 expect(await screen.findByText('This earlier action was recorded. The file has changed since; check its current record.')).toBeTruthy();
 expect(screen.queryByText('The actual file result was checked.')).toBeNull();
});

it('keeps offered targets visible and reports a failed selection request',async()=>{
 const action={kind:'choice' as const,action_id:'media.medication',options:[{value:id,label_key:'assistant.media.select',label_text:'DEMO selected medicine'}]};
 render(<AssistantWorkflow view={{...base,state:'collecting',input_fields:{},result_ref:null,visible_fields:{},missing_fields:['medication_id'],actions:[action]}} busy={false} onEvent={vi.fn().mockRejectedValue(new Error('DEMO selection unavailable'))}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Select: DEMO selected medicine'}));
 expect(await screen.findByRole('alert')).toBeTruthy();expect(screen.getByRole('button',{name:'Select: DEMO selected medicine'})).toBeTruthy();
});
