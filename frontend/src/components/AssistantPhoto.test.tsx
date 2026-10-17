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
 expect(api.sendMessage).toHaveBeenCalledWith(expect.objectContaining({text:'What does this label say?'}));
 const request=vi.mocked(api.sendMessage).mock.calls[0]![0];
 expect(request.photo_context?.products[0]?.printed_directions).toBe('Take once daily');
 expect(request.text).not.toContain('Take once daily');expect(request.text).not.toContain('JSON');
 expect(api.sendMessage).toHaveBeenCalledWith(expect.objectContaining({text:expect.stringContaining('What does this label say?')}));
 expect(screen.getByText('Photo attached: DEMO-label.png')).toBeTruthy();
});

it.each(['package','prescription','pharmacy_label'] as const)('preserves %s routing and patient words without technical context',async kind=>{
 vi.mocked(api.checkInput).mockResolvedValue({image_type:'document',checked:true,abstained:false,suggested_workflow:'source_review',message:'DEMO private technical route'});
 vi.mocked(api.sourcePreview).mockResolvedValue({source_document_id:'DEMO-source',source_kind:kind,provider:'SIMULATED',extraction_model:'SIMULATED',review_required:true,note:'DEMO technical note',candidates:[]});
 localStorage.setItem('pharmascan.image-processing.v1.DEMO-owner','allowed');
 render(<AssistantScreen ownerId="DEMO-owner" sessionId={null} onSession={vi.fn()} compact={false}/>);
 attachPhoto();fireEvent.change(screen.getByLabelText('Photo type'),{target:{value:kind}});
 const words=kind==='prescription'?'请帮我看一下这张处方。':'What does this photo show?';
 fireEvent.change(screen.getByLabelText('Review your message before sending'),{target:{value:words}});
 fireEvent.click(screen.getByRole('button',{name:'Send'}));await screen.findByText('I can help review this source.');
 expect(api.sourcePreview).toHaveBeenCalledWith(expect.any(File),kind);
 expect(api.sendMessage).toHaveBeenCalledWith(expect.objectContaining({text:words,photo_context:expect.objectContaining({source_kind:kind,provider:'SIMULATED'})}));
 expect(document.querySelector('.user-message')?.textContent).toContain(words);
 expect(document.querySelector('.user-message')?.textContent).not.toContain('SIMULATED');
});

it('does not analyze an unconsented photo and keeps uncertain routing separate',async()=>{
 vi.mocked(api.checkInput).mockResolvedValue({image_type:'unchecked',checked:true,abstained:true,suggested_workflow:'ask_patient',message:'DEMO technical route'});
 render(<AssistantScreen ownerId="DEMO-owner" sessionId={null} onSession={vi.fn()} compact={false}/>);attachPhoto();
 fireEvent.click(screen.getByRole('button',{name:'Send'}));expect(api.checkInput).not.toHaveBeenCalled();expect(api.sendMessage).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('checkbox',{name:'Allow photo processing. The image is not saved; extracted details may appear in saved chats.'}));
 fireEvent.click(screen.getByRole('button',{name:'Send'}));await screen.findByText('I can help review this source.');
 expect(api.sourcePreview).not.toHaveBeenCalled();expect(api.visualCheck).not.toHaveBeenCalled();
 expect(api.sendMessage).toHaveBeenCalledWith(expect.objectContaining({text:'',photo_context:expect.objectContaining({workflow:'ask_patient',products:[]})}));
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
 expect(api.sendMessage).toHaveBeenCalledWith(expect.objectContaining({text:'',photo_context:expect.objectContaining({visual:expect.objectContaining({reason:'No reviewed personal reference'})})}));
});
