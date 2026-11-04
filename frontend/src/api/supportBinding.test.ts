// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {api} from './client';
afterEach(()=>vi.restoreAllMocks());
it('passes task revision and independent confirmation to all native support writes',async()=>{
 const fetcher=vi.spyOn(globalThis,'fetch').mockImplementation(async()=>new Response('{}',{status:200,headers:{'Content-Type':'application/json'}}));
 const binding={task_id:'DEMO-task',expected_revision:3};
 await api.newConversation(binding);await api.resumeConversation('DEMO-thread',binding);await api.clearConversationHistory(binding);await api.feedback({id:'DEMO-feedback',category:'issue',message:'DEMO issue'},binding);
 for(const [,request] of fetcher.mock.calls){const headers=new Headers(request?.headers);expect(headers.get('X-Assistant-Task')).toBe(binding.task_id);expect(headers.get('X-Assistant-Revision')).toBe('3');expect(headers.get('X-Patient-Confirmed')).toBe('true');}
 expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body)).session_id).toBeNull();
});
