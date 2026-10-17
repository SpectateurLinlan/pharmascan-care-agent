// @vitest-environment jsdom
// Independent review counterexamples; synthetic HTTP adapter, no provider calls.
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {api,type AgentMessageResponse} from '../api/client';
import {EnrollScreen} from './EnrollScreen';
import {AssistantScreen} from './AssistantScreen';

vi.mock('../api/client',()=>({ApiError:class extends Error{},api:{createDraft:vi.fn(),reviewDraft:vi.fn(),requestChallenge:vi.fn(),activate:vi.fn(),recentTurns:vi.fn(),sendMessage:vi.fn(),submitReport:vi.fn(),submitPrnReport:vi.fn(),doseDisplay:vi.fn()}}));
vi.mock('./VoiceInput',()=>({VoiceInput:()=>null}));
beforeEach(()=>{vi.resetAllMocks();vi.mocked(api.recentTurns).mockResolvedValue([]);});
afterEach(()=>{cleanup();vi.useRealTimers();vi.restoreAllMocks();});

function enterCheckedEvidence(){
 fireEvent.change(screen.getByLabelText('Medication name'),{target:{value:'DEMO first'}});
 fireEvent.change(screen.getByLabelText('Dose amount'),{target:{value:'1'}});
 fireEvent.change(screen.getByLabelText('Strength per tablet or capsule'),{target:{value:'500 mg'}});
 fireEvent.change(screen.getByLabelText('Original dose instructions'),{target:{value:'Take 1 tablet daily'}});
 fireEvent.click(screen.getByLabelText('I checked the strength, form and count against my original instructions.'));
}

it('never carries checked evidence when a different source begins enrollment',()=>{
 const props={sessionId:'DEMO-session',medications:null,onChanged:vi.fn()};
 const {rerender}=render(<EnrollScreen {...props}/>);enterCheckedEvidence();
 rerender(<EnrollScreen {...props} sourceSelection={{name:'DEMO second',preview:{source_document_id:'DEMO-source',source_kind:'package',provider:'SIMULATED',extraction_model:'SIMULATED',review_required:true,note:'demo_only',candidates:[]}}}/>);
 expect(screen.getByLabelText('Strength per tablet or capsule')).toHaveProperty('value','');
 expect(screen.getByLabelText('Original dose instructions')).toHaveProperty('value','');
 expect(screen.getByLabelText('I checked the strength, form and count against my original instructions.')).toHaveProperty('checked',false);
});

it('clears all patient-specific course evidence before adding another medicine',async()=>{
 vi.mocked(api.doseDisplay).mockResolvedValue({status:'calculated',total_amount:500,total_unit:'mg',reason:'demo_only'});
 vi.mocked(api.createDraft).mockResolvedValue({medication_id:'DEMO-m',regimen_id:'DEMO-r',source_id:'DEMO-s',state:'draft',missing_instructions:[],reviewable_field_ids:[],note:'demo_only'});
 vi.mocked(api.reviewDraft).mockResolvedValue({source_id:'DEMO-s',reviewed_field_count:1,note:'demo_only'});
 vi.mocked(api.requestChallenge).mockResolvedValue({regimen_id:'DEMO-r',challenge_id:'DEMO-c',session_id:'DEMO-session',session_state:'awaiting_confirmation',session_state_version:1,expires_at:'2099-01-01T00:00:00Z',summary:{medication_name:'DEMO first',dose_amount:1,dose_unit:'tablet',frequency:{kind:'daily',local_times:['08:00'],days_of_week:[]},is_prn:false,version_no:1,local_timezone:'Asia/Singapore'},note:'demo_only'});
 vi.mocked(api.activate).mockResolvedValue({regimen_id:'DEMO-r',state:'active',superseded_regimen_ids:[]});
 render(<EnrollScreen sessionId="DEMO-session" medications={null} onChanged={vi.fn()}/>);enterCheckedEvidence();
 fireEvent.change(screen.getByLabelText('Course start date'),{target:{value:'2026-10-16'}});fireEvent.change(screen.getByLabelText('Number of days'),{target:{value:'7'}});
 // Two perceived steps over the same backend states: one summary, then the
 // existing B14 challenge. There is no separate "create draft" step for the
 // patient to walk any more.
 fireEvent.click(screen.getByRole('button',{name:'Review and add'}));
 await screen.findByRole('button',{name:'Add this medication'});
 fireEvent.click(screen.getByLabelText('I have checked these details against my original instructions.'));
 fireEvent.click(screen.getByRole('button',{name:'Add this medication'}));
 await screen.findByRole('button',{name:'Yes, save this medication'});
 fireEvent.click(screen.getByRole('button',{name:'Yes, save this medication'}));
 await screen.findByText('Medication added. It now appears in your medication list.');
 // The form is replaced by the success card, so "cleared" is asserted where it
 // matters: on the form the patient gets when they add the next medicine.
 fireEvent.click(screen.getByRole('button',{name:'Add another'}));
 expect(screen.getByLabelText('Strength per tablet or capsule')).toHaveProperty('value','');
 expect(screen.getByLabelText('Course start date')).toHaveProperty('value','');
 expect(screen.getByLabelText('Number of days')).toHaveProperty('value','');
 expect(screen.getByLabelText('I checked the strength, form and count against my original instructions.')).toHaveProperty('checked',false);
});

it('does not attach an old saved-dose status to a different turn after the six-turn window moves',async()=>{
 const reply:AgentMessageResponse={message:'DEMO dose one',session_id:'DEMO-session',intent:'self_report',session_state:'awaiting_confirmation',requires_confirmation:true,mode:'deterministic_degraded',tool_traces:[],pending_report:{challenge_id:'DEMO-c',occurrence_id:'DEMO-o',regimen_id:'DEMO-r',idempotency_key:'DEMO-key',expires_at:'2099-01-01T00:00:00Z',summary:{medication_display_name:'DEMO first',dose_amount:1,dose_unit:'tablet',regimen_version_no:1,occurrence_due_at:null,local_due_time:'08:00',local_timezone:'Asia/Singapore',intake_status:'reported_taken',intake_status_label:'Patient reported taken',safety_notice:'Self-report only',ingestion_proven:false,visual_status:'not_checked'}}};
 vi.mocked(api.sendMessage).mockResolvedValueOnce(reply);
 render(<AssistantScreen sessionId="DEMO-session" onSession={vi.fn()}/>);
 const input=screen.getByLabelText('Review your message before sending');
 fireEvent.change(input,{target:{value:'DEMO first report'}});fireEvent.click(screen.getByRole('button',{name:'Send'}));await screen.findByRole('button',{name:'Confirm record'});
 fireEvent.click(screen.getByRole('button',{name:'Confirm record'}));await screen.findByText('Report saved');
 for(let i=2;i<=7;i++){
  vi.mocked(api.sendMessage).mockResolvedValueOnce({...reply,message:`DEMO unrelated ${i}`,intent:'unknown',requires_confirmation:false,pending_report:null,session_state:'idle'});
  fireEvent.change(input,{target:{value:`DEMO query ${i}`}});fireEvent.click(screen.getByRole('button',{name:'Send'}));await screen.findByText(`DEMO unrelated ${i}`);
 }
 expect(screen.queryByText('Report saved')).toBeNull();expect(api.submitReport).toHaveBeenCalledTimes(1);
 await waitFor(()=>expect(screen.getAllByRole('listitem').filter(el=>el.classList.contains('turn'))).toHaveLength(6));
});

it('releases the assistant close lock when an unconfirmed B14 summary expires',async()=>{
 vi.useFakeTimers();const close=vi.fn();
 vi.mocked(api.sendMessage).mockResolvedValue({message:'DEMO expiry',session_id:'DEMO-session',intent:'self_report',session_state:'awaiting_confirmation',requires_confirmation:true,mode:'deterministic_degraded',tool_traces:[],pending_report:{challenge_id:'DEMO-expire',occurrence_id:'DEMO-o',regimen_id:'DEMO-r',idempotency_key:'DEMO-key',expires_at:new Date(Date.now()+35000).toISOString(),summary:{medication_display_name:'DEMO first',dose_amount:1,dose_unit:'tablet',regimen_version_no:1,occurrence_due_at:null,local_due_time:'08:00',local_timezone:'Asia/Singapore',intake_status:'reported_taken',intake_status_label:'Patient reported taken',safety_notice:'Self-report only',ingestion_proven:false,visual_status:'not_checked'}}});
 render(<AssistantScreen sessionId="DEMO-session" onSession={vi.fn()} workspace onClose={close}/>);
 await act(async()=>{fireEvent.change(screen.getByLabelText('Review your message before sending'),{target:{value:'DEMO report'}});fireEvent.click(screen.getByRole('button',{name:'Send'}));});
 expect(screen.getByRole('button',{name:'Confirm record'})).toBeTruthy();expect(screen.getByRole('button',{name:'Back'})).toHaveProperty('disabled',true);
 expect(screen.getByRole('button',{name:'New conversation'})).toHaveProperty('disabled',true);expect(screen.getByRole('button',{name:'Conversation history'})).toHaveProperty('disabled',true);
 await act(async()=>{await vi.advanceTimersByTimeAsync(60000);});
 expect(screen.queryByRole('button',{name:'Confirm record'})).toBeNull();expect(screen.getByRole('button',{name:'Back'})).toHaveProperty('disabled',false);
 fireEvent.click(screen.getByRole('button',{name:'Back'}));expect(close).toHaveBeenCalledOnce();expect(api.submitReport).not.toHaveBeenCalled();expect(api.submitPrnReport).not.toHaveBeenCalled();
});
