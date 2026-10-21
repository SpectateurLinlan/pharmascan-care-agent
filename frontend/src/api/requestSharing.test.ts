import {afterEach,expect,it,vi} from 'vitest';
import {api} from './client';
import {accessToken} from './auth';

vi.mock('./auth',()=>({accessToken:vi.fn().mockResolvedValue('DEMO-owner-a')}));
afterEach(()=>{vi.unstubAllGlobals();vi.clearAllMocks();vi.mocked(accessToken).mockResolvedValue('DEMO-owner-a');});
const response=(body:unknown)=>({ok:true,status:200,json:async()=>body}) as Response;

it('shares overlapping follow-up reads but reads again after settlement',async()=>{
 let finish!:(value:Response)=>void;
 const fetch=vi.fn().mockReturnValueOnce(new Promise(resolve=>{finish=resolve;})).mockResolvedValue(response({items:[]}));
 vi.stubGlobal('fetch',fetch);
 const first=api.doseFollowUps(),second=api.doseFollowUps();
 await vi.waitFor(()=>expect(fetch).toHaveBeenCalledTimes(1));
 finish(response({items:[]}));await Promise.all([first,second]);
 await api.doseFollowUps();expect(fetch).toHaveBeenCalledTimes(2);
});

it('isolates current tokens, query parameters and post-write reads',async()=>{
 const finishes:Array<(value:Response)=>void>=[];
 const fetch=vi.fn().mockImplementation(()=>new Promise(resolve=>finishes.push(resolve)));
 vi.stubGlobal('fetch',fetch);
 const pending=[api.doseFollowUps()];
 await vi.waitFor(()=>expect(fetch).toHaveBeenCalledTimes(1));
 vi.mocked(accessToken).mockResolvedValue('DEMO-owner-b');pending.push(api.doseFollowUps());
 await vi.waitFor(()=>expect(fetch).toHaveBeenCalledTimes(2));
 pending.push(api.doseFollowUps(true));await vi.waitFor(()=>expect(fetch).toHaveBeenCalledTimes(3));
 const write=api.updatePreferences({preferred_language:'zh'});
 await vi.waitFor(()=>expect(fetch).toHaveBeenCalledTimes(4));
 pending.push(api.doseFollowUps());await vi.waitFor(()=>expect(fetch).toHaveBeenCalledTimes(5));
 finishes.forEach(finish=>finish(response({items:[]})));await Promise.all([...pending,write]);
});

it('cleans up failed shared reads so an explicit retry reaches the server',async()=>{
 let fail!:(error:Error)=>void;
 const fetch=vi.fn().mockReturnValueOnce(new Promise((_,reject)=>{fail=reject;})).mockResolvedValue(response([]));
 vi.stubGlobal('fetch',fetch);
 const first=api.reminderAlerts(),second=api.reminderAlerts();
 const settled=Promise.allSettled([first,second]);
 await vi.waitFor(()=>expect(fetch).toHaveBeenCalledTimes(1));fail(new Error('DEMO offline'));
 expect((await settled).every(value=>value.status==='rejected')).toBe(true);
 await api.reminderAlerts();expect(fetch).toHaveBeenCalledTimes(2);
});
// @vitest-environment jsdom
