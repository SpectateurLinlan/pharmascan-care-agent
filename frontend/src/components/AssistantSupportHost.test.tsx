// @vitest-environment jsdom
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {api} from '../api/client';
import {workflowApi,type WorkflowView} from '../api/assistantWorkflows';
import {AssistantScreen} from './AssistantScreen';
vi.mock('../api/client',()=>({ApiError:class extends Error{},api:{recentTurns:vi.fn(),sendMessage:vi.fn(),newConversation:vi.fn(),resumeConversation:vi.fn(),clearConversationHistory:vi.fn(),conversation:vi.fn(),conversations:vi.fn()}}));
vi.mock('../api/assistantWorkflows',()=>({workflowApi:{capabilities:vi.fn(),sendMessage:vi.fn(),event:vi.fn(),list:vi.fn(),originals:vi.fn(),view:vi.fn()}}));
beforeEach(()=>{localStorage.clear();vi.resetAllMocks();vi.mocked(api.recentTurns).mockResolvedValue([]);vi.mocked(api.conversations).mockResolvedValue({entries:[],next_before:null});vi.mocked(workflowApi.list).mockResolvedValue([]);vi.mocked(workflowApi.originals).mockResolvedValue([]);vi.mocked(workflowApi.capabilities).mockResolvedValue({contract_version:1,enabled:true,capabilities:[]});});
afterEach(cleanup);
const base:WorkflowView={task_id:'DEMO-native-transition',revision:1,capability_id:'conversation.new',state:'collecting',save_mode:'allowed',storage_state:'saved',prompt_key:'assistant.conversation.patient_action',input_fields:{},visible_fields:{},missing_fields:[],actions:[{kind:'conversation',action:'new',conversation_id:null}],explanations:[],result_ref:null};
async function send(view:WorkflowView){vi.mocked(workflowApi.sendMessage).mockResolvedValue({reply:{message:'DEMO prepared action',intent:'clarification',mode:'workflow',tool_traces:[],session_id:'DEMO-original',session_state:'collecting',requires_confirmation:false},workflow:view,explanations:[]} as never);fireEvent.change(screen.getByRole('textbox'),{target:{value:'DEMO request'}});fireEvent.click(screen.getByRole('button',{name:'Send'}));await screen.findByText('DEMO prepared action');}
it('adopts a prepared new native session without sending a duplicate creation request',async()=>{
 vi.mocked(api.newConversation).mockResolvedValue({session_id:'DEMO-fresh',patient_id:'DEMO-owner'} as never);const onSession=vi.fn();
 render(<AssistantScreen ownerId="DEMO-A" sessionId="DEMO-original" onSession={onSession}/>);await send(base);
 fireEvent.click(await screen.findByRole('button',{name:'Start a new conversation'}));fireEvent.click(screen.getByRole('button',{name:'Confirm conversation action'}));
 await waitFor(()=>expect(onSession).toHaveBeenCalledWith('DEMO-fresh'));expect(api.newConversation).toHaveBeenCalledTimes(1);
});
it('adopts resumed history as text without restoring historical confirmation controls',async()=>{
 const conversation={id:'DEMO-thread',title:'DEMO history',created_at:'',updated_at:''};vi.mocked(api.resumeConversation).mockResolvedValue({conversation,session_id:'DEMO-restored'});vi.mocked(api.conversation).mockResolvedValue({conversation,entries:[{id:'DEMO-text',conversation_id:'DEMO-thread',user_text:'DEMO old question',assistant_text:'DEMO old answer',created_at:'',photo_attached:false}],next_before:null});const onSession=vi.fn();
 render(<AssistantScreen ownerId="DEMO-A" sessionId="DEMO-original" onSession={onSession}/>);await send({...base,capability_id:'conversation.resume',input_fields:{conversation_id:'DEMO-thread'},actions:[{kind:'conversation',action:'resume',conversation_id:'DEMO-thread'}]});
 fireEvent.click(await screen.findByRole('button',{name:'Resume conversation'}));fireEvent.click(screen.getByRole('button',{name:'Confirm conversation action'}));
 await waitFor(()=>expect(onSession).toHaveBeenCalledWith('DEMO-restored'));await screen.findByText('DEMO old answer');expect(api.resumeConversation).toHaveBeenCalledTimes(1);expect(screen.queryByRole('button',{name:'Confirm taking'})).toBeNull();
});
it('detaches the cleared conversation task before the next message while retaining saved drafts',async()=>{
 const cleared=vi.fn();vi.mocked(api.clearConversationHistory).mockResolvedValue({cleared:true});
 render(<AssistantScreen ownerId="DEMO-A" sessionId="DEMO-original" onSession={vi.fn()} onConversationCleared={cleared}/>);
 await send({...base,capability_id:'conversation.clear',conversation_id:'DEMO-cleared-thread',actions:[{kind:'conversation',action:'clear',conversation_id:null}]});
 fireEvent.click(await screen.findByRole('button',{name:'Clear chat history'}));fireEvent.click(screen.getByRole('button',{name:'Confirm conversation action'}));
 await waitFor(()=>expect(cleared).toHaveBeenCalledOnce());await waitFor(()=>expect(screen.queryByRole('region',{name:'Current task'})).toBeNull());
 await send({...base,capability_id:'assistant.usage',actions:[]});expect(vi.mocked(workflowApi.sendMessage).mock.calls.at(-1)?.[0].task_id).toBeUndefined();
});
