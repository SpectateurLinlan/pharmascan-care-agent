// @vitest-environment jsdom
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {api} from '../api/client';
import type {WorkflowView} from '../api/assistantWorkflows';
import {workflowChoice} from '../assistantWorkflowActions';
import {AssistantWorkflow} from './AssistantWorkflow';

const id='00000000-0000-4000-8000-000000000099';
const photo={id,medication_id:id,image_kind:'package',source_description:'DEMO original package',eligibility:'associated',reviewed:true};
const file={id,medication_id:id,display_title:'DEMO label',original_filename:'DEMO_original.pdf',description:'DEMO stored PDF',category:'prescription',byte_size:42,version:1};
const base:WorkflowView={task_id:id,revision:2,capability_id:'gallery.list',state:'collecting',save_mode:'allowed',storage_state:'saved',prompt_key:'assistant.media.read',visible_fields:{records:[],page:0,page_count:1,total:0},input_fields:{page:0},missing_fields:[],actions:[],explanations:[],result_ref:null};
const create=vi.fn(()=> 'blob:DEMO-owned-original'),revoke=vi.fn();
beforeEach(()=>{create.mockClear();revoke.mockClear();vi.stubGlobal('URL',class extends URL {static createObjectURL=create;static revokeObjectURL=revoke;});});
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.unstubAllGlobals();});

it('renders actual gallery metadata and no mutation or automatic binary fetch',async()=>{
 const read=vi.spyOn(api,'referencePhoto');const pdf=vi.spyOn(api,'libraryPdf');
 render(<AssistantWorkflow view={{...base,visible_fields:{records:[{medication_id:id,name:'<script>DEMO package</script>',photo_count:2,status:'current',eligible_count:0}],page:0,page_count:1,total:1}}} busy={false} onEvent={vi.fn()}/>);
 expect(await screen.findByText('<script>DEMO package</script>')).toBeTruthy();
 expect(screen.getByText(/^Photos: 2 ·/)).toBeTruthy();expect(document.querySelector('script')).toBeNull();
 expect(read).not.toHaveBeenCalled();expect(pdf).not.toHaveBeenCalled();
 expect(screen.queryByRole('button',{name:/delete|save changes|confirm/i})).toBeNull();
});

it('loads an owned photo only after a click and revokes its page URL on unmount',async()=>{
 const read=vi.spyOn(api,'referencePhoto').mockResolvedValue(new Blob(['DEMO image'],{type:'image/png'}));
 const mounted=render(<AssistantWorkflow view={{...base,capability_id:'gallery.photo.view',visible_fields:{photo,medication_name:'DEMO medicine'}}} busy={false} onEvent={vi.fn()}/>);
 fireEvent.click(await screen.findByRole('button',{name:'View original photo'}));
 expect(await screen.findByRole('img',{name:'DEMO original package'})).toHaveProperty('src','blob:DEMO-owned-original');
 expect(read).toHaveBeenCalledWith(id);expect(create).toHaveBeenCalledTimes(1);
 mounted.unmount();expect(revoke).toHaveBeenCalledWith('blob:DEMO-owned-original');
});

it('previews a PDF through the native bytes API and offers the original filename download',async()=>{
 const read=vi.spyOn(api,'libraryPdf').mockResolvedValue(new Blob(['%PDF-DEMO'],{type:'application/pdf'}));
 render(<AssistantWorkflow view={{...base,capability_id:'library.pdf.view',visible_fields:{file}}} busy={false} onEvent={vi.fn()}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Preview PDF'}));
 expect(await screen.findByTitle('PDF preview')).toHaveProperty('src','blob:DEMO-owned-original');
 expect(read).toHaveBeenCalledWith(id,'inline');
 expect(screen.getByRole('link',{name:'Download original'})).toHaveProperty('download','DEMO_original.pdf');
 expect(screen.getByText('This PDF is stored as a document. Its medication instructions have not been extracted or reviewed here.')).toBeTruthy();
});

it('keeps PDF metadata after download failure and allows an explicit retry',async()=>{
 const read=vi.spyOn(api,'libraryPdf').mockRejectedValueOnce(new Error('DEMO unavailable')).mockResolvedValueOnce(new Blob(['%PDF-DEMO'],{type:'application/pdf'}));
 render(<AssistantWorkflow view={{...base,capability_id:'library.pdf.download',visible_fields:{file}}} busy={false} onEvent={vi.fn()}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Prepare download'}));
 expect((await screen.findByRole('alert')).textContent).toBe('The original could not be loaded. Your selection is still here. Try again.');
 expect(screen.getByText('DEMO label')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'Prepare download'}));
 expect(await screen.findByRole('link',{name:'Download original'})).toHaveProperty('href','blob:DEMO-owned-original');
 expect(read).toHaveBeenCalledTimes(2);expect(read).toHaveBeenLastCalledWith(id,'attachment');
 expect(screen.queryByTitle('PDF preview')).toBeNull();
});

it('discards a late binary response after switching the selected task revision',async()=>{
 let resolve!:(value:Blob)=>void;vi.spyOn(api,'referencePhoto').mockImplementation(()=>new Promise(done=>{resolve=done;}));
 const mounted=render(<AssistantWorkflow view={{...base,capability_id:'gallery.photo.view',visible_fields:{photo}}} busy={false} onEvent={vi.fn()}/>);
 fireEvent.click(await screen.findByRole('button',{name:'View original photo'}));
 mounted.rerender(<AssistantWorkflow view={{...base,revision:3,capability_id:'gallery.photo.view',visible_fields:{photo:{...photo,id:'00000000-0000-4000-8000-000000000100',source_description:'DEMO second photo'}}}} busy={false} onEvent={vi.fn()}/>);
 await screen.findByText('DEMO second photo');resolve(new Blob(['DEMO old bytes'],{type:'image/png'}));
 await waitFor(()=>expect(screen.queryByRole('img')).toBeNull());expect(create).not.toHaveBeenCalled();
});

it('dispatches only an offered media choice and preserves typed paging',async()=>{
 const send=vi.fn();const action={kind:'choice' as const,action_id:'media.image',options:[{value:id,label_key:'assistant.media.select',label_text:'DEMO offered photo'}]};
 const view={...base,capability_id:'gallery.photo.view',actions:[action],missing_fields:['image_id']};
 render(<AssistantWorkflow view={view} busy={false} onEvent={send}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Select: DEMO offered photo'}));
 expect(send).toHaveBeenCalledWith(expect.objectContaining({kind:'provide_fields',values:{image_id:id,page:0}}));
 expect(()=>workflowChoice(view,action,'00000000-0000-4000-8000-000000000101')).toThrow();
 expect(()=>workflowChoice({...view,capability_id:'medication.enroll'},action,id)).toThrow();
});

it('shows paging errors and retains the displayed metadata',async()=>{
 render(<AssistantWorkflow view={{...base,visible_fields:{records:[{name:'DEMO page one',photo_count:1,status:'current',medication_id:id}],page:0,page_count:2,total:11}}} busy={false} onEvent={vi.fn().mockRejectedValue(new Error('DEMO read unavailable'))}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Next page'}));
 expect((await screen.findByRole('alert')).textContent).toBe('The query did not finish. Your selection is still here. Try again.');expect(screen.getByText('DEMO page one')).toBeTruthy();
});

it('describes saving an ephemeral media query without implying a plan review or record write',async()=>{
 render(<AssistantWorkflow view={{...base,save_mode:'ephemeral',storage_state:'ephemeral'}} busy={false} onEvent={vi.fn()}/>);
 expect(await screen.findByRole('button',{name:'Save this query'})).toBeTruthy();
 expect(screen.getByText('Saving keeps this query as a task. It does not change medication records.')).toBeTruthy();
});
