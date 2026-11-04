// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {AssistantWorkflowOriginals} from './AssistantWorkflowOriginals';
import {workflowApi,type WorkflowView,type OriginalView} from '../api/assistantWorkflows';

vi.mock('../api/assistantWorkflows',()=>({workflowApi:{originals:vi.fn(),originalBlob:vi.fn(),view:vi.fn(),preview:vi.fn(),previewOriginal:vi.fn(),retryOriginal:vi.fn(),recoverOriginal:vi.fn(),retryCleanup:vi.fn()}}));
afterEach(()=>{cleanup();vi.resetAllMocks();});
const task:WorkflowView={task_id:'DEMO-task',revision:2,capability_id:'medication.enroll',state:'failed_recoverable',save_mode:'allowed',storage_state:'saved',prompt_key:'assistant.enrollment.extraction_failed',visible_fields:{method:'photo'},missing_fields:['medication_name'],actions:[],explanations:[],result_ref:null};
const original:OriginalView={id:'DEMO-original',task_id:task.task_id,original_checksum:'DEMO-hash',content_type:'image/png',byte_size:20,state:'saved',extraction_status:'failed',reason:'provider_unavailable',cleanup_pending:false};
const props={view:task,files:[],busy:false,consent:false,onConsent:vi.fn(),onView:vi.fn()};

it('restores an authenticated original and recognizes it only after separate consent',async()=>{
 vi.mocked(workflowApi.originals).mockResolvedValue([original]);vi.mocked(workflowApi.view).mockResolvedValue(task);
 vi.mocked(workflowApi.previewOriginal).mockResolvedValue({attachment:original,workflow:{...task,revision:3}});
 const create=vi.fn(()=> 'blob:DEMO-private');const revoke=vi.fn();vi.stubGlobal('URL',Object.assign(URL,{createObjectURL:create,revokeObjectURL:revoke}));
 vi.mocked(workflowApi.originalBlob).mockResolvedValue(new Blob(['DEMO bytes'],{type:'image/png'}));
 const rendered=render(<AssistantWorkflowOriginals {...props}/>);
 const retry=await screen.findByRole('button',{name:'Retry recognition'});expect(retry).toHaveProperty('disabled',true);
 fireEvent.click(screen.getByRole('button',{name:'View original 1'}));
 expect((await screen.findByAltText('Saved original 1')).getAttribute('src')).toBe('blob:DEMO-private');
 rendered.rerender(<AssistantWorkflowOriginals {...props} consent/>);
 fireEvent.click(screen.getByRole('button',{name:'Retry recognition'}));
 await waitFor(()=>expect(props.onView).toHaveBeenCalledWith(expect.objectContaining({revision:3})));
 await screen.findByText('Photo recognition is unavailable. The original is still saved.');
 expect(workflowApi.previewOriginal).toHaveBeenCalledWith(task.task_id,original.id,2,true,expect.any(String));
 rendered.unmount();expect(revoke).toHaveBeenCalledWith('blob:DEMO-private');
});

it('keeps page photos visible in no-save mode without asking for saved originals',async()=>{
 render(<AssistantWorkflowOriginals {...props} view={{...task,save_mode:'ephemeral',storage_state:'ephemeral'}} files={[{upload_id:'DEMO-upload',file:new File(['DEMO bytes'],'DEMO-private.png'),source_kind:'package'}]}/>);
 expect(screen.getByText('DEMO-private.png')).toBeTruthy();expect(screen.getByText('Page copy only. Refreshing loses this photo.')).toBeTruthy();
 expect(workflowApi.originals).not.toHaveBeenCalled();
});

it('drops a late original response when its task is closed',async()=>{
 let resolve!:(blob:Blob)=>void;
 vi.mocked(workflowApi.originals).mockResolvedValue([original]);vi.mocked(workflowApi.originalBlob).mockReturnValue(new Promise(done=>{resolve=done;}));
 const create=vi.fn();vi.stubGlobal('URL',Object.assign(URL,{createObjectURL:create,revokeObjectURL:vi.fn()}));
 const rendered=render(<AssistantWorkflowOriginals {...props}/>);
 fireEvent.click(await screen.findByRole('button',{name:'View original 1'}));rendered.unmount();
 await act(async()=>resolve(new Blob(['DEMO private bytes'])));expect(create).not.toHaveBeenCalled();
});

it('rechecks pending cleanup without erasing page-only fields',async()=>{
 const noSave={...task,save_mode:'ephemeral' as const,storage_state:'cleanup_pending' as const,cleanup_pending:true};
 vi.mocked(workflowApi.retryCleanup).mockResolvedValue([]);vi.mocked(workflowApi.view).mockResolvedValue({...noSave,visible_fields:{}});
 vi.mocked(workflowApi.preview).mockResolvedValue({...noSave,storage_state:'ephemeral',cleanup_pending:false});
 render(<AssistantWorkflowOriginals {...props} view={noSave}/>);
 fireEvent.click(screen.getByRole('button',{name:'Retry original cleanup'}));
 await screen.findByText('Cleanup status checked.');
 expect(workflowApi.preview).toHaveBeenCalledWith(task.task_id,{capability_id:task.capability_id,fields:{method:'photo'}});
 expect(props.onView).toHaveBeenCalledWith(expect.objectContaining({visible_fields:{method:'photo'}}));
});

it('checks an ambiguous upload result using metadata without resending the photo',async()=>{
 vi.mocked(workflowApi.originals).mockResolvedValueOnce([]).mockResolvedValue([{...original,state:'reserved',extraction_status:'pending',reason:null}]);
 vi.mocked(workflowApi.view).mockResolvedValue({...task,state:'outcome_unknown'});
 render(<AssistantWorkflowOriginals {...props} files={[{upload_id:'DEMO-upload',file:new File(['DEMO bytes'],'DEMO-pending.png'),source_kind:'package'}]}/>);
 await waitFor(()=>expect(screen.getByRole('button',{name:'Check original status'})).not.toHaveProperty('disabled',true));
 fireEvent.click(screen.getByRole('button',{name:'Check original status'}));
 await screen.findByRole('button',{name:'Check original save result'});
 expect(workflowApi.previewOriginal).not.toHaveBeenCalled();expect(workflowApi.recoverOriginal).not.toHaveBeenCalled();
});

it('recovers saved-photo recognition metadata without consent or another provider call',async()=>{
 vi.mocked(workflowApi.originals).mockResolvedValue([{...original,extraction_status:'pending',reason:null}]);
 vi.mocked(workflowApi.view).mockResolvedValue({...task,state:'outcome_unknown'});
 vi.mocked(workflowApi.recoverOriginal).mockResolvedValue({attachment:{...original,extraction_status:'interrupted',reason:'extraction_interrupted'},workflow:{...task,revision:4}});
 render(<AssistantWorkflowOriginals {...props} view={{...task,state:'outcome_unknown'}}/>);
 const recover=await screen.findByRole('button',{name:'Check recognition result'});expect(recover).not.toHaveProperty('disabled',true);fireEvent.click(recover);
 await screen.findByText('The previous recognition result is unavailable. You can explicitly retry recognition.');
 expect(workflowApi.previewOriginal).not.toHaveBeenCalled();expect(workflowApi.recoverOriginal).toHaveBeenCalledWith(task.task_id,original.id,2);
});

it('lets a refreshed page reselect the original bytes for an explicit saving retry',async()=>{
 vi.mocked(workflowApi.originals).mockResolvedValue([{...original,state:'reserved'}]);vi.mocked(workflowApi.view).mockResolvedValue({...task,state:'outcome_unknown'});
 vi.mocked(workflowApi.retryOriginal).mockResolvedValue({attachment:original,workflow:{...task,revision:4}});
 render(<AssistantWorkflowOriginals {...props} view={{...task,state:'outcome_unknown'}}/>);
 const file=new File(['DEMO original bytes'],'DEMO-original.png',{type:'image/png'});
 fireEvent.change(await screen.findByLabelText('Original file 1'),{target:{files:[file]}});
 fireEvent.click(screen.getByRole('button',{name:'Retry saving original 1'}));
 await waitFor(()=>expect(props.onView).toHaveBeenCalledWith(expect.objectContaining({revision:4})));
 expect(workflowApi.retryOriginal).toHaveBeenCalledWith(task.task_id,original.id,file,2,false);
});
