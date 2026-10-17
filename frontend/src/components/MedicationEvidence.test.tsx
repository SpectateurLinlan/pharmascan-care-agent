// @vitest-environment jsdom
// AUTOMATED/SIMULATED component wiring; real providers are tested separately.
import {afterEach,expect,it,vi} from 'vitest';
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {api,type EvidenceTask,type GalleryEntry,type GalleryImage} from '../api/client';
import {EvidenceEnrollmentScreen} from './EvidenceEnrollmentScreen';
import {PersonalGalleryScreen} from './PersonalGalleryScreen';
import {MedicinesHub} from './MedicinesHub';
import {medicationSetupEntries} from '../medicationSetup';
vi.mock('../api/client',()=>({ApiError:class extends Error{},api:{sourcePreview:vi.fn(),checkInput:vi.fn(),personalGallery:vi.fn(),referencePhoto:vi.fn(),addReference:vi.fn(),retireReference:vi.fn(),evidenceTasks:vi.fn(),evidenceTask:vi.fn(),evidenceSources:vi.fn(),attachEvidence:vi.fn(),reviewEvidence:vi.fn(),requestChallenge:vi.fn(),activate:vi.fn(),sendMessage:vi.fn()}}));
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.resetAllMocks();});
const task:EvidenceTask={id:'DEMO-task',medication_id:'DEMO-med',version:2,status:'pending_information',product:{name:'DEMO Metformin',strength:'500 mg',dose_form:'tablet',formulation:null,brand:null,ingredients:[],category:'unknown',verification:'source_supplied'},source_ids:['DEMO-source'],missing:['dose_amount','schedule'],conflicts:[],possible_duplicate_ids:[],draft_regimen_id:null,suggested_regimen:null};
const preview:Awaited<ReturnType<typeof api.sourcePreview>>={note:'SIMULATED',source_document_id:'DEMO-preview',source_kind:'package',provider:'SIMULATED',extraction_model:'SIMULATED',review_required:true,candidates:[{product:{name:'DEMO read-only label',strength:'500 mg',source_lines:[]},review_status:'extracted',can_activate_regimen:false,regimen_evidence:{directions:null,dose_amount:null,frequency:null,administration_times:null,duration:null}}]};
function mocks(){vi.mocked(api.sourcePreview).mockResolvedValue(preview);vi.mocked(api.checkInput).mockResolvedValue({image_type:'package',checked:true,abstained:true,suggested_workflow:'source_review',message:'DEMO routing'});vi.mocked(api.personalGallery).mockResolvedValue([]);vi.mocked(api.evidenceTasks).mockResolvedValue([]);vi.mocked(api.evidenceSources).mockResolvedValue([]);vi.spyOn(URL,'createObjectURL').mockReturnValue('blob:DEMO');vi.spyOn(URL,'revokeObjectURL').mockImplementation(()=>undefined);}
it('reads without persistence, then explicitly saves and opens plan review without an unsolicited Agent call',async()=>{
 mocks();vi.mocked(api.attachEvidence).mockResolvedValue(task);vi.mocked(api.sendMessage).mockResolvedValue({message:'Dose instructions are missing. Please add a pharmacy label.',intent:'medication_enrollment',mode:'gemini',tool_traces:[],session_id:'DEMO-session',session_state:'idle',requires_confirmation:false});
 render(<EvidenceEnrollmentScreen sessionId="DEMO-session" onChanged={vi.fn()}/>);
 fireEvent.change(screen.getByLabelText('Take or choose a photo'),{target:{files:[new File(['DEMO'],'demo.png',{type:'image/png'})]}});
 expect(api.attachEvidence).not.toHaveBeenCalled();fireEvent.click(screen.getByLabelText('I allow this photo to be sent to the recognition service to read medication information. I can change this in Privacy and data.'));fireEvent.click(screen.getByRole('button',{name:'Read photo'}));
 await screen.findByRole('heading',{name:'Read from your photo'});expect(api.attachEvidence).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'Save source and set up plan'}));await screen.findByRole('heading',{name:'DEMO Metformin'});
 expect(api.sendMessage).not.toHaveBeenCalled();expect(api.reviewEvidence).not.toHaveBeenCalled();expect(api.activate).not.toHaveBeenCalled();
 expect(screen.getByLabelText('Dose time 1')).toBeTruthy();
});
it('reload restores a conflicting task and prevents plan review without hiding the original evidence',async()=>{
 mocks();vi.mocked(api.evidenceTask).mockResolvedValue({...task,status:'conflict',conflicts:['strength: 500 mg / 1000 mg (source DEMO)']});
 render(<EvidenceEnrollmentScreen initialTaskId="DEMO-task" sessionId="DEMO-session" onChanged={vi.fn()}/>);
 await screen.findByText('Sources need clarification');expect(screen.getByRole('button',{name:'Prepare activation confirmation'})).toHaveProperty('disabled',true);expect(screen.getByText('Strength: 500 mg / 1000 mg')).toBeTruthy();expect(api.activate).not.toHaveBeenCalled();
});
// Saved registrations are now a visible list, not a collapsed <details>: there is
// nothing to open, so the tests wait for the heading and click the row itself.
it('does not attach the old photo to a new registration when type detection completes late',async()=>{
 mocks();vi.mocked(api.evidenceTasks).mockResolvedValue([task]);
 let resolveRoute!:(value:Awaited<ReturnType<typeof api.checkInput>>)=>void;
 vi.mocked(api.checkInput).mockReturnValue(new Promise(resolve=>{resolveRoute=resolve;}));
 render(<EvidenceEnrollmentScreen sessionId="DEMO-session" onChanged={vi.fn()}/>);
 await screen.findByText(/Continue a saved registration/);
 fireEvent.click(screen.getByRole('button',{name:/DEMO Metformin/}));
 await screen.findByRole('heading',{name:'DEMO Metformin'});
 fireEvent.change(screen.getByLabelText('Take or choose a photo'),{target:{files:[new File(['DEMO'],'demo.png',{type:'image/png'})]}});
 fireEvent.click(screen.getByLabelText('I allow this photo to be sent to the recognition service to read medication information. I can change this in Privacy and data.'));
 fireEvent.click(screen.getByRole('button',{name:'Read photo'}));
 await waitFor(()=>expect(api.checkInput).toHaveBeenCalledOnce());
 fireEvent.click(screen.getByRole('button',{name:'Cancel supplement'}));
 await act(async()=>resolveRoute({image_type:'package',checked:true,abstained:true,suggested_workflow:'source_review',message:'DEMO routing'}));
 expect(api.attachEvidence).not.toHaveBeenCalled();expect(api.sendMessage).not.toHaveBeenCalled();
 expect(screen.queryByRole('heading',{name:'DEMO Metformin'})).toBeNull();
});
it('keeps a new registration selected when a previously submitted upload returns',async()=>{
 mocks();vi.mocked(api.evidenceTasks).mockResolvedValue([task]);
 let resolveUpload!:(value:EvidenceTask)=>void;
 vi.mocked(api.attachEvidence).mockReturnValue(new Promise(resolve=>{resolveUpload=resolve;}));
 const key='pharmascan.enrollment.DEMO-rc-owner';
 render(<EvidenceEnrollmentScreen ownerId="DEMO-rc-owner" sessionId="DEMO-session" onChanged={vi.fn()}/>);
 await screen.findByText(/Continue a saved registration/);
 fireEvent.click(screen.getByRole('button',{name:/DEMO Metformin/}));await screen.findByRole('heading',{name:'DEMO Metformin'});
 fireEvent.change(screen.getByLabelText('Take or choose a photo'),{target:{files:[new File(['DEMO'],'demo.png',{type:'image/png'})]}});
 fireEvent.click(screen.getByLabelText('I allow this photo to be sent to the recognition service to read medication information. I can change this in Privacy and data.'));
 fireEvent.click(screen.getByRole('button',{name:'Read photo'}));
 await screen.findByRole('button',{name:'Save source and set up plan'});fireEvent.click(screen.getByRole('button',{name:'Save source and set up plan'}));await waitFor(()=>expect(api.attachEvidence).toHaveBeenCalledWith(task.id,expect.any(File),'package',undefined,true));
 fireEvent.click(screen.getByRole('button',{name:'Cancel supplement'}));
 await act(async()=>resolveUpload(task));
 expect(screen.queryByRole('heading',{name:'DEMO Metformin'})).toBeNull();
 expect(localStorage.getItem(key)).toBeNull();expect(api.sendMessage).not.toHaveBeenCalled();
});
it('does not restore an earlier navigation target after explicitly starting a new medicine',async()=>{
 mocks();vi.mocked(api.evidenceTask).mockResolvedValue(task);const fresh=vi.fn();
 const view=render(<EvidenceEnrollmentScreen initialTaskId={task.id} sessionId="DEMO-session" onChanged={vi.fn()} onNewRegistration={fresh}/>);
 await screen.findByRole('heading',{name:'DEMO Metformin'});
 fireEvent.click(screen.getByRole('button',{name:'Cancel supplement'}));expect(fresh).toHaveBeenCalledOnce();
 view.rerender(<EvidenceEnrollmentScreen initialTaskId={null} active={false} sessionId="DEMO-session" onChanged={vi.fn()} onNewRegistration={fresh}/>);
 view.rerender(<EvidenceEnrollmentScreen initialTaskId={null} active sessionId="DEMO-session" onChanged={vi.fn()} onNewRegistration={fresh}/>);
 await act(async()=>{});expect(screen.queryByRole('heading',{name:'DEMO Metformin'})).toBeNull();expect(api.evidenceTask).toHaveBeenCalledOnce();
});
it('ignores an old upload after navigation selects another saved task',async()=>{
 mocks();vi.mocked(api.evidenceTask).mockResolvedValue(task);
 let resolveUpload!:(value:EvidenceTask)=>void;vi.mocked(api.attachEvidence).mockReturnValue(new Promise(resolve=>{resolveUpload=resolve;}));
 const view=render(<EvidenceEnrollmentScreen initialTaskId={task.id} sessionId="DEMO-session" onChanged={vi.fn()}/>);
 await screen.findByRole('heading',{name:'DEMO Metformin'});
 fireEvent.change(screen.getByLabelText('Take or choose a photo'),{target:{files:[new File(['DEMO'],'demo.png',{type:'image/png'})]}});
 fireEvent.click(screen.getByLabelText('I allow this photo to be sent to the recognition service to read medication information. I can change this in Privacy and data.'));
 fireEvent.click(screen.getByRole('button',{name:'Read photo'}));await screen.findByRole('button',{name:'Save source and set up plan'});fireEvent.click(screen.getByRole('button',{name:'Save source and set up plan'}));await waitFor(()=>expect(api.attachEvidence).toHaveBeenCalledOnce());
 const second={...task,id:'DEMO-task-B',medication_id:'DEMO-med-B',product:{...task.product,name:'DEMO Another medicine'}};
 vi.mocked(api.evidenceTask).mockResolvedValue(second);
 view.rerender(<EvidenceEnrollmentScreen initialTaskId={second.id} sessionId="DEMO-session" onChanged={vi.fn()}/>);
 await screen.findByRole('heading',{name:'DEMO Another medicine'});await act(async()=>resolveUpload(task));
 expect(screen.queryByRole('heading',{name:'DEMO Metformin'})).toBeNull();expect(screen.getByRole('heading',{name:'DEMO Another medicine'})).toBeTruthy();expect(api.sendMessage).not.toHaveBeenCalled();
});
it('allows continuing the selected saved task while discarding the earlier pending upload',async()=>{
 mocks();const second={...task,id:'DEMO-task-B',product:{...task.product,name:'DEMO Second medicine'}};
 vi.mocked(api.evidenceTasks).mockResolvedValue([task,second]);
 let resolveUpload!:(value:EvidenceTask)=>void;vi.mocked(api.attachEvidence).mockReturnValue(new Promise(resolve=>{resolveUpload=resolve;}));
 render(<EvidenceEnrollmentScreen sessionId="DEMO-session" onChanged={vi.fn()}/>);
 await screen.findByText(/Continue a saved registration/);fireEvent.click(screen.getByRole('button',{name:/DEMO Metformin/}));await screen.findByRole('heading',{name:'DEMO Metformin'});
 fireEvent.change(screen.getByLabelText('Take or choose a photo'),{target:{files:[new File(['DEMO'],'demo.png',{type:'image/png'})]}});
 fireEvent.click(screen.getByLabelText('I allow this photo to be sent to the recognition service to read medication information. I can change this in Privacy and data.'));
 fireEvent.click(screen.getByRole('button',{name:'Read photo'}));await screen.findByRole('button',{name:'Save source and set up plan'});fireEvent.click(screen.getByRole('button',{name:'Save source and set up plan'}));await waitFor(()=>expect(api.attachEvidence).toHaveBeenCalledOnce());
 fireEvent.click(screen.getByRole('button',{name:/DEMO Second medicine/}));await screen.findByRole('heading',{name:'DEMO Second medicine'});
 await act(async()=>resolveUpload(task));
 expect(screen.getByLabelText('Take or choose a photo')).toHaveProperty('disabled',false);
 expect(screen.queryByRole('heading',{name:'DEMO Metformin'})).toBeNull();expect(api.sendMessage).not.toHaveBeenCalled();
});
const photo:GalleryImage={id:'DEMO-image',medication_id:'DEMO-med',image_kind:'loose_pill',source_description:'DEMO reviewed sample',reviewed:true,eligibility:'eligible',eligibility_reason:'patient_reviewed_visual_reference_only',created_at:'2026-10-15T00:00:00Z'};
const entry:GalleryEntry={evidence_task_id:'DEMO-task',medication:{id:'DEMO-med',display_name:'DEMO Metformin',identity_status:'user_reviewed_document'},product:task.product,status:'current',regimens:[{id:'DEMO-regimen',state:'active',version_no:1,course_start_date:'2026-10-15',course_end_date:'2026-10-21',dose_amount:1,dose_unit:'tablet'}],images:[photo],eligible_count:1};
it('groups by product, reads private thumbnails and retains course history behind the detail entry',async()=>{
 mocks();vi.mocked(api.personalGallery).mockResolvedValue([entry]);vi.mocked(api.referencePhoto).mockResolvedValue(new Blob(['DEMO'],{type:'image/png'}));const check=vi.fn(),sources=vi.fn();render(<PersonalGalleryScreen onCheck={check} onSources={sources}/>);
 await screen.findByRole('button',{name:/DEMO Metformin/});expect(screen.queryByText('Medication courses')).toBeNull();fireEvent.click(screen.getByRole('button',{name:/DEMO Metformin/}));await screen.findByAltText('Pill reference photo');expect(api.referencePhoto).toHaveBeenCalledWith(photo.id);fireEvent.click(screen.getByRole('button',{name:'Source information and review'}));expect(sources).toHaveBeenCalledWith('DEMO-task');
 fireEvent.click(screen.getByRole('button',{name:'Check this dose'}));expect(check).toHaveBeenCalledWith('DEMO-regimen');expect(screen.getByText(/2026-10-15/)).toBeTruthy();
});
it('retiring a reference refreshes its status without deleting its private photo or medication plan',async()=>{
 mocks();vi.mocked(api.personalGallery).mockResolvedValueOnce([entry]).mockResolvedValue([{...entry,eligible_count:0,images:[{...photo,eligibility:'ineligible'}]}]);vi.mocked(api.referencePhoto).mockResolvedValue(new Blob(['DEMO']));vi.mocked(api.retireReference).mockResolvedValue({...photo,eligibility:'ineligible'});
 render(<PersonalGalleryScreen onCheck={vi.fn()}/>);fireEvent.click(await screen.findByRole('button',{name:/DEMO Metformin/}));fireEvent.click(screen.getByRole('button',{name:'Remove from visual comparison'}));await waitFor(()=>expect(api.retireReference).toHaveBeenCalledWith(photo.id));await screen.findByText(/Removed from visual comparison/);expect(screen.getByRole('button',{name:'Check this dose'})).toBeTruthy();
});

it('unfinished registration count includes identity-only source tasks, not just regimen drafts',async()=>{
 mocks();vi.mocked(api.evidenceTasks).mockResolvedValue([task,{...task,id:'DEMO-finished',status:'draft_created'}]);
 render(<MedicinesHub medications={[]} drafts={[]} setupCount={medicationSetupEntries([task,{...task,id:'DEMO-finished',status:'draft_created'}],[]).length} versions={[]} onOpen={vi.fn()}/>);
 await screen.findByText('1 awaiting review');expect(screen.getByRole('button',{name:/Finish medication setup/})).toBeTruthy();
});
