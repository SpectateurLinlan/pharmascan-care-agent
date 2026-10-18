// @vitest-environment jsdom
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {act,cleanup,fireEvent,render,screen} from '@testing-library/react';
import {AssistantScreen} from './AssistantScreen';
import {api,type AgentMessageResponse} from '../api/client';
vi.mock('../api/client',()=>({ApiError:class extends Error{},api:{recentTurns:vi.fn(),sendMessage:vi.fn()}}));
beforeEach(()=>{localStorage.clear();vi.resetAllMocks();vi.mocked(api.recentTurns).mockResolvedValue([]);});
afterEach(cleanup);
const reply:AgentMessageResponse={message:'DEMO saved answer',conversation_id:'DEMO-thread',history_saved:true,intent:'clarification',mode:'rules',tool_traces:[],session_id:'DEMO-session',session_state:'collecting',requires_confirmation:false};

it('retains the same message identity after an ambiguous network failure',async()=>{
 vi.mocked(api.sendMessage).mockRejectedValueOnce(new Error('DEMO network interrupted')).mockResolvedValueOnce(reply);
 render(<AssistantScreen ownerId="DEMO-A" sessionId={null} onSession={vi.fn()}/>);
 fireEvent.change(screen.getByRole('textbox'),{target:{value:'DEMO retry text'}});
 fireEvent.click(screen.getByRole('button',{name:'Send'}));await screen.findByText('DEMO network interrupted');
 const first=vi.mocked(api.sendMessage).mock.calls[0]![0];
 fireEvent.click(screen.getByRole('button',{name:'Send'}));await screen.findByText('DEMO saved answer');
 expect(api.sendMessage).toHaveBeenCalledTimes(2);
 expect(vi.mocked(api.sendMessage).mock.calls[1]![0].client_turn_id).toBe(first.client_turn_id);
 expect(localStorage.getItem('pharmascan.conversation:DEMO-A')).toBe('DEMO-thread');
});

it('does not silently truncate a long programmatic or voice draft',async()=>{
 render(<AssistantScreen ownerId="DEMO-A" sessionId={null} onSession={vi.fn()}/>);
 const text='患'.repeat(2001);
 fireEvent.change(screen.getByRole('textbox'),{target:{value:text}});
 fireEvent.click(screen.getByRole('button',{name:'Send'}));
 await screen.findByText('Keep your message within 2000 characters.');
 expect(screen.getByRole('textbox')).toHaveProperty('value',text);
 expect(api.sendMessage).not.toHaveBeenCalled();
});

it('ignores a pending previous-patient reply and never saves its conversation selection to the next patient',async()=>{
 let finish!:(value:AgentMessageResponse)=>void;
 vi.mocked(api.sendMessage).mockReturnValue(new Promise(resolve=>{finish=resolve;}));
 const {rerender}=render(<AssistantScreen ownerId="DEMO-A" sessionId={null} onSession={vi.fn()}/>);
 fireEvent.change(screen.getByRole('textbox'),{target:{value:'DEMO A private words'}});fireEvent.click(screen.getByRole('button',{name:'Send'}));
 rerender(<AssistantScreen ownerId="DEMO-B" sessionId={null} onSession={vi.fn()}/>);
 await act(async()=>finish(reply));
 expect(screen.queryByText('DEMO saved answer')).toBeNull();
 expect(screen.queryByText('DEMO A private words')).toBeNull();
 expect(localStorage.getItem('pharmascan.conversation:DEMO-B')).toBeNull();
});
