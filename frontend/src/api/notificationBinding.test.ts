import {afterEach,expect,it,vi} from 'vitest';
import {api} from './client';
vi.mock('./auth',()=>({accessToken:vi.fn().mockResolvedValue(null)}));
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();});
it.each(['subscribe','current','device','test'])('binds the %s native notification call without moving secrets to an Agent request',async action=>{
 const fetch=vi.fn().mockResolvedValue({ok:true,status:200,json:async()=>({})});vi.stubGlobal('fetch',fetch);const binding={task_id:'DEMO-task',expected_revision:2},secret={endpoint:'DEMO-private-endpoint',keys:{auth:'DEMO-auth',p256dh:'DEMO-p256dh'}};
 if(action==='subscribe')await api.savePushSubscription(secret,binding);else if(action==='current')await api.revokeCurrentPush(secret,binding);else if(action==='device')await api.revokePushSubscription('DEMO-private-subscription',binding);else await api.testPush('DEMO-private-subscription','DEMO-request',binding);
 const [url,options]=fetch.mock.calls[0]!;expect(url).toContain('/api/reminders/push/');expect(url).not.toContain('/agent/');expect(options.headers['X-Assistant-Task']).toBe('DEMO-task');expect(options.headers['X-Assistant-Revision']).toBe('2');expect(options.headers['X-Patient-Confirmed']).toBe('true');
});
