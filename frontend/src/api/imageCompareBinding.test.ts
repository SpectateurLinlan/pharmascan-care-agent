import {afterEach,expect,it,vi} from 'vitest';
import {workflowApi} from './assistantWorkflows';
vi.mock('./auth',()=>({accessToken:vi.fn().mockResolvedValue(null)}));
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();});
it('separates original retention from explicit consented processing and sends no-save typed inputs only when needed',async()=>{
 const fetch=vi.fn().mockResolvedValue({ok:true,status:200,json:async()=>({})});vi.stubGlobal('fetch',fetch);const file=new File(['DEMO image'],'DEMO.png',{type:'image/png'});
 await workflowApi.uploadComparisonOriginal('DEMO-task','DEMO-upload',file,2);
 const [store,request]=fetch.mock.calls[0]!;expect(store).toContain('source_kind=comparison_photo');expect(request.headers['X-Stage2-Consent']).toBe('false');expect(request.body).toBe(file);
 await workflowApi.compareImage('DEMO-task',file,3,true,{intent:'personal',regimen_id:'DEMO-regimen'});
 const [url,process]=fetch.mock.calls[1]!;expect(url).toContain('expected_revision=3');expect(url).toContain('ephemeral_intent=personal');expect(url).toContain('ephemeral_regimen_id=DEMO-regimen');expect(process.body).toBe(file);expect(process.headers['X-Stage2-Consent']).toBe('true');
});
