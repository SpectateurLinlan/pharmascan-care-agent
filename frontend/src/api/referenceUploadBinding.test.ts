import {afterEach,expect,it,vi} from 'vitest';
import {api} from './client';
import {workflowApi} from './assistantWorkflows';
vi.mock('./auth',()=>({accessToken:vi.fn().mockResolvedValue(null)}));
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();});

it('stores a typed reference original without recognition consent and binds the separate native gallery write',async()=>{
 const fetch=vi.fn().mockResolvedValue({ok:true,status:200,json:async()=>({})});vi.stubGlobal('fetch',fetch);
 const file=new File(['DEMO raw bytes'],'DEMO.png',{type:'image/png'});
 await workflowApi.uploadReferenceOriginal('DEMO-task','DEMO-upload',file,3);
 const [url,options]=fetch.mock.calls[0]!;expect(url).toContain('source_kind=reference_photo');expect(url).toContain('expected_revision=3');
 expect(options.body).toBe(file);expect(options.headers['X-Stage2-Consent']).toBe('false');
 await api.addReference('DEMO-med',file,'package','DEMO patient source',true,false,{task_id:'DEMO-task',expected_revision:4});
 const [native,request]=fetch.mock.calls[1]!;expect(native).toContain('for_comparison=false');
 expect(request.headers['X-Assistant-Task']).toBe('DEMO-task');expect(request.headers['X-Assistant-Revision']).toBe('4');
 expect(request.body).toBe(file);
});
