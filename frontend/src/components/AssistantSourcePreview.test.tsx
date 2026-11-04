// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import type {SourcePreview} from '../api/client';
import {workflowApi,type WorkflowView} from '../api/assistantWorkflows';
import {AssistantWorkflow} from './AssistantWorkflow';
vi.mock('./PhotoAcquisition',()=>({PhotoAcquisition:({file,onFile}:{file:File|null;onFile:(file:File|null)=>void})=><><input type="file" aria-label="DEMO preview photo" onChange={event=>onFile(event.target.files?.[0]??null)}/>{file?<p>{file.name}</p>:null}</>}));
vi.mock('../api/assistantWorkflows',async load=>{const module=await load<typeof import('../api/assistantWorkflows')>();return {...module,workflowApi:{...module.workflowApi,previewSource:vi.fn(),uploadPreviewOriginal:vi.fn()}};});
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.clearAllMocks();});
const source='00000000-0000-4000-8000-000000000100';
const base:WorkflowView={task_id:'DEMO-preview-task',revision:1,capability_id:'source.preview',state:'collecting',save_mode:'allowed',storage_state:'saved',prompt_key:'assistant.source_preview.collect',input_fields:{source_kind:'pharmacy_label'},visible_fields:{},missing_fields:['source_image'],actions:[{kind:'choice',action_id:'preview.source_kind',options:[{value:'pharmacy_label',label_key:'assistant.preview.label'},{value:'package',label_key:'assistant.preview.package'},{value:'prescription',label_key:'assistant.preview.prescription'}]}],explanations:[],result_ref:null};
const saved:WorkflowView={...base,revision:2,state:'ready_for_review',input_fields:{source_kind:'pharmacy_label',source_attachment_id:source},missing_fields:[]};
const file=new File(['DEMO original label'],'DEMO.png',{type:'image/png'});
const preview:SourcePreview={source_document_id:source,source_kind:'pharmacy_label',provider:'DEMO',extraction_model:'DEMO replay',review_required:true,note:'DEMO only',candidates:[{product:{name:'DEMO source medicine',strength:'DEMO 1 mg',source_lines:['DEMO source line at 13:45']},regimen_evidence:{directions:{value:'DEMO printed words only',line:'DEMO source line at 13:45'},dose_amount:null,frequency:null,administration_times:null,duration:null},review_status:'extracted',can_activate_regimen:false}]};
const success={outcome:'success',preview,reason:null} as const;
async function pick(){fireEvent.change(await screen.findByLabelText('DEMO preview photo'),{target:{files:[file]}});}

it('retains a no-save File across explicit saving without extracting it on select or save',async()=>{
 const send=vi.fn().mockResolvedValue({...base,revision:2}),mounted=render(<AssistantWorkflow view={{...base,save_mode:'ephemeral',storage_state:'ephemeral'}} busy={false} onEvent={send} onView={vi.fn()}/>);await pick();
 fireEvent.click(await screen.findByRole('button',{name:'Save source preview draft'}));await waitFor(()=>expect(send).toHaveBeenCalledWith(expect.objectContaining({kind:'allow_save'})));
 mounted.rerender(<AssistantWorkflow view={{...base,revision:2}} busy={false} onEvent={send} onView={vi.fn()}/>);expect(screen.getByText(file.name)).toBeTruthy();expect(workflowApi.previewSource).not.toHaveBeenCalled();expect(workflowApi.uploadPreviewOriginal).not.toHaveBeenCalled();
});

it('retains the File after an original storage error',async()=>{
 vi.mocked(workflowApi.uploadPreviewOriginal).mockRejectedValue(new Error('DEMO storage unavailable'));
 render(<AssistantWorkflow view={base} busy={false} onEvent={vi.fn()} onView={vi.fn()}/>);await pick();fireEvent.click(await screen.findByRole('button',{name:'Save preview original'}));
 expect(await screen.findByRole('alert')).toBeTruthy();expect(screen.getByText(file.name)).toBeTruthy();expect(workflowApi.previewSource).not.toHaveBeenCalled();
});

it('requires explicit consent, reads the resumed original and shows evidence without a plan form or implied save',async()=>{
 vi.mocked(workflowApi.previewSource).mockResolvedValue(success);const blob=vi.spyOn(workflowApi,'originalBlob').mockResolvedValue(new Blob(['DEMO raw label'],{type:'image/png'}));
 render(<AssistantWorkflow view={saved} busy={false} onEvent={vi.fn()} onView={vi.fn()}/>);const read=await screen.findByRole('button',{name:'Preview source'});expect(read).toHaveProperty('disabled',true);expect(blob).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('checkbox'));fireEvent.click(read);expect(await screen.findByRole('heading',{name:'DEMO source medicine'})).toBeTruthy();expect(screen.getByText('DEMO printed words only')).toBeTruthy();
 expect(screen.getByText('Previewed clock words are unconfirmed; this preview does not save scheduled times.')).toBeTruthy();expect(screen.queryByText(/time fields below/)).toBeNull();
 expect(workflowApi.previewSource).toHaveBeenCalledWith(base.task_id,expect.any(File),2,true,undefined);expect(blob).toHaveBeenCalledWith(base.task_id,source);
 expect(screen.queryByRole('button',{name:/Activate|Save medication|Save source/i})).toBeNull();
});

it('discards a late preview after the task inputs change',async()=>{
 let resolve!:(value:typeof success)=>void;vi.mocked(workflowApi.previewSource).mockReturnValue(new Promise(done=>{resolve=done;}));
 const view={...base,save_mode:'ephemeral' as const,storage_state:'ephemeral' as const};const mounted=render(<AssistantWorkflow view={view} busy={false} onEvent={vi.fn()} onView={vi.fn()}/>);await pick();fireEvent.click(screen.getByRole('checkbox'));fireEvent.click(screen.getByRole('button',{name:'Preview source'}));await waitFor(()=>expect(workflowApi.previewSource).toHaveBeenCalled());
 mounted.rerender(<AssistantWorkflow view={{...view,revision:2,input_fields:{source_kind:'package'}}} busy={false} onEvent={vi.fn()} onView={vi.fn()}/>);resolve(success);await waitFor(()=>expect(screen.getByRole('button',{name:'Preview source'})).toHaveProperty('disabled',true));expect(screen.queryByText('DEMO source medicine')).toBeNull();expect(screen.getByText(file.name)).toBeTruthy();
});

it('distinguishes service unavailability from a successful empty extraction without retrying automatically',async()=>{
 vi.mocked(workflowApi.previewSource).mockResolvedValueOnce({outcome:'unavailable',preview:null,reason:'service_unavailable'}).mockResolvedValueOnce({...success,preview:{...preview,candidates:[]}});
 render(<AssistantWorkflow view={{...base,save_mode:'ephemeral',storage_state:'ephemeral'}} busy={false} onEvent={vi.fn()} onView={vi.fn()}/>);await pick();fireEvent.click(screen.getByRole('checkbox'));fireEvent.click(screen.getByRole('button',{name:'Preview source'}));
 expect(await screen.findByText('Source reading is unavailable. Your original is retained; no extraction was confirmed.')).toBeTruthy();expect(workflowApi.previewSource).toHaveBeenCalledTimes(1);
 fireEvent.click(screen.getByRole('button',{name:'Preview source'}));expect(await screen.findByText('No medication information was read. Check the original label or enter verified details manually.')).toBeTruthy();
});

it('uses a fresh original key after saving is revoked and enabled again',async()=>{
 vi.mocked(workflowApi.uploadPreviewOriginal).mockResolvedValue({workflow:saved,attachment:{id:source,task_id:base.task_id,original_checksum:'a'.repeat(64),content_type:'image/png',byte_size:20,state:'saved',extraction_status:'not_requested',reason:null,cleanup_pending:false}});
 const mounted=render(<AssistantWorkflow view={base} busy={false} onEvent={vi.fn()} onView={vi.fn()}/>);await pick();fireEvent.click(await screen.findByRole('button',{name:'Save preview original'}));await waitFor(()=>expect(workflowApi.uploadPreviewOriginal).toHaveBeenCalledTimes(1));await waitFor(()=>expect(screen.getByRole('button',{name:'Save preview original'})).toHaveProperty('disabled',false));
 mounted.rerender(<AssistantWorkflow view={{...base,revision:3,save_mode:'ephemeral',storage_state:'ephemeral'}} busy={false} onEvent={vi.fn()} onView={vi.fn()}/>);mounted.rerender(<AssistantWorkflow view={{...base,revision:4}} busy={false} onEvent={vi.fn()} onView={vi.fn()}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Save preview original'}));await waitFor(()=>expect(workflowApi.uploadPreviewOriginal).toHaveBeenCalledTimes(2));const calls=vi.mocked(workflowApi.uploadPreviewOriginal).mock.calls;expect(calls[0]![1]).not.toBe(calls[1]![1]);
});

it('changes only the typed offered source kind without processing',async()=>{
 const send=vi.fn().mockResolvedValue({...base,revision:2,input_fields:{source_kind:'package'}});render(<AssistantWorkflow view={base} busy={false} onEvent={send} onView={vi.fn()}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Medicine package'}));await waitFor(()=>expect(send).toHaveBeenCalledWith(expect.objectContaining({kind:'provide_fields',values:{source_kind:'package'}})));expect(workflowApi.previewSource).not.toHaveBeenCalled();
});
