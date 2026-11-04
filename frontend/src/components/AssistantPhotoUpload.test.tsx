// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {api} from '../api/client';
import {workflowApi,type WorkflowView} from '../api/assistantWorkflows';
import {AssistantWorkflow} from './AssistantWorkflow';
import {AssistantWorkflowOriginals} from './AssistantWorkflowOriginals';
vi.mock('./PhotoAcquisition',()=>({PhotoAcquisition:({file,onFile}:{file:File|null;onFile:(file:File|null)=>void})=><><input type="file" aria-label="DEMO photo selection" onChange={event=>onFile(event.target.files?.[0]??null)}/>{file?<p>{file.name}</p>:null}</>}));
vi.mock('../api/assistantWorkflows',async load=>{const module=await load<typeof import('../api/assistantWorkflows')>();return {...module,workflowApi:{...module.workflowApi,uploadReferenceOriginal:vi.fn()}};});
afterEach(()=>{cleanup();vi.restoreAllMocks();});
const id='00000000-0000-4000-8000-000000000099';
const source='00000000-0000-4000-8000-000000000100';
const base:WorkflowView={task_id:'DEMO-reference-task',revision:1,capability_id:'gallery.photo.add',state:'collecting',save_mode:'allowed',storage_state:'saved',prompt_key:'assistant.photo.collect',input_fields:{medication_id:id,image_kind:'package',source_description:'DEMO package'},visible_fields:{medication_name:'DEMO medicine',originals:[]},missing_fields:['source_image'],actions:[],explanations:[],result_ref:null};
const saved={...base,revision:2,state:'ready_for_review' as const,input_fields:{...base.input_fields,source_attachment_id:source},visible_fields:{medication_name:'DEMO medicine',originals:[{id:source}]},missing_fields:[]};
const ref={kind:'media_review' as const,id,version:1};
const reviewed:WorkflowView={...saved,revision:3,state:'awaiting_confirmation',prompt_key:'assistant.photo.review',actions:[{kind:'existing_review',component_key:'existing_media_management',owned_ref:ref,expected_version:1}],result_ref:ref,visible_fields:{...saved.visible_fields,original_id:source,upload_attempted:false}};
const file=new File(['DEMO raw image'],'DEMO_original.png',{type:'image/png'});
async function pick(){fireEvent.change(await screen.findByLabelText('DEMO photo selection'),{target:{files:[file]}});}

it('can reopen independent review after an unchanged read proves registration is still pending',async()=>{
 vi.spyOn(workflowApi,'originalBlob').mockResolvedValue(file);
 const write=vi.spyOn(api,'addReference').mockRejectedValue(new Error('DEMO registration unavailable'));
 const send=vi.fn().mockResolvedValue(reviewed);
 render(<AssistantWorkflow view={reviewed} busy={false} onEvent={send} onView={vi.fn()}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Review gallery photo'}));fireEvent.click(screen.getByRole('checkbox'));
 fireEvent.click(screen.getByRole('button',{name:'Add photo to gallery'}));expect(await screen.findByRole('alert')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'Check photo result'}));
 await waitFor(()=>expect(screen.queryByRole('dialog')).toBeNull());
 fireEvent.click(screen.getByRole('button',{name:'Review gallery photo'}));
 expect(screen.getByRole('button',{name:'Add photo to gallery'})).toHaveProperty('disabled',false);
 expect(write).toHaveBeenCalledTimes(1);
});

it('keeps a page-only File across the explicit save transition without uploading or recognizing it',async()=>{
 const send=vi.fn().mockResolvedValue({...base,revision:2}),native=vi.spyOn(api,'addReference');
 const mounted=render(<AssistantWorkflow view={{...base,save_mode:'ephemeral',storage_state:'ephemeral'}} busy={false} onEvent={send} onView={vi.fn()}/>);
 await pick();fireEvent.click(await screen.findByRole('button',{name:'Save photo draft'}));
 await waitFor(()=>expect(send).toHaveBeenCalledWith(expect.objectContaining({kind:'allow_save',values:{}})));
 mounted.rerender(<AssistantWorkflow view={{...base,revision:2}} busy={false} onEvent={send} onView={vi.fn()}/>);
 expect(screen.getByText(file.name)).toBeTruthy();expect(workflowApi.uploadReferenceOriginal).not.toHaveBeenCalled();expect(native).not.toHaveBeenCalled();
});

it('preserves the File and typed details when saving the original fails',async()=>{
 vi.mocked(workflowApi.uploadReferenceOriginal).mockRejectedValue(new Error('DEMO original storage unavailable'));
 const native=vi.spyOn(api,'addReference');render(<AssistantWorkflow view={base} busy={false} onEvent={vi.fn()} onView={vi.fn()}/>);
 await pick();fireEvent.click(await screen.findByRole('button',{name:'Save original photo'}));
 expect(await screen.findByRole('alert')).toBeTruthy();expect(screen.getByText(file.name)).toBeTruthy();
 expect(screen.getByLabelText('Photo description and source')).toHaveProperty('value','DEMO package');expect(native).not.toHaveBeenCalled();
});

it('saves only the original before requesting independent patient review',async()=>{
 const onView=vi.fn(),native=vi.spyOn(api,'addReference');
 vi.mocked(workflowApi.uploadReferenceOriginal).mockResolvedValue({workflow:saved,attachment:{id:source,task_id:base.task_id,original_checksum:'a'.repeat(64),content_type:'image/png',byte_size:14,state:'saved',extraction_status:'not_requested',reason:null,cleanup_pending:false}});
 render(<AssistantWorkflow view={base} busy={false} onEvent={vi.fn()} onView={onView}/>);
 await pick();fireEvent.click(await screen.findByRole('button',{name:'Save original photo'}));
 await waitFor(()=>expect(onView).toHaveBeenCalledWith(saved));expect(native).not.toHaveBeenCalled();
 expect(workflowApi.uploadReferenceOriginal).toHaveBeenCalledWith(base.task_id,expect.any(String),file,1);
});

it('uses a fresh immutable upload ID after saving is revoked and explicitly enabled again',async()=>{
 vi.mocked(workflowApi.uploadReferenceOriginal).mockClear().mockResolvedValue({workflow:saved,attachment:{id:source,task_id:base.task_id,original_checksum:'a'.repeat(64),content_type:'image/png',byte_size:14,state:'saved',extraction_status:'not_requested',reason:null,cleanup_pending:false}});
 const mounted=render(<AssistantWorkflow view={base} busy={false} onEvent={vi.fn()} onView={vi.fn()}/>);
 await pick();fireEvent.click(await screen.findByRole('button',{name:'Save original photo'}));
 await waitFor(()=>expect(workflowApi.uploadReferenceOriginal).toHaveBeenCalledTimes(1));
 await waitFor(()=>expect(screen.getByRole('button',{name:'Apply photo details'})).toHaveProperty('disabled',false));
 mounted.rerender(<AssistantWorkflow view={{...base,revision:3,save_mode:'ephemeral',storage_state:'ephemeral'}} busy={false} onEvent={vi.fn()} onView={vi.fn()}/>);
 mounted.rerender(<AssistantWorkflow view={{...base,revision:4}} busy={false} onEvent={vi.fn()} onView={vi.fn()}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Save original photo'}));
 await waitFor(()=>expect(workflowApi.uploadReferenceOriginal).toHaveBeenCalledTimes(2));
 expect(vi.mocked(workflowApi.uploadReferenceOriginal).mock.calls[1]![1]).not.toBe(vi.mocked(workflowApi.uploadReferenceOriginal).mock.calls[0]![1]);
});

it('loads a saved original on resume and uploads only after separate consent and confirmation',async()=>{
 const native=vi.spyOn(api,'addReference').mockResolvedValue({photo:{id},duplicate:false} as never);
 const blob=vi.spyOn(workflowApi,'originalBlob').mockResolvedValue(new Blob(['DEMO raw image'],{type:'image/png'}));
 render(<AssistantWorkflow view={reviewed} busy={false} onEvent={vi.fn().mockResolvedValue({...reviewed,revision:4,state:'completed'})} onView={vi.fn()}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Review gallery photo'}));expect(native).not.toHaveBeenCalled();expect(blob).not.toHaveBeenCalled();
 expect(screen.getByRole('dialog').textContent).toContain('DEMO medicine');
 expect(screen.getByRole('button',{name:'Add photo to gallery'})).toHaveProperty('disabled',true);
 fireEvent.click(screen.getByRole('checkbox',{name:'I checked that this photo belongs with this medication and allow private photo processing.'}));
 fireEvent.click(screen.getByRole('button',{name:'Add photo to gallery'}));
 await waitFor(()=>expect(native).toHaveBeenCalledWith(id,expect.any(File),'package','DEMO package',true,false,{task_id:base.task_id,expected_revision:3}));
 expect(blob).toHaveBeenCalledWith(base.task_id,source);
});

it('retains the saved review after a lost native response and checks before retry',async()=>{
 vi.spyOn(api,'addReference').mockRejectedValue(new Error('DEMO lost response'));
 vi.spyOn(workflowApi,'originalBlob').mockResolvedValue(new Blob(['DEMO raw image'],{type:'image/png'}));
 const send=vi.fn().mockResolvedValue({...reviewed,revision:4,state:'completed'});
 render(<AssistantWorkflow view={reviewed} busy={false} onEvent={send} onView={vi.fn()}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Review gallery photo'}));fireEvent.click(screen.getByRole('checkbox'));
 fireEvent.click(screen.getByRole('button',{name:'Add photo to gallery'}));expect(await screen.findByRole('alert')).toBeTruthy();
 expect(screen.getByRole('button',{name:'Add photo to gallery'})).toHaveProperty('disabled',true);
 fireEvent.click(screen.getByRole('button',{name:'Check photo result'}));
 await waitFor(()=>expect(send).toHaveBeenCalledWith(expect.objectContaining({kind:'report_business_result',values:{}})));
});

it('does not offer source recognition for a store-only gallery original',async()=>{
 vi.spyOn(workflowApi,'originals').mockResolvedValue([{id:source,task_id:base.task_id,original_checksum:'a'.repeat(64),content_type:'image/png',byte_size:14,state:'saved',extraction_status:'not_requested',reason:null,cleanup_pending:false}]);
 render(<AssistantWorkflowOriginals view={saved} files={[]} busy={false} consent onConsent={vi.fn()} onView={vi.fn()}/>);
 expect(await screen.findByText('No medication recognition was requested for this gallery original.')).toBeTruthy();
 expect(screen.queryByRole('checkbox')).toBeNull();expect(screen.queryByRole('button',{name:/recogniz|recognition/i})).toBeNull();
});
