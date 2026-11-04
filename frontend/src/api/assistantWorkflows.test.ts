// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {accessToken} from './auth';
import {workflowApi,readWorkflowRun} from './assistantWorkflows';

vi.mock('./auth',()=>({accessToken:vi.fn().mockResolvedValue('DEMO-token')}));
afterEach(()=>{vi.unstubAllGlobals();vi.clearAllMocks();});

it('does not expose malformed status-response content as an error message',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('PRIVATE_UNTRUSTED_STATUS_BODY')));
 await expect(readWorkflowRun('DEMO-run')).rejects.toThrow('Processing status is unavailable.');
});

it('resumes only the server-bound original draft task using the current revision',async()=>{
 const fetcher=vi.fn().mockResolvedValue(new Response(JSON.stringify({task_id:'DEMO-original'})));
 vi.stubGlobal('fetch',fetcher);
 await workflowApi.resumeDraft('DEMO-recovery',4);
 expect(fetcher.mock.calls[0]![0]).toContain('/api/agent/workflows/tasks/DEMO-recovery/resume-draft?client_id=');
 expect(JSON.parse(fetcher.mock.calls[0]![1].body)).toEqual({expected_revision:4});
 expect(fetcher.mock.calls[0]![1].headers.Authorization).toBe('Bearer DEMO-token');
});

it('uses the shared authenticated client and requires an explicitly supported manifest',async()=>{
 const fetcher=vi.fn().mockResolvedValue(new Response(JSON.stringify({contract_version:2,enabled:true,capabilities:[]})));
 vi.stubGlobal('fetch',fetcher);
 expect((await workflowApi.capabilities()).enabled).toBe(false);
 expect(accessToken).toHaveBeenCalled();
 expect(fetcher.mock.calls[0]![0]).toContain('/api/agent/workflows/capabilities?client_id=');
 expect(fetcher.mock.calls[0]![1].headers.Authorization).toBe('Bearer DEMO-token');
});

it('does not resend to the legacy endpoint after a workflow POST fails',async()=>{
 const fetcher=vi.fn().mockResolvedValue(new Response(JSON.stringify({code:'PROVIDER_UNAVAILABLE',message:'DEMO interrupted'}),{status:503}));
 vi.stubGlobal('fetch',fetcher);
 await expect(workflowApi.sendMessage({workspace_id:'DEMO-workspace',text:'DEMO request',session_id:null,client_turn_id:'DEMO-id',slots:{}})).rejects.toThrow('DEMO interrupted');
 expect(fetcher).toHaveBeenCalledTimes(1);
 expect(fetcher.mock.calls[0]![0]).toContain('/api/agent/workflows/messages?');
});

it('uploads the original File body through the shared authenticated client without conversion',async()=>{
 const fetcher=vi.fn().mockResolvedValue(new Response(JSON.stringify({attachment:{id:'DEMO-original'},workflow:{task_id:'DEMO-task'}})));
 vi.stubGlobal('fetch',fetcher);
 const file=new File(['DEMO original bytes'],'DEMO private label.png',{type:'image/png'});
 await workflowApi.uploadOriginal('DEMO-task','DEMO-upload',file,4,'pharmacy_label',true);
 expect(fetcher.mock.calls[0]![1].body).toBe(file);
 expect(fetcher.mock.calls[0]![1].headers['Content-Type']).toBe('image/png');
 expect(fetcher.mock.calls[0]![0]).toContain('expected_revision=4');
 expect(fetcher.mock.calls[0]![0]).not.toContain('private');
});
