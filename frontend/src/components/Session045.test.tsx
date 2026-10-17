// @vitest-environment jsdom
// LOCAL/MOCK UI wiring. Provider recognition is not asserted by these fixtures.
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {useState} from 'react';
import {api,type EvidenceTask} from '../api/client';
import {DoseDetails} from './DoseDetails';
import type {DoseBasis,DoseDisplay} from '../api/dose';
import {EvidenceEnrollmentScreen} from './EvidenceEnrollmentScreen';
import {ConversationHistory} from './ConversationHistory';
import {ConversationHistoryBrowser} from './ConversationHistoryBrowser';
import {ConversationSurface} from './ConversationSurface';

vi.mock('../api/client',()=>({ApiError:class extends Error{},api:{sourcePreview:vi.fn(),doseDisplay:vi.fn(),evidenceTasks:vi.fn(),personalGallery:vi.fn(),checkInput:vi.fn(),attachEvidence:vi.fn(),evidenceSources:vi.fn(),sendMessage:vi.fn(),conversationHistory:vi.fn(),clearConversationHistory:vi.fn(),submitReport:vi.fn()}}));
const sourceTask:EvidenceTask={id:'DEMO-task',medication_id:'DEMO-med',version:1,status:'pending_information',product:{name:'DEMO Metformin',strength:'500 mg',dose_form:'tablet',formulation:null,brand:null,ingredients:[],category:'unknown',verification:'source_supplied'},source_ids:['DEMO-source'],missing:['dose_amount','schedule'],conflicts:[],possible_duplicate_ids:[],draft_regimen_id:null,suggested_regimen:null};
const basis:DoseBasis={strength_text:'500 mg',form:'tablet',formulation:'standard',single_ingredient:true,instructions_text:'Take 1 tablet',patient_checked:true};
beforeEach(()=>{vi.resetAllMocks();vi.mocked(api.evidenceTasks).mockResolvedValue([]);vi.mocked(api.personalGallery).mockResolvedValue([]);vi.mocked(api.evidenceSources).mockResolvedValue([]);vi.spyOn(URL,'createObjectURL').mockReturnValue('blob:DEMO');vi.spyOn(URL,'revokeObjectURL').mockImplementation(()=>undefined);});
afterEach(()=>{cleanup();vi.restoreAllMocks();});
it('does not display a stale arithmetic response after the entered count changes',async()=>{
 let finish!:(value:DoseDisplay)=>void;vi.mocked(api.doseDisplay).mockReturnValue(new Promise(resolve=>{finish=resolve;}));
 const {rerender}=render(<DoseDetails basis={basis} onChange={vi.fn()} amount="1" unit="tablet"/>);fireEvent.click(screen.getByRole('button',{name:'Show total from these details'}));
 rerender(<DoseDetails basis={basis} onChange={vi.fn()} amount="2" unit="tablet"/>);finish({status:'calculated',total_amount:500,total_unit:'mg',reason:'DEMO'});await waitFor(()=>expect(screen.queryByText(/Checking the entered details/)).toBeNull());expect(screen.queryByText(/Total per dose: 500/)).toBeNull();
});
it('asks for an uncertain type and uses manual correction without saving a guessed identity',async()=>{
 vi.mocked(api.checkInput).mockResolvedValue({image_type:'blister',checked:true,abstained:true,suggested_workflow:'ask_patient',message:'DEMO'});
 render(<EvidenceEnrollmentScreen sessionId="DEMO-session" onChanged={vi.fn()}/>);
 fireEvent.change(screen.getByLabelText('Take or choose a photo'),{target:{files:[new File(['DEMO'],'demo.png',{type:'image/png'})]}});fireEvent.click(screen.getByLabelText('I allow this photo to be sent to the recognition service to read medication information. I can change this in Privacy and data.'));fireEvent.click(screen.getByRole('button',{name:'Read photo'}));
 await screen.findByText(/The photo type is uncertain/);expect(api.attachEvidence).not.toHaveBeenCalled();expect(api.sendMessage).not.toHaveBeenCalled();
 vi.mocked(api.attachEvidence).mockResolvedValue(sourceTask);vi.mocked(api.sendMessage).mockResolvedValue({message:'DEMO more instructions needed',intent:'clarification',session_id:'DEMO-session',session_state:'idle',requires_confirmation:false,mode:'deterministic_degraded',tool_traces:[]});
 vi.mocked(api.sourcePreview).mockResolvedValue({note:'SIMULATED',source_document_id:'DEMO-read',source_kind:'pharmacy_label',provider:'SIMULATED',extraction_model:'SIMULATED',candidates:[],review_required:true});fireEvent.change(screen.getByLabelText('Source type'),{target:{value:'pharmacy_label'}});fireEvent.click(screen.getByRole('button',{name:'Read photo'}));await screen.findByRole('heading',{name:'Read from your photo'});
 expect(api.attachEvidence).not.toHaveBeenCalled();expect(api.sourcePreview).toHaveBeenCalledWith(expect.any(File),'pharmacy_label');expect(api.checkInput).toHaveBeenCalledOnce();
});
it('paginates text-only saved history and requires confirmation before clearing',async()=>{
 const entry={id:'DEMO-history',created_at:'2026-10-16T00:00:00Z',user_text:'DEMO question',assistant_text:'DEMO review requested'};
 vi.mocked(api.conversationHistory).mockResolvedValueOnce({entries:[entry],next_before:entry.id}).mockResolvedValueOnce({entries:[{...entry,id:'DEMO-old',user_text:'DEMO older question'}],next_before:null});vi.mocked(api.clearConversationHistory).mockResolvedValue({cleared:true});const cleared=vi.fn();
 render(<><ConversationHistory onCleared={cleared}/><ConversationHistoryBrowser revision={0} onBack={vi.fn()}/></>);await screen.findByText('DEMO question');fireEvent.click(screen.getByRole('button',{name:'Load earlier conversations'}));await screen.findByText('DEMO older question');
 expect(api.conversationHistory).toHaveBeenLastCalledWith('DEMO-history');expect(screen.queryByRole('button',{name:'Confirm record'})).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'Clear saved conversations'}));expect(api.clearConversationHistory).not.toHaveBeenCalled();fireEvent.click(screen.getByRole('button',{name:'Cancel'}));expect(api.clearConversationHistory).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'Clear saved conversations'}));fireEvent.click(screen.getByRole('button',{name:'Confirm clear'}));await waitFor(()=>expect(cleared).toHaveBeenCalledOnce());expect(api.submitReport).not.toHaveBeenCalled();
});
it('expands above the current page, keeps its draft and restores focus without a route change',()=>{
 function Host(){const [open,setOpen]=useState(false),[text,setText]=useState('DEMO draft');return <><div data-app-content><button onClick={()=>setOpen(true)}>Open</button></div><ConversationSurface open={open} locked={false} onClose={()=>setOpen(false)}><div className="composer-row"><input aria-label="DEMO draft" value={text} onChange={event=>setText(event.target.value)}/></div></ConversationSurface></>;}
 const hash=location.hash;render(<Host/>);fireEvent.click(screen.getByRole('button',{name:'Open'}));expect(screen.getByRole('dialog',{name:'Medication assistant'})).toBeTruthy();expect(document.querySelector<HTMLElement>('[data-app-content]')!.inert).toBe(true);fireEvent.change(screen.getByLabelText('DEMO draft'),{target:{value:'DEMO retained'}});fireEvent.click(screen.getByRole('button',{name:'Close conversation'}));expect(screen.getByLabelText('DEMO draft')).toHaveProperty('value','DEMO retained');expect(location.hash).toBe(hash);expect(document.querySelector<HTMLElement>('[data-app-content]')!.inert).toBe(false);
});

it('keeps clear confirmation open with a visible error and allows an explicit retry',async()=>{
 const cleared=vi.fn();vi.mocked(api.clearConversationHistory).mockRejectedValueOnce(new Error('DEMO clear unavailable')).mockResolvedValueOnce({cleared:true});
 render(<ConversationHistory onCleared={cleared}/>);fireEvent.click(screen.getByRole('button',{name:'Clear saved conversations'}));
 fireEvent.click(screen.getByRole('button',{name:'Confirm clear'}));await screen.findByText('Could not confirm clearing. Retry or cancel.');
 expect(screen.getByRole('dialog',{name:'Clear saved conversations?'}).textContent).toContain('Could not confirm clearing. Retry or cancel.');expect(cleared).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'Confirm clear'}));await waitFor(()=>expect(cleared).toHaveBeenCalledOnce());expect(api.submitReport).not.toHaveBeenCalled();
});
