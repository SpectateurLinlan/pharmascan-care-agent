// @vitest-environment jsdom
// @vitest-environment-options {"url":"http://localhost:5173"}
/** Synthetic credentials/records only; no real Auth, Storage or patient calls. */
import {afterEach,expect,it,vi} from 'vitest';
import {ApiError,DiagnosticSessionUnavailable,readDiagnosticCounts} from './client';
import {existingAccessToken,accessToken} from './auth';
import {createMedicationDiagnostic,installLocalDiagnostics} from './localDiagnostics';
import {diagnosticEvent,diagnosticFailureStage,observeDiagnosticResponse} from './diagnosticContract';

vi.mock('./auth',()=>({existingAccessToken:vi.fn(),accessToken:vi.fn()}));
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();localStorage.clear();delete window.medithreadMedicationCounts;});
const response=(data:unknown)=>new Response(JSON.stringify(data),{status:200});
it('uses the app SDK token despite unrelated/stale stored entries; emits GETs and aggregates only',async()=>{
 localStorage.setItem('supabase.auth.token',JSON.stringify({access_token:'SIMULATED_OLD',expires_at:1}));
 localStorage.setItem('sb-unrelated-auth-token',JSON.stringify({access_token:'SIMULATED_UNRELATED',expires_at:1}));
 vi.mocked(existingAccessToken).mockResolvedValue('SIMULATED_CURRENT');
 const fetch=vi.fn().mockResolvedValueOnce(response({item_count:2,medications:[{name:'PRIVATE_NAME',id:'PRIVATE_ID'}]})).mockResolvedValueOnce(response([{state:'ended',id:'PRIVATE_ID'},{state:'ended'},{state:'active'},{state:'PRIVATE_STATE'}]));
 vi.stubGlobal('fetch',fetch);
 const run=createMedicationDiagnostic(readDiagnosticCounts,()=>location.origin,()=>[]);
 const report=await run();expect(report.result).toBe('complete');
 expect(report.endpoints.map(row=>[row.item_count,row.states])).toEqual([[2,null],[null,{ended:2,active:1,unsupported_state:1}]]);
 expect(JSON.stringify(report)).not.toMatch(/PRIVATE|SIMULATED/);
 expect(accessToken).not.toHaveBeenCalled();
 for(const [url,init] of fetch.mock.calls){expect(['/api/me/medications','/api/me/regimens']).toContain(url);expect(init).toMatchObject({method:'GET',redirect:'error',headers:{Authorization:'Bearer SIMULATED_CURRENT'}});expect(init.body).toBeUndefined();}
});
it('does not fetch or anonymously log in if the SDK has no existing session',async()=>{
 vi.mocked(existingAccessToken).mockResolvedValue(null);const fetch=vi.fn();vi.stubGlobal('fetch',fetch);
 const report=await createMedicationDiagnostic(readDiagnosticCounts,()=>location.origin,()=>[])();
 expect(report.result).toBe('session_unavailable');expect(report.endpoints[0]?.status).toBeNull();expect(fetch).not.toHaveBeenCalled();expect(accessToken).not.toHaveBeenCalled();
});
it('keeps 401 and 503 separate, never outputs raw provider errors or fake zero counts',async()=>{
 const read=vi.fn().mockRejectedValueOnce(new ApiError(401,{code:'AUTH_REQUIRED',message:'PRIVATE token',rule_id:null})).mockRejectedValueOnce(new ApiError(503,{code:'PROVIDER_UNAVAILABLE',message:'PRIVATE record',rule_id:null}));
 const report=await createMedicationDiagnostic(read,()=>location.origin,()=>[])();
 expect(report.result).toBe('partial');expect(report.endpoints.map(row=>[row.status,row.result,row.item_count])).toEqual([[401,'authentication_rejected',null],[503,'service_unavailable',null]]);expect(JSON.stringify(report)).not.toContain('PRIVATE');
});
it('blocks nonlocal origins and overlapping runs share one bounded request set',async()=>{
 const read=vi.fn().mockResolvedValue(response({item_count:0}));
 expect((await createMedicationDiagnostic(read,()=> 'https://medithread.vercel.app',()=>[])()).result).toBe('blocked_origin');expect(read).not.toHaveBeenCalled();
 read.mockImplementation(async path=>response(path.endsWith('regimens')?[]:{item_count:0}));
 const run=createMedicationDiagnostic(read,()=>location.origin,()=>[]);const first=run();expect(run()).toBe(first);await first;expect(read).toHaveBeenCalledTimes(2);
});
it('observes existing requests without probing Alerts or retaining query/record fields; cleans up',async()=>{
 const read=vi.fn().mockImplementation(async path=>response(path.endsWith('regimens')?[]:{item_count:0}));
 const stop=installLocalDiagnostics(window,read);
 observeDiagnosticResponse('/api/me/today-attention?client_id=PRIVATE',401,true);
 observeDiagnosticResponse('/api/reminders/alerts',503,true);
 window.dispatchEvent(new CustomEvent(diagnosticEvent,{detail:{endpoint:'/api/me/today-attention',status:401,authorization_attached:true,token:'PRIVATE'}}));
 observeDiagnosticResponse('/api/PRIVATE',200,true);
 const report=await window.medithreadMedicationCounts?.();
 expect(report?.observed_requests).toEqual([{endpoint:'/api/me/today-attention',status:401,authorization_attached:true,failure_stage:'unknown'},{endpoint:'/api/reminders/alerts',status:503,authorization_attached:true,failure_stage:'unknown'}]);
 expect(read.mock.calls.map(row=>row[0])).toEqual(['/api/me/medications','/api/me/regimens']);expect(JSON.stringify(report)).not.toContain('PRIVATE');stop();expect(window.medithreadMedicationCounts).toBeUndefined();
});
it('labels only known static auth failure phases, without echoing arbitrary server messages',()=>{
 expect(diagnosticFailureStage(401,'A bearer access token is required for this endpoint')).toBe('missing_bearer');
 expect(diagnosticFailureStage(401,'Access token rejected by the identity provider (HTTP 401)')).toBe('identity_rejected');
 expect(diagnosticFailureStage(401,'Could not verify the access token with the identity provider')).toBe('legacy_identity_service_failure_401');
 expect(diagnosticFailureStage(503,'Identity verification service is temporarily unavailable.')).toBe('identity_service_unavailable');
 expect(diagnosticFailureStage(401,'Supabase rejected authenticated data access')).toBe('data_api_auth_rejected');
 expect(diagnosticFailureStage(503,'PRIVATE record token')).toBe('unknown');
});
it('does not treat an unreadable SDK/transport error or malformed JSON as signed-out proof',async()=>{
 const read=vi.fn().mockRejectedValueOnce(new Error('PRIVATE')).mockResolvedValueOnce(response({unexpected:'PRIVATE'}));
 const report=await createMedicationDiagnostic(read,()=>location.origin,()=>[])();expect(report.result).toBe('partial');expect(report.endpoints.map(row=>row.result)).toEqual(['session_or_network_unavailable','invalid_response']);
 expect(new DiagnosticSessionUnavailable()).toBeInstanceOf(Error);
});
