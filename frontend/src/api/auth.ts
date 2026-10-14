/** Identity only. All patient business data continues through FastAPI/RLS. */
import {GoTrueClient,type Session} from '@supabase/auth-js';
export type AuthEnvironment={VITE_SUPABASE_URL?:string;VITE_SUPABASE_PUBLISHABLE_KEY?:string};
export type Account={kind:'guest'|'member'|'local'|'signed_out';email:string|null;verified:boolean};
export interface AccountPort {
 available:boolean;account():Promise<Account>;
 requestEmail(email:string,mode:'login'|'link'):Promise<void>;
 verifyEmail(email:string,code:string,mode:'login'|'link'):Promise<void>;
 passwordLogin(email:string,password:string):Promise<void>;setPassword(password:string):Promise<void>;signOut():Promise<void>;
 watchIdentity?:(listener:()=>void)=>()=>void;
}
type Driver=Pick<GoTrueClient,'getSession'|'getUser'|'signInAnonymously'|'signInWithOtp'|'verifyOtp'|'signInWithPassword'|'updateUser'|'signOut'|'onAuthStateChange'>;
export class AccountError extends Error {constructor(message:string){super(message);this.name='AccountError';}}
async function authFetch(input:RequestInfo|URL,init?:RequestInit):Promise<Response>{
 const controller=new AbortController(),cancel=()=>controller.abort();
 if(init?.signal?.aborted)controller.abort();else init?.signal?.addEventListener('abort',cancel,{once:true});
 const timer=setTimeout(cancel,15000);try{return await fetch(input,{...init,signal:controller.signal});}finally{clearTimeout(timer);init?.signal?.removeEventListener('abort',cancel);}
}
function scrub(error:unknown):never{
 const code=typeof error==='object'&&error!==null&&'code' in error?String(error.code):'';
 const message=code==='over_email_send_rate_limit'||code==='over_request_rate_limit'?'Too many requests. Please try again later.':
 code==='invalid_credentials'?'Email or password was not accepted.':code==='otp_expired'?'The code or link expired. Request a new one.':
 code==='email_exists'||code==='identity_already_exists'?'This email already has an account. Choose sign in instead.':
 'Could not complete sign in. Check your details and try again. Email delivery may need configuration.';
 throw new AccountError(message);
}
function view(user:Session['user']|null):Account{return user?{kind:user.is_anonymous?'guest':'member',email:user.is_anonymous?null:user.email??null,verified:!!user.email_confirmed_at}:{kind:'signed_out',email:null,verified:false};}
function cleanCallbackUrl(){if(typeof window!=='undefined'&&window.location&&window.history){const location=new URL(window.location.href);
   if(location.hash.includes('access_token')||location.hash.includes('refresh_token')||location.searchParams.has('code')){location.hash='';location.searchParams.delete('code');window.history.replaceState(null,'',location.pathname+location.search);}}}
function emailValue(email:string){if(!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)||email.length>254)throw new AccountError('Enter a valid email address.');return email.trim();}
export function createAuthGateway(environment:AuthEnvironment,factory:(url:string,key:string)=>Driver=(url,key)=>new GoTrueClient({url:`${url.replace(/\/$/,'')}/auth/v1`,headers:{apikey:key},detectSessionInUrl:true,fetch:authFetch})){
 const url=environment.VITE_SUPABASE_URL,key=environment.VITE_SUPABASE_PUBLISHABLE_KEY;
 if((url||key)&&(!url||!key||key.startsWith('sb_secret_')))throw new AccountError('Supabase Auth requires a URL and publishable key');
 const client=url&&key?factory(url,key):null;let signingIn:Promise<string>|null=null;
 const required=()=>{if(!client)throw new AccountError('Email sign in is unavailable in this local demo.');return client;};
 async function guarded<R extends {error:unknown}>(action:()=>Promise<R>):Promise<R>{try{const result=await action();if(result.error)scrub(result.error);return result;}catch(error){if(error instanceof AccountError)throw error;return scrub(error);}}
 async function getAccessToken():Promise<string|null>{
  if(!client)return null;let result:Awaited<ReturnType<Driver['getSession']>>;try{result=await guarded(()=>client.getSession());}finally{cleanCallbackUrl();}const data=result.data;
  if(data.session)return data.session.access_token;
  if(!signingIn)signingIn=(async()=>{const response=await guarded(()=>client.signInAnonymously({options:{data:{demo_only:true}}}));if(!response.data.session)throw new AccountError('Anonymous sign-in unavailable');return response.data.session.access_token;})().finally(()=>{signingIn=null;});
  return signingIn;
 }
 const accountPort:AccountPort={available:!!client,
  account:async()=>{if(!client)return {kind:'local',email:null,verified:false};const session=await guarded(()=>client.getSession());if(!session.data.session)return view(null);const result=await guarded(()=>client.getUser());return view(result.data.user);},
  requestEmail:async(email,mode)=>{const driver=required(),address=emailValue(email);if(mode==='link')await guarded(()=>driver.updateUser({email:address},{emailRedirectTo:window.location.origin}));else await guarded(()=>driver.signInWithOtp({email:address,options:{emailRedirectTo:window.location.origin,shouldCreateUser:true}}));},
  verifyEmail:async(email,code,mode)=>{if(!/^\d{6,10}$/.test(code))throw new AccountError('Enter the code from your email.');await guarded(()=>required().verifyOtp({email:emailValue(email),token:code,type:mode==='link'?'email_change':'email'}));},
  passwordLogin:async(email,password)=>{await guarded(()=>required().signInWithPassword({email:emailValue(email),password}));},
  setPassword:async(password)=>{const account=await accountPort.account();if(account.kind!=='member'||!account.verified)throw new AccountError('Verify your email before setting a password.');if(password.length<8)throw new AccountError('Use at least eight characters for your password.');await guarded(()=>required().updateUser({password}));},
  signOut:async()=>{await guarded(()=>required().signOut({scope:'local'}));},
  watchIdentity:listener=>{if(!client||typeof client.onAuthStateChange!=='function')return ()=>undefined;let prior:string|null|undefined;
   const {data}=client.onAuthStateChange((_event,session)=>{const next=session?.user.id??null;
    if(prior!==undefined&&prior!==next&&!(prior===null&&session?.user.is_anonymous)){prior=next;listener();}else prior=next;});
   return ()=>data.subscription.unsubscribe();},
 };
 return {getAccessToken,accountPort};
}
export function createAccessTokenProvider(environment:AuthEnvironment){return createAuthGateway(environment).getAccessToken;}
const environment=(import.meta as ImportMeta & {env:AuthEnvironment}).env;
const gateway=createAuthGateway(environment);
export const accessToken=gateway.getAccessToken;
export const accountAuth=gateway.accountPort;
