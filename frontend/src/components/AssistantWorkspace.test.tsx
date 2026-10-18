// @vitest-environment jsdom
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {useState} from 'react';
import {AssistantScreen} from './AssistantScreen';
import {api,type AgentMessageResponse} from '../api/client';
vi.mock('../api/client',()=>({ApiError:class extends Error{},api:{recentTurns:vi.fn(),sendMessage:vi.fn(),newConversation:vi.fn(),conversationHistory:vi.fn(),agentUsage:vi.fn()}}));
beforeEach(()=>{localStorage.removeItem('pharmascan.agent-session');vi.mocked(api.recentTurns).mockResolvedValue([]);vi.mocked(api.conversationHistory).mockResolvedValue({entries:[],next_before:null});vi.mocked(api.agentUsage).mockResolvedValue({llm_user_turns:2,model_requests:2,limit:20,usage_date:'2026-10-18',next_reset_at:'2026-10-19T00:00:00+08:00'});});
afterEach(()=>{cleanup();vi.resetAllMocks();});
function Host({onViewTodayMedication}:{onViewTodayMedication?:()=>void}={}){const [workspace,setWorkspace]=useState(false),[session,setSession]=useState<string|null>('DEMO-session');return <AssistantScreen sessionId={session} onSession={setSession} todayEntry compact={!workspace} workspace={workspace} onExpand={()=>setWorkspace(true)} onClose={()=>setWorkspace(false)} {...(onViewTodayMedication?{onViewTodayMedication}:{})}/>;}
const reply:AgentMessageResponse={message:'DEMO answer',intent:'clarification',mode:'rules',tool_traces:[],session_id:'DEMO-session',session_state:'idle',requires_confirmation:false};
it('edits inline without opening, sends once, and displays the pending patient message immediately',async()=>{
 let finish!:(value:AgentMessageResponse)=>void;vi.mocked(api.sendMessage).mockReturnValue(new Promise(resolve=>{finish=resolve;}));render(<Host/>);
 const input=screen.getByRole('textbox');fireEvent.focus(input);fireEvent.change(input,{target:{value:'DEMO question'}});expect(screen.queryByRole('dialog')).toBeNull();
 fireEvent.keyDown(input,{key:'Enter'});fireEvent.keyDown(input,{key:'Enter'});
 expect(api.sendMessage).toHaveBeenCalledOnce();expect(screen.getByText('DEMO question')).toBeTruthy();expect(screen.queryByRole('dialog')).toBeNull();
 await act(async()=>finish(reply));await screen.findByText('DEMO answer');expect(screen.getAllByText('DEMO question')).toHaveLength(1);
 fireEvent.click(screen.getByRole('button',{name:'Open full chat'}));expect(document.querySelector('.conversation-workspace')).toBeTruthy();expect(screen.getByText('DEMO answer')).toBeTruthy();
 expect(screen.queryByLabelText('Save new conversations')).toBeNull();expect(api.conversationHistory).not.toHaveBeenCalled();
});
it('creates a real new session only on request, preserves the unsent draft, and retains state on failure',async()=>{
 render(<Host/>);fireEvent.click(screen.getByRole('button',{name:'Open full chat'}));
 fireEvent.change(screen.getByRole('textbox'),{target:{value:'DEMO retained draft'}});
 vi.mocked(api.newConversation).mockRejectedValueOnce(new Error('DEMO unavailable'));
 fireEvent.click(screen.getByRole('button',{name:'New conversation'}));await screen.findByText(/DEMO unavailable/);expect(screen.getByRole('textbox')).toHaveProperty('value','DEMO retained draft');
 vi.mocked(api.newConversation).mockResolvedValue({session_id:'DEMO-new',patient_id:'DEMO-owner',demo_only:true,seeded_medication_count:0,note:'SIMULATED'});
 fireEvent.click(screen.getByRole('button',{name:'New conversation'}));await waitFor(()=>expect(localStorage.getItem('pharmascan.agent-session')).toBe('DEMO-new'));
 expect(screen.getByRole('textbox')).toHaveProperty('value','');expect(api.sendMessage).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'Return to unsent conversation'}));expect(screen.getByRole('textbox')).toHaveProperty('value','DEMO retained draft');
 fireEvent.click(screen.getByRole('button',{name:'Conversation history'}));await screen.findByText('Saving is off. No saved messages are available.');
 fireEvent.click(screen.getByRole('button',{name:'Back to current conversation'}));expect(screen.getByRole('textbox')).toHaveProperty('value','DEMO retained draft');
});

it('opens a saved exchange read-only without replacing the current session or draft',async()=>{
 const entry={id:'DEMO-history-row',created_at:'2026-10-16T23:30:00Z',user_text:'DEMO saved question',assistant_text:'DEMO saved answer'};
 vi.mocked(api.conversationHistory).mockResolvedValue({entries:[entry],next_before:null});render(<Host/>);
 fireEvent.click(screen.getByRole('button',{name:'Open full chat'}));fireEvent.change(screen.getByRole('textbox'),{target:{value:'DEMO current draft'}});
 fireEvent.click(screen.getByRole('button',{name:'Conversation history'}));await screen.findByText('DEMO saved question');
 fireEvent.click(screen.getByRole('button',{name:/DEMO saved question/}));expect(screen.getByText('DEMO saved answer')).toBeTruthy();
 expect(screen.queryByRole('textbox')).toBeNull();expect(screen.queryByRole('navigation',{name:'Assistant tasks'})).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'Back to current conversation'}));expect(screen.getByRole('textbox')).toHaveProperty('value','DEMO current draft');expect(localStorage.getItem('pharmascan.agent-session')).toBeNull();expect(api.sendMessage).not.toHaveBeenCalled();
});

it('keeps quick tasks by the multiline composer and exposes a retry using the same send identity',async()=>{
 vi.mocked(api.sendMessage).mockRejectedValueOnce(new Error('DEMO C1 network failure')).mockResolvedValueOnce(reply);
 render(<Host/>);fireEvent.click(screen.getByRole('button',{name:'Open full chat'}));
 const input=screen.getByRole('textbox');expect(input.tagName).toBe('TEXTAREA');
 const bottom=document.querySelector('.conversation-interaction')!;
 expect(bottom.contains(screen.getByRole('button',{name:'View today’s medication'}))).toBe(true);expect(bottom.contains(input)).toBe(true);
 fireEvent.change(input,{target:{value:'DEMO first line\nDEMO second line'}});
 fireEvent.keyDown(input,{key:'Enter',shiftKey:true});expect(api.sendMessage).not.toHaveBeenCalled();
 fireEvent.keyDown(input,{key:'Enter'});await screen.findByText('DEMO C1 network failure');
 expect(input).toHaveProperty('value','DEMO first line\nDEMO second line');
 const request=vi.mocked(api.sendMessage).mock.calls[0]![0];
 fireEvent.click(screen.getByRole('button',{name:'Retry sending'}));await screen.findByText('DEMO answer');
 expect(vi.mocked(api.sendMessage).mock.calls[1]![0].client_turn_id).toBe(request.client_turn_id);
 expect(input).toHaveProperty('value','');expect(screen.queryByRole('button',{name:'Retry sending'})).toBeNull();
});

it('opens Today at its medication section from the medication shortcut',()=>{
 const viewTodayMedication=vi.fn();render(<Host onViewTodayMedication={viewTodayMedication}/>);
 fireEvent.click(screen.getByRole('button',{name:'View today’s medication'}));
 expect(viewTodayMedication).toHaveBeenCalledOnce();expect(api.sendMessage).not.toHaveBeenCalled();
});

it('does not portal a retained assistant error over another page while the assistant is inactive',async()=>{
 vi.mocked(api.recentTurns).mockRejectedValueOnce(new Error('DEMO restore failure'));
 const view=render(<AssistantScreen sessionId="DEMO-session" onSession={()=>{}} compact active ownerId="DEMO-owner"/>);
 expect(await screen.findByRole('alert')).toBeTruthy();
 view.rerender(<AssistantScreen sessionId="DEMO-session" onSession={()=>{}} compact active={false} ownerId="DEMO-owner"/>);
 expect(screen.queryByRole('alert')).toBeNull();
});

it('continues a typed medicine choice and retries the same request while keeping a separate composer draft',async()=>{
 const choice={id:'DEMO-choice',question:'general_use' as const,expires_at:new Date(Date.now()+600000).toISOString(),options:[{medication_id:'DEMO-medication',regimen_id:'DEMO-regimen',display_name:'DEMO medicine',label:'DEMO medicine 10 mg'}]};
 vi.mocked(api.sendMessage).mockResolvedValueOnce({...reply,message:'Which medicine?',medication_choice:choice}).mockRejectedValueOnce(new Error('DEMO choice network failure')).mockResolvedValueOnce(reply);
 render(<Host/>);fireEvent.click(screen.getByRole('button',{name:'Open full chat'}));
 fireEvent.change(screen.getByRole('textbox'),{target:{value:'What is this medicine for?'}});fireEvent.keyDown(screen.getByRole('textbox'),{key:'Enter'});
 const option=await screen.findByRole('button',{name:'DEMO medicine 10 mg'});
 fireEvent.change(screen.getByRole('textbox'),{target:{value:'DEMO keep this separate draft'}});fireEvent.click(option);
 await screen.findByText('DEMO choice network failure');fireEvent.click(screen.getByRole('button',{name:'Retry sending'}));
 await screen.findByText('DEMO answer');const calls=vi.mocked(api.sendMessage).mock.calls;
 expect(calls[1]![0].medication_selection).toEqual({choice_id:'DEMO-choice',medication_id:'DEMO-medication'});
 expect(calls[2]![0].client_turn_id).toBe(calls[1]![0].client_turn_id);expect(calls[2]![0].medication_selection).toEqual(calls[1]![0].medication_selection);
 expect(screen.getByRole('textbox')).toHaveProperty('value','DEMO keep this separate draft');expect(screen.queryByRole('button',{name:'DEMO medicine 10 mg'})).toBeNull();
});

it('folds restored and current exchanges together after leaving and returning to Today',async()=>{
 vi.mocked(api.recentTurns).mockResolvedValue([{user:'DEMO older question',assistant:'DEMO older answer'}]);
 vi.mocked(api.sendMessage).mockResolvedValue(reply);
 const {rerender}=render(<AssistantScreen sessionId="DEMO-session" onSession={()=>{}} todayEntry compact active ownerId="DEMO-owner"/>);
 await waitFor(()=>expect(document.querySelector('details.recent-chat')).toBeTruthy());
 fireEvent.change(screen.getByRole('textbox'),{target:{value:'DEMO follow-up question'}});fireEvent.keyDown(screen.getByRole('textbox'),{key:'Enter'});
 await screen.findByText('DEMO answer');
 const details=document.querySelector<HTMLDetailsElement>('details.recent-chat')!;expect(details.open).toBe(true);
 expect(details.contains(screen.getByText('DEMO older question'))).toBe(true);expect(details.contains(screen.getByText('DEMO follow-up question'))).toBe(true);
 rerender(<AssistantScreen sessionId="DEMO-session" onSession={()=>{}} todayEntry={false} compact active={false} ownerId="DEMO-owner"/>);
 rerender(<AssistantScreen sessionId="DEMO-session" onSession={()=>{}} todayEntry compact active ownerId="DEMO-owner"/>);
 expect(document.querySelector<HTMLDetailsElement>('details.recent-chat')?.open).toBe(false);
});

it('keeps the allowance with bottom controls outside the message timeline',async()=>{
 render(<Host/>);fireEvent.click(screen.getByRole('button',{name:'Open full chat'}));
 const allowance=await screen.findByText(/AI conversations left today.*18 \/ 20/);
 expect(document.querySelector('.conversation-interaction')!.contains(allowance)).toBe(true);
 expect(document.querySelector('.conversation-scroll')!.contains(allowance)).toBe(false);
});

it('ignores an older recent-turns response after the patient starts a new session',async()=>{
 let finish!:(rows:Array<{user:string;assistant:string}>)=>void;
 vi.mocked(api.recentTurns).mockReturnValueOnce(new Promise(resolve=>{finish=resolve;}));
 vi.mocked(api.newConversation).mockResolvedValue({session_id:'DEMO-new',patient_id:'DEMO-owner',demo_only:true,seeded_medication_count:0,note:'SIMULATED'});
 render(<Host/>);fireEvent.click(screen.getByRole('button',{name:'Open full chat'}));fireEvent.click(screen.getByRole('button',{name:'New conversation'}));
 await waitFor(()=>expect(localStorage.getItem('pharmascan.agent-session')).toBe('DEMO-new'));
 await act(async()=>finish([{user:'DEMO old context',assistant:'DEMO old answer'}]));
 expect(screen.queryByText('DEMO old context')).toBeNull();expect(api.sendMessage).not.toHaveBeenCalled();
});
