// @vitest-environment jsdom
// AUTOMATED/SIMULATED component wiring; real providers are tested separately.
import {afterEach,expect,it,vi} from 'vitest';
import {act,cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {api,type EvidenceTask,type GalleryEntry,type GalleryImage,type RegimenHistoryItem,type MedicationKnowledge,type MedicationLibrarySource,type MedicationFiles} from '../api/client';
import {EvidenceEnrollmentScreen} from './EvidenceEnrollmentScreen';
import {PersonalGalleryScreen} from './PersonalGalleryScreen';
import {MedicinesHub,MedicationDetail} from './MedicinesHub';
import {medicationSetupEntries} from '../medicationSetup';
import {LanguageProvider,useLanguage} from '../language';
vi.mock('../api/client',()=>({ApiError:class extends Error{},api:{sourcePreview:vi.fn(),checkInput:vi.fn(),personalGallery:vi.fn(),medicationFiles:vi.fn(),referencePhoto:vi.fn(),addReference:vi.fn(),retireReference:vi.fn(),evidenceTasks:vi.fn(),evidenceTask:vi.fn(),evidenceSources:vi.fn(),attachEvidence:vi.fn(),reviewEvidence:vi.fn(),requestChallenge:vi.fn(),activate:vi.fn(),sendMessage:vi.fn(),medicationHistory:vi.fn(),inventory:vi.fn(),medicationKnowledge:vi.fn(),updatePreferences:vi.fn()}}));
afterEach(()=>{cleanup();window.history.replaceState({},'','#');vi.restoreAllMocks();vi.resetAllMocks();});
const task:EvidenceTask={id:'DEMO-task',medication_id:'DEMO-med',version:2,status:'pending_information',product:{name:'DEMO Metformin',strength:'500 mg',dose_form:'tablet',formulation:null,brand:null,ingredients:[],category:'unknown',verification:'source_supplied'},source_ids:['DEMO-source'],missing:['dose_amount','schedule'],conflicts:[],possible_duplicate_ids:[],draft_regimen_id:null,suggested_regimen:null};
const preview:Awaited<ReturnType<typeof api.sourcePreview>>={note:'SIMULATED',source_document_id:'DEMO-preview',source_kind:'package',provider:'SIMULATED',extraction_model:'SIMULATED',review_required:true,candidates:[{product:{name:'DEMO read-only label',strength:'500 mg',source_lines:[]},review_status:'extracted',can_activate_regimen:false,regimen_evidence:{directions:null,dose_amount:null,frequency:null,administration_times:null,duration:null}}]};
function mocks(){vi.mocked(api.sourcePreview).mockResolvedValue(preview);vi.mocked(api.checkInput).mockResolvedValue({image_type:'package',checked:true,abstained:true,suggested_workflow:'source_review',message:'DEMO routing'});vi.mocked(api.personalGallery).mockResolvedValue([]);vi.mocked(api.medicationFiles).mockResolvedValue({medication_id:'DEMO-med',files:[],source_records:[],regimens:[]});vi.mocked(api.referencePhoto).mockResolvedValue(new Blob(['DEMO image'],{type:'image/png'}));vi.mocked(api.evidenceTasks).mockResolvedValue([]);vi.mocked(api.evidenceSources).mockResolvedValue([]);vi.spyOn(URL,'createObjectURL').mockReturnValue('blob:DEMO');vi.spyOn(URL,'revokeObjectURL').mockImplementation(()=>undefined);}
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
function fileResponse(row:GalleryEntry):MedicationFiles{return{file_management_available:true,medication_id:row.medication.id,files:row.images.map(image=>({id:image.id,image_id:image.id,image_ids:[image.id],name:image.source_description,format:'PNG',content_type:'image',photo_description:image.image_kind,purpose_tags:['evidence',...(image.eligibility==='eligible'?['appearance_reference' as const]:[])],created_at:image.created_at,eligibility:image.eligibility,eligibility_reason:image.eligibility_reason,sources:[]})),source_records:[],regimens:[]};}
const detailEndedPlan:RegimenHistoryItem={regimen_id:'DEMO-stopped',medication_id:'DEMO-med',supersedes_id:null,display_name:'DEMO Metformin',version_no:1,state:'ended',effective_from:null,effective_to:'2026-10-18T00:00:00Z',course_start_date:'2026-10-01',course_end_date:'2026-10-31',dose_amount:1,dose_unit:'tablet',food_instruction:null,is_prn:false,local_times:['08:00']};
it('groups by product, reads private thumbnails, keeps course history and has no dose-check action',async()=>{
 mocks();vi.mocked(api.personalGallery).mockResolvedValue([entry]);vi.mocked(api.medicationFiles).mockResolvedValue(fileResponse(entry));vi.mocked(api.referencePhoto).mockResolvedValue(new Blob(['DEMO'],{type:'image/png'}));const sources=vi.fn();render(<PersonalGalleryScreen onSources={sources}/>);
 await screen.findByRole('button',{name:/DEMO Metformin/});expect(screen.queryByText('Medication courses')).toBeNull();fireEvent.click(screen.getByRole('button',{name:/DEMO Metformin/}));await screen.findByAltText('Pill reference photo');expect(api.referencePhoto).toHaveBeenCalledWith(photo.id);fireEvent.click(screen.getByRole('button',{name:'Source information and review'}));expect(sources).toHaveBeenCalledWith('DEMO-task');
 expect(screen.queryByRole('button',{name:'Check this dose'})).toBeNull();expect(screen.getByText(/2026-10-15/)).toBeTruthy();
});
it('labels stopped, expired and superseded courses distinctly in the Gallery in English and Chinese',async()=>{
 mocks();const galleryEntry={...entry,regimens:[{id:'DEMO-stopped',state:'ended',version_no:2,course_start_date:'2026-10-01',course_end_date:'2026-10-31',dose_amount:1,dose_unit:'tablet'},{id:'DEMO-expired',state:'active',version_no:1,course_start_date:'2026-09-01',course_end_date:'2004-01-01',dose_amount:1,dose_unit:'tablet'},{id:'DEMO-superseded',state:'superseded',version_no:1,course_start_date:null,course_end_date:null,dose_amount:1,dose_unit:'tablet'}]};
 vi.mocked(api.personalGallery).mockResolvedValue([galleryEntry]);vi.mocked(api.medicationFiles).mockResolvedValue(fileResponse(galleryEntry));
 const view=render(<PersonalGalleryScreen initialMedicationId="DEMO-med"/>);
 expect(await screen.findAllByText('Terminated',{exact:true})).not.toHaveLength(0);expect(screen.getByText('Course Expired',{exact:true})).toBeTruthy();expect(screen.getByText('Superseded',{exact:true})).toBeTruthy();
 vi.spyOn(api,'updatePreferences').mockResolvedValue({patient_id:'DEMO-patient',preferred_language:'zh',speech_locale:'zh-CN',text_size:'standard',voice_enabled:false,tts_autoplay:false,reminder_lead_minutes:0,timezone:'Asia/Singapore',created_at:'2026-10-19T00:00:00Z',updated_at:'2026-10-19T00:00:00Z'});
 function SwitchLanguage(){const {setLanguage}=useLanguage();return <button type="button" onClick={()=>setLanguage('zh')}>DEMO Chinese</button>;}
 view.unmount();render(<LanguageProvider><SwitchLanguage/><PersonalGalleryScreen initialMedicationId="DEMO-med"/></LanguageProvider>);fireEvent.click(screen.getByRole('button',{name:'DEMO Chinese'}));
 expect(await screen.findByText('\u5df2\u7ec8\u6b62')).toBeTruthy();expect(screen.getByText('\u5df2\u5230\u671f')).toBeTruthy();expect(screen.getByText('\u5df2\u88ab\u66ff\u4ee3')).toBeTruthy();
});
it('labels a stopped course in Medication Detail using the shared English and Chinese mapping',async()=>{
 mocks();vi.mocked(api.medicationHistory).mockResolvedValue({entries:[],next_cursor:null,window_start:null,window_end:'2026-10-19T00:00:00Z',as_of:'2026-10-19T00:00:00Z',scope:'stored_records_only',missing_plan_start:false});
 vi.mocked(api.inventory).mockResolvedValue({medication_id:'DEMO-med',unit:null,last_confirmed_stock:null,last_confirmed_at:null,estimated_remaining:null,daily_requirement:null,estimated_days:null,low_stock:false,estimate_note:'DEMO synthetic inventory',transactions:[]});
 const props={row:detailEndedPlan,onHistory:vi.fn(),onGallery:vi.fn(),onCheck:vi.fn()};const view=render(<MedicationDetail {...props}/>);
 expect(await screen.findAllByText('Terminated',{exact:true})).toHaveLength(2);
 vi.spyOn(api,'updatePreferences').mockResolvedValue({patient_id:'DEMO-patient',preferred_language:'zh',speech_locale:'zh-CN',text_size:'standard',voice_enabled:false,tts_autoplay:false,reminder_lead_minutes:0,timezone:'Asia/Singapore',created_at:'2026-10-19T00:00:00Z',updated_at:'2026-10-19T00:00:00Z'});
 function SwitchLanguage(){const {setLanguage}=useLanguage();return <button type="button" onClick={()=>setLanguage('zh')}>DEMO Chinese</button>;}
 view.unmount();render(<LanguageProvider><SwitchLanguage/><MedicationDetail {...props}/></LanguageProvider>);fireEvent.click(screen.getByRole('button',{name:'DEMO Chinese'}));
 expect(await screen.findAllByText('\u5df2\u7ec8\u6b62')).toHaveLength(2);
});
it('opens the exact medication ID when names are identical and does not merge gallery identities',async()=>{
 mocks();const other={...entry,evidence_task_id:'DEMO-other-task',medication:{...entry.medication,id:'DEMO-other-med'},images:[]};vi.mocked(api.personalGallery).mockResolvedValue([entry,other]);
 const sources=vi.fn();render(<PersonalGalleryScreen initialMedicationId="DEMO-other-med" onSources={sources}/>);await screen.findByRole('heading',{name:/DEMO Metformin/});fireEvent.click(screen.getByRole('button',{name:'Source information and review'}));expect(sources).toHaveBeenCalledWith('DEMO-other-task');expect(screen.queryByRole('button',{name:'Check this dose'})).toBeNull();
});
it('shows linked source provenance in the unified file grid and opens its authenticated source detail route',async()=>{
 mocks();vi.mocked(api.personalGallery).mockResolvedValue([entry]);
 const source:MedicationLibrarySource={id:'DEMO-source',source_kind:'prescription',review_status:'extracted',reviewed_at:null,recorded_at:'2026-10-15T00:00:00Z',extraction_evidence:preview,fields:[{id:'DEMO-field',field_name:'medication_name',field_value:'DEMO Metformin',review_status:'extracted',reviewed_at:null}],regimen_ids:['DEMO-regimen'],image_ids:[photo.id]};
 const files=fileResponse(entry);files.files[0]!.purpose_tags=['evidence','appearance_reference','enrollment_source'];files.files[0]!.sources=[source];
 vi.mocked(api.medicationFiles).mockResolvedValue(files);
 render(<PersonalGalleryScreen initialMedicationId="DEMO-med"/>);
 fireEvent.click(await screen.findByRole('button',{name:'Source materials'}));
 fireEvent.click(await screen.findByRole('button',{name:'View source record: Prescription'}));
 expect(await screen.findByRole('dialog')).toBeTruthy();expect(screen.getByText(/not a medically verified prescription/)).toBeTruthy();
 expect(screen.getByText(/DEMO read-only label/)).toBeTruthy();expect(screen.getAllByText(/Plan version 1/).length).toBeGreaterThan(0);
 expect(new URLSearchParams(location.hash.split('?')[1]).get('source_id')).toBe('DEMO-source');
});
it('uses neutral file titles, unknown-purpose fallback and overlapping source/reference filters',async()=>{
 mocks();vi.mocked(api.personalGallery).mockResolvedValue([entry]);const files=fileResponse(entry);files.files[0]!.name='home';files.files[0]!.purpose_tags=['legacy_unmapped','appearance_reference'];
 const source:MedicationLibrarySource={id:'DEMO-source',source_kind:'prescription',review_status:'extracted',reviewed_at:null,recorded_at:null,extraction_evidence:preview,fields:[],regimen_ids:[],image_ids:[photo.id]};files.files[0]!.sources=[source];vi.mocked(api.medicationFiles).mockResolvedValue(files);
 render(<PersonalGalleryScreen initialMedicationId="DEMO-med"/>);
 expect(await screen.findByText(/Medication photo|药物照片/)).toBeTruthy();expect(screen.queryByText('home')).toBeNull();expect(screen.getByText(/Unclassified purpose|用途未分类/)).toBeTruthy();
 const filter=screen.getByRole('group',{name:/Filter medication files|筛选药物资料/});const all=within(filter).getByRole('button',{name:/^(All|全部)$/});expect(all.getAttribute('aria-pressed')).toBe('true');
 fireEvent.click(within(filter).getByRole('button',{name:/^(Reference photos|参考照片)$/}));expect(screen.getByText(/Medication photo|药物照片/)).toBeTruthy();
 fireEvent.click(within(filter).getByRole('button',{name:/^(Source materials|来源资料)$/}));expect(screen.getByText(/Medication photo|药物照片/)).toBeTruthy();
 fireEvent.click(all);expect(screen.queryByText('home')).toBeNull();
});
it('explains source records from recorded kind and fields rather than inferring manual entry from no image',async()=>{
 mocks();vi.mocked(api.personalGallery).mockResolvedValue([entry]);const files=fileResponse(entry);files.source_records=[
  {id:'DEMO-manual',source_kind:'user_manual',review_status:'user_reviewed',reviewed_at:null,recorded_at:null,extraction_evidence:null,fields:[],regimen_ids:[],image_ids:[]},
  {id:'DEMO-source-only',source_kind:'prescription',review_status:'extracted',reviewed_at:null,recorded_at:null,extraction_evidence:preview,fields:[],regimen_ids:['DEMO-regimen'],image_ids:[]},
 ];vi.mocked(api.medicationFiles).mockResolvedValue(files);render(<PersonalGalleryScreen initialMedicationId="DEMO-med"/>);
 expect(await screen.findByRole('heading',{name:'Other source records'})).toBeTruthy();expect(screen.getByText('This record is marked as manually entered; no image is linked.')).toBeTruthy();expect(screen.getByText('Source information is recorded, but no image association is recorded.')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:/Prescription.*Source record/}));expect(await screen.findByRole('dialog')).toBeTruthy();expect(screen.getByText('Plan version 1')).toBeTruthy();
});
it('localises the medication library and file purpose controls in Chinese',async()=>{
 mocks();vi.mocked(api.personalGallery).mockResolvedValue([entry]);const files=fileResponse(entry);files.files[0]!.purpose_tags=['legacy_unmapped','appearance_reference'];vi.mocked(api.medicationFiles).mockResolvedValue(files);vi.mocked(api.updatePreferences).mockResolvedValue({patient_id:'DEMO-patient',preferred_language:'zh',speech_locale:'zh-CN',text_size:'standard',voice_enabled:true,tts_autoplay:false,reminder_lead_minutes:0,timezone:'Asia/Singapore',created_at:'2026-10-15T00:00:00Z',updated_at:'2026-10-15T00:00:00Z'});
 function SwitchLanguage(){const {setLanguage}=useLanguage();return <button type="button" onClick={()=>setLanguage('zh')}>DEMO Chinese</button>;}
 render(<LanguageProvider><SwitchLanguage/><PersonalGalleryScreen initialMedicationId="DEMO-med"/></LanguageProvider>);
 fireEvent.click(screen.getByRole('button',{name:'DEMO Chinese'}));
 expect((await screen.findAllByRole('heading',{name:/\u836f\u7269\u8d44\u6599/})).length).toBeGreaterThan(0);expect(screen.getByRole('button',{name:'\u5168\u90e8\u8d44\u6599\u5e93'})).toBeTruthy();expect(screen.getByRole('group',{name:'\u7b5b\u9009\u836f\u7269\u8d44\u6599'})).toBeTruthy();expect(screen.getByRole('button',{name:'\u53c2\u8003\u7167\u7247'})).toBeTruthy();expect(screen.getByRole('button',{name:'\u6765\u6e90\u8d44\u6599'})).toBeTruthy();expect(screen.getByText('\u836f\u7269\u7167\u7247')).toBeTruthy();expect(screen.getByText(/\u7528\u9014\u672a\u5206\u7c7b/)).toBeTruthy();
});
it('restores the medication ID from a gallery URL over stale app state and shows loading until scoped data arrives',async()=>{
 mocks();const other={...entry,evidence_task_id:'DEMO-other-task',medication:{...entry.medication,id:'DEMO-other-med',display_name:'DEMO Other medication'}};
 let resolveGallery!:(rows:GalleryEntry[])=>void;vi.mocked(api.personalGallery).mockReturnValue(new Promise(resolve=>{resolveGallery=resolve;}));
 window.history.replaceState({careRoute:['medicines','gallery']},'','#gallery?medication_id=DEMO-other-med');
 render(<PersonalGalleryScreen initialMedicationId="DEMO-med"/>);
 expect(screen.getByRole('status').textContent).toBe('Loading medication photos...');
 expect(screen.queryByText('Register a medication to begin your personal gallery.')).toBeNull();
 await act(async()=>resolveGallery([entry,other]));
  expect(await screen.findByRole('heading',{name:/DEMO Other medication.*Medication Files/})).toBeTruthy();
  expect(screen.queryByRole('heading',{name:/DEMO Metformin.*Medication Files/})).toBeNull();
});
it('links the associated medication card back to the product medication detail callback',async()=>{
 mocks();vi.mocked(api.personalGallery).mockResolvedValue([entry]);const detail=vi.fn();render(<PersonalGalleryScreen initialMedicationId="DEMO-med" onMedicationDetail={detail}/>);fireEvent.click(await screen.findByRole('button',{name:'Medication details'}));expect(detail).toHaveBeenCalledWith('DEMO-med');
});
it('searches the available product fields and keeps same-name medication records separate',async()=>{
 mocks();const other={...entry,medication:{...entry.medication,id:'DEMO-other-med'},product:{...task.product,name:'DEMO Metformin XR',brand:'DEMO Brand'}};vi.mocked(api.personalGallery).mockResolvedValue([entry,other]);
 render(<PersonalGalleryScreen/>);await screen.findAllByRole('button',{name:/DEMO Metformin/});expect(screen.getAllByRole('button',{name:/DEMO Metformin/})).toHaveLength(2);
 fireEvent.change(screen.getByLabelText('Search gallery'),{target:{value:'DEMO Brand'}});expect(screen.getAllByRole('button',{name:/DEMO Metformin/})).toHaveLength(1);
 fireEvent.change(screen.getByLabelText('Search gallery'),{target:{value:'missing'}});expect(screen.getByText('No medications match these filters.')).toBeTruthy();
});
it('includes linked PDF files in the global document filter and count',async()=>{
 mocks();vi.mocked(api.personalGallery).mockResolvedValue([{...entry,source_document_count:0,pdf_file_count:1}]);
 render(<PersonalGalleryScreen/>);const card=await screen.findByRole('button',{name:/DEMO Metformin/});
 expect(card.textContent).toContain('1 PDF files');
 fireEvent.change(screen.getByLabelText('Filter gallery'),{target:{value:'documents'}});
 expect(screen.getByRole('button',{name:/DEMO Metformin/})).toBeTruthy();
});
it('shows photo details and separately retires comparison eligibility while keeping the evidence record',async()=>{
 mocks();vi.mocked(api.personalGallery).mockResolvedValueOnce([entry]).mockResolvedValue([{...entry,eligible_count:0,images:[{...photo,eligibility:'ineligible',eligibility_reason:'patient_retired_reference'}]}]);vi.mocked(api.medicationFiles).mockResolvedValue(fileResponse(entry));vi.mocked(api.referencePhoto).mockResolvedValue(new Blob(['DEMO']));vi.mocked(api.retireReference).mockResolvedValue({...photo,eligibility:'ineligible'});
  render(<PersonalGalleryScreen initialMedicationId="DEMO-med"/>);fireEvent.click(await screen.findByRole('button',{name:'Open photo preview: Pill reference photo'}));expect(await screen.findByRole('dialog')).toBeTruthy();expect(screen.getAllByText('DEMO reviewed sample').length).toBeGreaterThan(0);expect(screen.getByRole('heading',{name:'Photo management'})).toBeTruthy();expect(screen.getByRole('button',{name:'Edit Photo Information'})).toBeTruthy();expect(screen.getByRole('button',{name:'Remove from Reference Gallery'})).toBeTruthy();expect(screen.getByRole('button',{name:'Delete Photo'})).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'Stop using for comparison'}));expect(screen.getByText('Stop using this photo for comparison? The private evidence photo will remain saved.')).toBeTruthy();fireEvent.click(screen.getByRole('button',{name:'Stop comparison'}));await waitFor(()=>expect(api.retireReference).toHaveBeenCalledWith(photo.id));expect(screen.getAllByText('Removed from visual comparison').length).toBeGreaterThan(0);expect(api.referencePhoto).toHaveBeenCalledWith(photo.id);
});
it('keeps gallery uploads evidence-only and submits content, provenance and explicit association through the existing API',async()=>{
 mocks();vi.mocked(api.addReference).mockResolvedValue({photo,duplicate:false});vi.mocked(api.personalGallery).mockResolvedValue([entry]);render(<PersonalGalleryScreen initialMedicationId="DEMO-med"/>);
 fireEvent.click(await screen.findByRole('button',{name:'Add reference photo'}));fireEvent.change(screen.getByLabelText('Choose a photo from device'),{target:{files:[new File(['DEMO image'],'sample.png',{type:'image/png'})]}});fireEvent.click(screen.getByRole('button',{name:'Continue'}));
 expect(screen.getByText(/Automatic image content classification is unavailable/)).toBeTruthy();fireEvent.change(screen.getByLabelText('Your description of the photo'),{target:{value:'source'}});fireEvent.click(screen.getByRole('button',{name:'Continue'}));fireEvent.change(screen.getByLabelText('Where did this image come from?'),{target:{value:'unknown'}});fireEvent.click(screen.getByRole('button',{name:'Continue'}));
 fireEvent.click(screen.getByRole('button',{name:'Continue'}));expect(screen.getByText(/Personal visual comparison is unavailable/)).toBeTruthy();fireEvent.click(screen.getByRole('button',{name:'Continue'}));
 expect(screen.getByRole('button',{name:'Save reference photo'})).toHaveProperty('disabled',true);
 fireEvent.click(screen.getByRole('button',{name:'Previous'}));fireEvent.click(screen.getByRole('button',{name:'Previous'}));fireEvent.click(screen.getByLabelText('I confirm this photo is associated with the medication shown. This does not verify exact product identity.'));fireEvent.click(screen.getByRole('button',{name:'Continue'}));fireEvent.click(screen.getByRole('button',{name:'Continue'}));fireEvent.click(screen.getByLabelText('I agree to privately store and prepare this image for display.'));fireEvent.click(screen.getByRole('button',{name:'Save reference photo'}));
 await waitFor(()=>expect(api.addReference).toHaveBeenCalledWith('DEMO-med',expect.any(File),'source','Unknown',true,false));
});
it('reports exact duplicate uploads and keeps the form available for replacement',async()=>{
 mocks();vi.mocked(api.addReference).mockResolvedValue({photo,duplicate:true});vi.mocked(api.personalGallery).mockResolvedValue([entry]);render(<PersonalGalleryScreen initialMedicationId="DEMO-med"/>);
 fireEvent.click(await screen.findByRole('button',{name:'Add reference photo'}));fireEvent.change(screen.getByLabelText('Choose a photo from device'),{target:{files:[new File(['DEMO image'],'sample.png',{type:'image/png'})]}});fireEvent.click(screen.getByRole('button',{name:'Continue'}));fireEvent.click(screen.getByRole('button',{name:'Continue'}));fireEvent.click(screen.getByRole('button',{name:'Continue'}));
 fireEvent.click(screen.getByLabelText('I confirm this photo is associated with the medication shown. This does not verify exact product identity.'));fireEvent.click(screen.getByRole('button',{name:'Continue'}));fireEvent.click(screen.getByRole('button',{name:'Continue'}));
 fireEvent.click(screen.getByLabelText('I agree to privately store and prepare this image for display.'));fireEvent.click(screen.getByRole('button',{name:'Save reference photo'}));await screen.findByRole('status');
 expect(screen.getByText('This photo is already saved for this medication. No duplicate copy was created.')).toBeTruthy();expect(screen.getByRole('button',{name:'View existing photo'})).toBeTruthy();expect(screen.getByRole('dialog')).toBeTruthy();for(let step=0;step<5;step++)fireEvent.click(screen.getByRole('button',{name:'Previous'}));expect(screen.getByRole('button',{name:'Replace photo'})).toBeTruthy();
 expect(api.addReference).toHaveBeenCalledWith('DEMO-med',expect.any(File),'loose_pill','Unknown',true,false);
});
it('retiring a reference refreshes its status without deleting its private photo or medication plan',async()=>{
 mocks();vi.mocked(api.personalGallery).mockResolvedValueOnce([entry]).mockResolvedValue([{...entry,eligible_count:0,images:[{...photo,eligibility:'ineligible'}]}]);vi.mocked(api.medicationFiles).mockResolvedValue(fileResponse(entry));vi.mocked(api.referencePhoto).mockResolvedValue(new Blob(['DEMO']));vi.mocked(api.retireReference).mockResolvedValue({...photo,eligibility:'ineligible'});
 render(<PersonalGalleryScreen/>);fireEvent.click(await screen.findByRole('button',{name:/DEMO Metformin/}));fireEvent.click(await screen.findByRole('button',{name:'Open photo preview: Pill reference photo'}));fireEvent.click(await screen.findByRole('button',{name:'Stop using for comparison'}));fireEvent.click(screen.getByRole('button',{name:'Stop comparison'}));await waitFor(()=>expect(api.retireReference).toHaveBeenCalledWith(photo.id));await waitFor(()=>expect(screen.getAllByText(/Removed from visual comparison/).length).toBeGreaterThan(0));expect(screen.queryByRole('button',{name:'Check this dose'})).toBeNull();
});

it('shows detail sections in clinical order and requests medication-scoped, read-only history',async()=>{
 mocks();const regimen:RegimenHistoryItem={regimen_id:'DEMO-plan',display_name:'DEMO Metformin',version_no:2,state:'active',medication_id:'DEMO-med',effective_from:null,effective_to:null,course_start_date:'2026-10-01',course_end_date:null,dose_amount:500,dose_unit:'mg',food_instruction:null,is_prn:false,local_times:['08:00'],patient_edited:true};
 vi.mocked(api.medicationHistory).mockResolvedValue({entries:[],next_cursor:null,window_start:null,window_end:'2026-10-17T00:00:00Z',as_of:'2026-10-17T00:00:00Z',scope:'stored_records_only',missing_plan_start:false});
 vi.mocked(api.inventory).mockResolvedValue({medication_id:'DEMO-med',unit:null,last_confirmed_stock:null,last_confirmed_at:null,estimated_remaining:null,daily_requirement:null,estimated_days:null,low_stock:false,estimate_note:'DEMO',transactions:[]});
 render(<MedicationDetail row={regimen} summary={{medication_id:'DEMO-med',regimen_id:'DEMO-plan',display_name:'DEMO Metformin',is_prn:false,version_no:2,identity_status:'user_reviewed_document',source_backed:true,dose_amount:500,dose_unit:'mg',frequency_rule:{kind:'daily',local_times:['08:00'],days_of_week:[]}}} onHistory={vi.fn()} onGallery={vi.fn()} onCheck={vi.fn()}/>);
 await screen.findByText('No records in this range.');expect(api.medicationHistory).toHaveBeenCalledWith({range_kind:'7',medication_id:'DEMO-med',regimen_id:'DEMO-plan'});
 const ids=['current-plan-title','medication-information-title','medication-inventory-title','medication-history-title','medication-evidence-title','regimen-management-title'];const headings=ids.map(id=>document.getElementById(id)!);expect(headings.slice(0,-1).every((heading,index)=>Boolean(heading.compareDocumentPosition(headings[index+1]!)&Node.DOCUMENT_POSITION_FOLLOWING))).toBe(true);
 expect(screen.getByText('No end date recorded')).toBeTruthy();expect(screen.queryByText('Partially unverified')).toBeNull();expect(screen.getByRole('button',{name:'Manage medication plan'})).toBeTruthy();expect(screen.getByRole('button',{name:'Stop tracking this regimen'})).toBeTruthy();
});
it('renders associated private reference photos in a carousel and opens a non-diagnostic preview',async()=>{
 mocks();vi.mocked(api.personalGallery).mockResolvedValue([entry]);vi.mocked(api.referencePhoto).mockResolvedValue(new Blob(['DEMO private image'],{type:'image/png'}));
 vi.mocked(api.medicationHistory).mockResolvedValue({entries:[],next_cursor:null,window_start:null,window_end:'2026-10-17T00:00:00Z',as_of:'2026-10-17T00:00:00Z',scope:'stored_records_only',missing_plan_start:false});
 vi.mocked(api.inventory).mockResolvedValue({medication_id:'DEMO-med',unit:null,last_confirmed_stock:null,last_confirmed_at:null,estimated_remaining:null,daily_requirement:null,estimated_days:null,low_stock:false,estimate_note:'DEMO',transactions:[]});
 render(<MedicationDetail row={{regimen_id:'DEMO-plan',display_name:'DEMO Metformin',version_no:1,state:'active',medication_id:'DEMO-med',effective_from:null,effective_to:null,course_start_date:null,course_end_date:null,dose_amount:1,dose_unit:'tablet',food_instruction:null,is_prn:false,local_times:['08:00']}} onHistory={vi.fn()} onGallery={vi.fn()} onCheck={vi.fn()}/>);
 const open=await screen.findByRole('button',{name:'Open photo preview: Pill reference photo'});expect(api.referencePhoto).toHaveBeenCalledWith(photo.id);expect(open.closest('[role="region"]')?.className).toContain('medication-photo-carousel');
 fireEvent.click(open);await screen.findByRole('dialog');expect(screen.getByText('This image is linked to this medication as reference evidence. It does not confirm ingestion.')).toBeTruthy();fireEvent.click(screen.getByRole('button',{name:'Close photo preview'}));await waitFor(()=>expect(screen.queryByRole('dialog')).toBeNull());
});
it('loads sourced general knowledge without replacing patient-specific identity',async()=>{
 mocks();const regimen:RegimenHistoryItem={regimen_id:'DEMO-plan',display_name:'DEMO Amlodipine',version_no:1,state:'active',medication_id:'DEMO-med',effective_from:null,effective_to:null,course_start_date:null,course_end_date:null,dose_amount:1,dose_unit:'tablet',food_instruction:null,is_prn:false,local_times:['08:00']};
 vi.mocked(api.medicationHistory).mockResolvedValue({entries:[],next_cursor:null,window_start:null,window_end:'2026-10-17T00:00:00Z',as_of:'2026-10-17T00:00:00Z',scope:'stored_records_only',missing_plan_start:false});
 vi.mocked(api.inventory).mockResolvedValue({medication_id:'DEMO-med',unit:null,last_confirmed_stock:null,last_confirmed_at:null,estimated_remaining:null,daily_requirement:null,estimated_days:null,low_stock:false,estimate_note:'DEMO',transactions:[]});
 const response:MedicationKnowledge={clarification_required:false,medication_id:'DEMO-med',regimen_id:'DEMO-plan',question:'general_use',medication_name:'DEMO Amlodipine',patient_safe_summary:'DEMO source-grounded summary',general_knowledge:{status:'matched',reason:'exact_ingredient_and_consistent_label_use',match_scope:'US_label_ingredient',candidate_count:1,sources:[{source_name:'openFDA Drug Label / SPL',market:'US',set_id:'DEMO-set',label_id:'DEMO-label',version:'2',effective_time:'20260101',retrieved_at:'2026-10-18T00:00:00Z',url:'https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=DEMO-set',api_url:'https://api.fda.gov/drug/label.json',sections:[{field:'indications_and_usage',text:'DEMO source excerpt',truncated:false}]}],use_statement:'DEMO source statement',use_statement_zh:'DEMO controlled translation',translation_status:'controlled_translation',personal_dosing_authority:false,regulatory_note:'DEMO general US label; not personal dosing.'},personal_instructions:null,personal_indication:null};
 vi.mocked(api.medicationKnowledge).mockResolvedValue(response);
 render(<MedicationDetail row={regimen} onHistory={vi.fn()} onGallery={vi.fn()} onCheck={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'View medication knowledge'}));await screen.findByText('DEMO source statement');
 expect(api.medicationKnowledge).toHaveBeenCalledWith('DEMO-med','en');expect(screen.getByText('DEMO source excerpt')).toBeTruthy();expect(screen.getAllByText('Not recorded').length).toBeGreaterThan(0);expect(screen.getByText('DEMO general US label; not personal dosing.')).toBeTruthy();
});
it('unfinished registration count includes identity-only source tasks, not just regimen drafts',async()=>{
 mocks();vi.mocked(api.evidenceTasks).mockResolvedValue([task,{...task,id:'DEMO-finished',status:'draft_created'}]);
 render(<MedicinesHub medications={[]} drafts={[]} setupCount={medicationSetupEntries([task,{...task,id:'DEMO-finished',status:'draft_created'}],[]).length} versions={[]} onOpen={vi.fn()}/>);
 await screen.findByText('1 medication setup needs review');expect(screen.getByRole('button',{name:/Finish medication setup/})).toBeTruthy();
});
it('does not present a failed gallery read as no medications or a request to register',async()=>{
 mocks();vi.mocked(api.personalGallery).mockRejectedValue(new Error('DEMO database service unavailable'));
 render(<PersonalGalleryScreen/>);await screen.findByRole('alert');
 expect(screen.queryByText('No medications match these filters.')).toBeNull();
 expect(screen.queryByText('Register a medication to begin your personal gallery.')).toBeNull();
});
it('keeps existing photos usable while unreleased file management is disabled',async()=>{
 mocks();vi.mocked(api.personalGallery).mockResolvedValue([entry]);
 vi.mocked(api.medicationFiles).mockResolvedValue({...fileResponse(entry),file_management_available:false});
 render(<PersonalGalleryScreen initialMedicationId="DEMO-med"/>);
 await screen.findByRole('heading',{name:/DEMO Metformin.*Medication Files/});
 expect(screen.getByRole('button',{name:'Add reference photo'})).toBeTruthy();
 expect(screen.queryByRole('button',{name:'Upload PDF'})).toBeNull();
});
it('offers the existing PDF workflow only when the service explicitly enables it',async()=>{
 mocks();vi.mocked(api.personalGallery).mockResolvedValue([entry]);
 vi.mocked(api.medicationFiles).mockResolvedValue({...fileResponse(entry),file_management_available:true});
 render(<PersonalGalleryScreen initialMedicationId="DEMO-med"/>);
 expect(await screen.findByRole('button',{name:'Upload PDF'})).toBeTruthy();
});
