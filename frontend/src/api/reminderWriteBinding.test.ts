import {afterEach,expect,it,vi} from 'vitest';
import {api} from './client';
vi.mock('./auth',()=>({accessToken:vi.fn().mockResolvedValue(null)}));
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();});
it.each(['snooze','preferences'])('binds independent %s patient confirmation without adding fields to the native body',async kind=>{
 const fetch=vi.fn().mockResolvedValue({ok:true,status:200,json:async()=>({})});vi.stubGlobal('fetch',fetch);const binding={task_id:'DEMO-task',expected_revision:4};
 if(kind==='snooze')await api.snoozeReminder('DEMO-dose',15,binding);else await api.updatePreferences({reminders_enabled:false},binding);
 const [,options]=fetch.mock.calls[0]!;expect(options.headers['X-Assistant-Task']).toBe('DEMO-task');expect(options.headers['X-Assistant-Revision']).toBe('4');expect(options.headers['X-Patient-Confirmed']).toBe('true');expect(JSON.parse(options.body)).toEqual(kind==='snooze'?{occurrence_id:'DEMO-dose',minutes:15}:{reminders_enabled:false});
});
