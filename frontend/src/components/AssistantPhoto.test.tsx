// @vitest-environment jsdom
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import {api} from '../api/client';
import {AssistantScreen} from './AssistantScreen';

vi.mock('../api/client',()=>({api:{agentUsage:vi.fn(),recentTurns:vi.fn(),sendMessage:vi.fn(),checkInput:vi.fn(),sourcePreview:vi.fn(),visualCheck:vi.fn()}}));
vi.mock('./VoiceInput',()=>({VoiceInput:()=>null}));

beforeEach(()=>{
 vi.resetAllMocks();localStorage.clear();
 vi.mocked(api.agentUsage).mockResolvedValue({usage_date:'2026-10-16',llm_user_turns:0,model_requests:0,limit:20,next_reset_at:'2026-10-16T16:00:00Z'});
 vi.mocked(api.sendMessage).mockResolvedValue({message:'I can help review this source.',session_id:'DEMO-session',intent:'clarification',session_state:'idle',requires_confirmation:false,mode:'gemini',tool_traces:[]} as never);
});
afterEach(()=>{cleanup();localStorage.clear();});

function attachPhoto(){
 const file=new File(['synthetic image bytes'],'DEMO-label.png',{type:'image/png'});
 fireEvent.change(screen.getByLabelText('Choose a photo'),{target:{files:[file]}});
 return file;
}

it('routes an attached label photo through source review and keeps the patient question in the chat',async()=>{
 vi.mocked(api.checkInput).mockResolvedValue({image_type:'printed',checked:true,abstained:false,suggested_workflow:'source_review',message:'Text-bearing medicine source'});
 vi.mocked(api.sourcePreview).mockResolvedValue({source_document_id:'DEMO-source',source_kind:'pharmacy_label',provider:'SIMULATED',extraction_model:'SIMULATED',review_required:true,note:'Needs patient review',candidates:[{product:{name:'DEMO medicine',strength:'5 mg',source_lines:['Take once daily']},regimen_evidence:{directions:{value:'Take once daily',line:'Take once daily'},dose_amount:null,frequency:null,administration_times:null,duration:null},review_status:'extracted',can_activate_regimen:false}]} as never);
 render(<AssistantScreen ownerId="DEMO-owner" sessionId={null} onSession={vi.fn()} compact={false}/>);
 attachPhoto();
 fireEvent.change(screen.getByLabelText('Review your message before sending'),{target:{value:'What does this label say?'}});
 fireEvent.click(screen.getByRole('checkbox',{name:'Allow photo processing. The image is not saved; extracted details may appear in saved chats.'}));
 fireEvent.click(screen.getByRole('button',{name:'Send'}));
 await screen.findByText('I can help review this source.');
 expect(api.checkInput).toHaveBeenCalledOnce();
 expect(api.sourcePreview).toHaveBeenCalledWith(expect.any(File),'pharmacy_label');
 expect(api.sendMessage).toHaveBeenCalledWith(expect.objectContaining({text:expect.stringContaining('unverified evidence')}));
 expect(api.sendMessage).toHaveBeenCalledWith(expect.objectContaining({text:expect.stringContaining('What does this label say?')}));
 expect(screen.getByText('Photo attached: DEMO-label.png')).toBeTruthy();
});

it('uses the visual evidence API for pill images instead of opening medication enrollment',async()=>{
 vi.mocked(api.checkInput).mockResolvedValue({image_type:'loose_pills',checked:true,abstained:false,suggested_workflow:'pill_evidence',message:'Pill image'});
 vi.mocked(api.visualCheck).mockResolvedValue({decision:'unknown',selected_medication:null,comparison_available:false,reason:'No reviewed personal reference',candidates:[],count_reliable:false,ingestion_proven:false,safe_to_take_confirmed:false,next_action:'Review the medication source'});
 localStorage.setItem('pharmascan.image-processing.v1.DEMO-owner','allowed');
 render(<AssistantScreen ownerId="DEMO-owner" sessionId={null} onSession={vi.fn()} compact={false}/>);
 attachPhoto();fireEvent.click(screen.getByRole('button',{name:'Send'}));
 await screen.findByText('I can help review this source.');
 expect(api.visualCheck).toHaveBeenCalledWith(expect.any(File),null);
 expect(api.sourcePreview).not.toHaveBeenCalled();
 expect(api.sendMessage).toHaveBeenCalledWith(expect.objectContaining({text:expect.stringContaining('No reviewed personal reference')}));
});
