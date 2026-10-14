// @vitest-environment jsdom
// AUTOMATED/SIMULATED component wiring; real providers are tested separately.
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {api,type EvidenceTask,type GalleryEntry,type GalleryImage} from '../api/client';
import {EvidenceEnrollmentScreen} from './EvidenceEnrollmentScreen';
import {PersonalGalleryScreen} from './PersonalGalleryScreen';
import {MedicinesHub} from './MedicinesHub';
vi.mock('../api/client',()=>({ApiError:class extends Error{},api:{personalGallery:vi.fn(),referencePhoto:vi.fn(),addReference:vi.fn(),retireReference:vi.fn(),evidenceTasks:vi.fn(),evidenceTask:vi.fn(),evidenceSources:vi.fn(),attachEvidence:vi.fn(),reviewEvidence:vi.fn(),requestChallenge:vi.fn(),activate:vi.fn(),sendMessage:vi.fn()}}));
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.resetAllMocks();});
const task:EvidenceTask={id:'DEMO-task',medication_id:'DEMO-med',version:2,status:'pending_information',product:{name:'DEMO Metformin',strength:'500 mg',dose_form:'tablet',formulation:null,brand:null,ingredients:[],category:'unknown',verification:'source_supplied'},source_ids:['DEMO-source'],missing:['dose_amount','schedule'],conflicts:[],possible_duplicate_ids:[],draft_regimen_id:null,suggested_regimen:null};
function mocks(){vi.mocked(api.personalGallery).mockResolvedValue([]);vi.mocked(api.evidenceTasks).mockResolvedValue([]);vi.mocked(api.evidenceSources).mockResolvedValue([]);vi.spyOn(URL,'createObjectURL').mockReturnValue('blob:DEMO');vi.spyOn(URL,'revokeObjectURL').mockImplementation(()=>undefined);}
it('persists a package task then sends its verified task reference through the normal Agent flow',async()=>{
 mocks();vi.mocked(api.attachEvidence).mockResolvedValue(task);vi.mocked(api.sendMessage).mockResolvedValue({message:'Dose instructions are missing. Please add a pharmacy label.',intent:'medication_enrollment',mode:'gemini',tool_traces:[],session_id:'DEMO-session',session_state:'idle',requires_confirmation:false});
 render(<EvidenceEnrollmentScreen sessionId="DEMO-session" onChanged={vi.fn()}/>);
 fireEvent.change(screen.getByLabelText('Take or choose a photo'),{target:{files:[new File(['DEMO'],'demo.png',{type:'image/png'})]}});
 expect(api.attachEvidence).not.toHaveBeenCalled();fireEvent.click(screen.getByLabelText('I agree to private storage and the selected image processing. Use synthetic files for this demo.'));fireEvent.click(screen.getByRole('button',{name:'Read and save source'}));
 await screen.findByText(/Dose instructions are missing/);expect(api.sendMessage).toHaveBeenCalledWith(expect.objectContaining({session_id:'DEMO-session',slots:{evidence_task_id:'DEMO-task'}}));
 expect(api.reviewEvidence).not.toHaveBeenCalled();expect(api.activate).not.toHaveBeenCalled();
 expect(screen.getByRole('button',{name:'Review product and medication plan'})).toBeTruthy();
});
it('reload restores a conflicting task and prevents plan review without hiding the original evidence',async()=>{
 mocks();vi.mocked(api.evidenceTask).mockResolvedValue({...task,status:'conflict',conflicts:['strength: 500 mg / 1000 mg (source DEMO)']});
 render(<EvidenceEnrollmentScreen initialTaskId="DEMO-task" sessionId="DEMO-session" onChanged={vi.fn()}/>);
 await screen.findByText('Sources need clarification');expect(screen.getByRole('button',{name:'Review product and medication plan'})).toHaveProperty('disabled',true);expect(screen.getByText('Strength: 500 mg / 1000 mg')).toBeTruthy();expect(api.activate).not.toHaveBeenCalled();
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
 render(<MedicinesHub medications={[]} drafts={[]} versions={[]} onOpen={vi.fn()}/>);
 await screen.findByText('1 awaiting review');expect(screen.getByRole('button',{name:/Finish medication setup/})).toBeTruthy();
});
