// @vitest-environment jsdom
/** SIMULATED SDK calls, not real email delivery. */
import {beforeEach,expect,it,vi} from 'vitest';
import {createAuthGateway} from './auth';
import type {Session} from '@supabase/auth-js';
type Driver=ReturnType<NonNullable<Parameters<typeof createAuthGateway>[1]>>;
const environment={VITE_SUPABASE_URL:'https://synthetic.example.test',VITE_SUPABASE_PUBLISHABLE_KEY:'sb_publishable_SIMULATED'};
function setup(){const driver={getSession:vi.fn().mockResolvedValue({data:{session:{access_token:'SIMULATED_TOKEN'}},error:null}),getUser:vi.fn().mockResolvedValue({data:{user:{is_anonymous:true,id:'synthetic-user'}},error:null}),signInAnonymously:vi.fn().mockResolvedValue({data:{session:{access_token:'SIMULATED_TOKEN'}},error:null}),signInWithOtp:vi.fn().mockResolvedValue({data:{},error:null}),verifyOtp:vi.fn().mockResolvedValue({data:{},error:null}),signInWithPassword:vi.fn().mockResolvedValue({data:{},error:null}),updateUser:vi.fn().mockResolvedValue({data:{},error:null}),signOut:vi.fn().mockResolvedValue({error:null})};return {driver,gateway:createAuthGateway(environment,()=>driver as unknown as Driver)};}
beforeEach(()=>{history.replaceState(null,'','/');});
it('email linking preserves the guest identity flow and verifies email_change OTP',async()=>{
 const {driver,gateway}=setup();await gateway.accountPort.requestEmail('synthetic@example.test','link');
 expect(driver.updateUser).toHaveBeenCalledWith({email:'synthetic@example.test'},{emailRedirectTo:window.location.origin});expect(driver.signInWithOtp).not.toHaveBeenCalled();
 await gateway.accountPort.verifyEmail('synthetic@example.test','123456','link');expect(driver.verifyOtp).toHaveBeenCalledWith({email:'synthetic@example.test',token:'123456',type:'email_change'});
});
it('normal OTP/magic link and password sign-in use the official identity APIs',async()=>{
 const {driver,gateway}=setup();await gateway.accountPort.requestEmail('synthetic@example.test','login');
 expect(driver.signInWithOtp).toHaveBeenCalledWith({email:'synthetic@example.test',options:{emailRedirectTo:window.location.origin,shouldCreateUser:true}});
 await gateway.accountPort.verifyEmail('synthetic@example.test','123456','login');expect(driver.verifyOtp).toHaveBeenCalledWith(expect.objectContaining({type:'email'}));
 await gateway.accountPort.passwordLogin('synthetic@example.test','SIMULATED_password');expect(driver.signInWithPassword).toHaveBeenCalledOnce();
});
it('rejects password setup before email verification and scrubs provider errors',async()=>{
 const {driver,gateway}=setup();await expect(gateway.accountPort.setPassword('SIMULATED_password')).rejects.toThrow('Verify your email');expect(driver.updateUser).not.toHaveBeenCalled();
 driver.signInWithOtp.mockResolvedValue({data:{},error:{code:'over_email_send_rate_limit',message:'PRIVATE_PROVIDER_DETAILS'}});
 await expect(gateway.accountPort.requestEmail('synthetic@example.test','login')).rejects.toThrow('Too many requests');
});
it('SDK session stays in the token boundary and callback credentials leave the URL',async()=>{
 const {gateway}=setup();history.replaceState(null,'','/#access_token=SIMULATED_TOKEN&refresh_token=SIMULATED_REFRESH');
 expect(await gateway.getAccessToken()).toBe('SIMULATED_TOKEN');expect(window.location.hash).toBe('');
});
it('concurrent bootstrap signs in anonymously only once',async()=>{
 const {driver,gateway}=setup();driver.getSession.mockResolvedValue({data:{session:null},error:null});
 await Promise.all([gateway.getAccessToken(),gateway.getAccessToken()]);expect(driver.signInAnonymously).toHaveBeenCalledOnce();
});
it('existing-session reads wait for the same SDK and never bootstrap another identity',async()=>{
 const {driver,gateway}=setup();
 let complete:((value:Awaited<ReturnType<Driver['getSession']>>)=>void)|undefined;
 driver.getSession.mockImplementationOnce(()=>new Promise(resolve=>{complete=resolve;}));
 const read=gateway.getExistingAccessToken();
 complete?.({data:{session:{access_token:'SIMULATED_REFRESHED'} as Session},error:null});
 expect(await read).toBe('SIMULATED_REFRESHED');expect(driver.signInAnonymously).not.toHaveBeenCalled();
 driver.getSession.mockResolvedValue({data:{session:null},error:null});
 expect(await gateway.getExistingAccessToken()).toBeNull();expect(driver.signInAnonymously).not.toHaveBeenCalled();
});
it('only a changed subject invalidates patient state; refresh metadata must not discard an open draft',async()=>{
 const {driver}=setup();let listener:Parameters<Driver['onAuthStateChange']>[0]|undefined;
 const unsubscribe=vi.fn();const observed={...driver,onAuthStateChange:vi.fn((callback:Parameters<Driver['onAuthStateChange']>[0])=>{listener=callback;return {data:{subscription:{unsubscribe}}};})};
 const gateway=createAuthGateway(environment,()=>observed as unknown as Driver),changed=vi.fn();const stop=gateway.accountPort.watchIdentity?.(changed);
 const session=(id:string,anonymous?:boolean)=>({user:{id,is_anonymous:anonymous},access_token:'SIMULATED_TOKEN'}) as unknown as Session;
 await listener?.('INITIAL_SESSION',session('DEMO-A',true));await listener?.('TOKEN_REFRESHED',session('DEMO-A'));expect(changed).not.toHaveBeenCalled();
 await listener?.('SIGNED_IN',session('DEMO-B',false));expect(changed).toHaveBeenCalledOnce();stop?.();expect(unsubscribe).toHaveBeenCalledOnce();
});
