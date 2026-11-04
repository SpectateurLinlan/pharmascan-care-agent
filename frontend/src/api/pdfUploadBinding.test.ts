import {afterEach,expect,it,vi} from 'vitest';
import {api} from './client';
import {workflowApi} from './assistantWorkflows';
vi.mock('./auth',()=>({accessToken:vi.fn().mockResolvedValue(null)}));
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();});
it('saves a store-only PDF original and binds a separately confirmed native upload',async()=>{
 const fetch=vi.fn().mockResolvedValue({ok:true,status:200,json:async()=>({})});vi.stubGlobal('fetch',fetch);
 const file=new File(['%PDF-1.7\n% DEMO_ONLY\n%%EOF'],'DEMO.pdf',{type:'application/pdf'});
 await workflowApi.uploadPdfOriginal('DEMO-task','DEMO-upload',file,2);
 const [url,options]=fetch.mock.calls[0]!;expect(url).toContain('source_kind=library_pdf');expect(url).toContain('expected_revision=2');
 expect(options.body).toBe(file);expect(options.headers['X-Stage2-Consent']).toBe('false');
 await api.uploadLibraryPdf('DEMO-med',file,'other','DEMO document',{task_id:'DEMO-task',expected_revision:3});
 const [native,request]=fetch.mock.calls[1]!;expect(native).toContain('filename=DEMO.pdf');expect(native).toContain('confirmed=true');
 expect(request.headers['X-Assistant-Task']).toBe('DEMO-task');expect(request.headers['X-Assistant-Revision']).toBe('3');expect(request.body).toBe(file);
});
