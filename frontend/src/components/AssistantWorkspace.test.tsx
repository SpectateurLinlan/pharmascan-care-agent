// @vitest-environment jsdom
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {useState} from 'react';
import {AssistantScreen} from './AssistantScreen';
import {api,type AgentMessageResponse} from '../api/client';
vi.mock('../api/client',()=>({ApiError:class extends Error{},api:{recentTurns:vi.fn(),sendMessage:vi.fn(),newConversation:vi.fn(),conversationHistory:vi.fn()}}));
beforeEach(()=>{vi.mocked(api.recentTurns).mockResolvedValue([]);vi.mocked(api.conversationHistory).mockResolvedValue({entries:[],next_before:null});});
afterEach(()=>{cleanup();vi.resetAllMocks();});
function Host(){const [open,setOpen]=useState(false),[session,setSession]=useState<string|null>('DEMO-session');return <AssistantScreen sessionId={session} onSession={setSession} todayEntry compact={!open} onExpand={()=>setOpen(true)} onClose={()=>setOpen(false)}/>;}
const reply:AgentMessageResponse={message:'DEMO answer',intent:'clarification',mode:'rules',tool_traces:[],session_id:'DEMO-session',session_state:'idle',requires_confirmation:false};
it('edits inline without opening, sends once, and displays the pending patient message immediately',async()=>{
 let finish!:(value:AgentMessageResponse)=>void;vi.mocked(api.sendMessage).mockReturnValue(new Promise(resolve=>{finish=resolve;}));render(<Host/>);
 const input=screen.getByRole('textbox');fireEvent.focus(input);fireEvent.change(input,{target:{value:'DEMO question'}});expect(screen.queryByRole('dialog')).toBeNull();
 fireEvent.keyDown(input,{key:'Enter'});fireEvent.keyDown(input,{key:'Enter'});
 expect(api.sendMessage).toHaveBeenCalledOnce();expect(screen.getByRole('dialog').textContent).toContain('DEMO question');
 await act(async()=>finish(reply));await screen.findByText('DEMO answer');expect(screen.getAllByText('DEMO question')).toHaveLength(1);
 expect(screen.queryByLabelText('Save new conversations')).toBeNull();expect(api.conversationHistory).not.toHaveBeenCalled();
});
it('creates a real new session only on request, preserves the unsent draft, and retains state on failure',async()=>{
 render(<Host/>);fireEvent.click(screen.getByRole('button',{name:'Open conversation'}));
 fireEvent.change(screen.getByRole('textbox'),{target:{value:'DEMO retained draft'}});
 vi.mocked(api.newConversation).mockRejectedValueOnce(new Error('DEMO unavailable'));
 fireEvent.click(screen.getByRole('button',{name:'New conversation'}));await screen.findByText(/DEMO unavailable/);expect(screen.getByRole('textbox')).toHaveProperty('value','DEMO retained draft');
 vi.mocked(api.newConversation).mockResolvedValue({session_id:'DEMO-new',patient_id:'DEMO-owner',demo_only:true,seeded_medication_count:0,note:'SIMULATED'});
 fireEvent.click(screen.getByRole('button',{name:'New conversation'}));await waitFor(()=>expect(localStorage.getItem('pharmascan.agent-session')).toBe('DEMO-new'));
 expect(screen.getByRole('textbox')).toHaveProperty('value','DEMO retained draft');expect(api.sendMessage).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'Conversation history'}));await screen.findByText('Saving is off. No saved messages are available.');
 fireEvent.click(screen.getByRole('button',{name:'Back to current conversation'}));expect(screen.getByRole('textbox')).toHaveProperty('value','DEMO retained draft');
});

it('ignores an older recent-turns response after the patient starts a new session',async()=>{
 let finish!:(rows:Array<{user:string;assistant:string}>)=>void;
 vi.mocked(api.recentTurns).mockReturnValueOnce(new Promise(resolve=>{finish=resolve;}));
 vi.mocked(api.newConversation).mockResolvedValue({session_id:'DEMO-new',patient_id:'DEMO-owner',demo_only:true,seeded_medication_count:0,note:'SIMULATED'});
 render(<Host/>);fireEvent.click(screen.getByRole('button',{name:'Open conversation'}));fireEvent.click(screen.getByRole('button',{name:'New conversation'}));
 await waitFor(()=>expect(localStorage.getItem('pharmascan.agent-session')).toBe('DEMO-new'));
 await act(async()=>finish([{user:'DEMO old context',assistant:'DEMO old answer'}]));
 expect(screen.queryByText('DEMO old context')).toBeNull();expect(api.sendMessage).not.toHaveBeenCalled();
});
