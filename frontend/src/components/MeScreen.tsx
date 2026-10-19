import {disableWebPush} from '../webPush';
import {useEffect,useState} from 'react';
import {accountAuth,type Account,type AccountPort} from '../api/auth';
import {useLanguage} from '../language';
import {Card} from './primitives';
import {BottomSheet} from './BottomSheet';

/**
 * Account and sign-in.
 *
 * `standalone` is the signed-out surface: it renders without the app shell
 * (no bottom tabs, no rail, no Settings entry) because a sign-in screen is a
 * decision about identity, not a destination inside the app.
 *
 * The guest path is preserved and remains the default: the app signs in
 * anonymously so a patient can use every medication feature without an email
 * address. Only an explicit choice links an email account.
 */
export function MeScreen({auth=accountAuth,onIdentityChanged,standalone=false,onGuest,onHelp}:{auth?:AccountPort;onSettings?:()=>void;onFeedback?:()=>void;onIdentityChanged:()=>void;standalone?:boolean;onGuest?:()=>void;onHelp?:()=>void}){
 const {t,preferences}=useLanguage();const [account,setAccount]=useState<Account|null>(null),[accountLoading,setAccountLoading]=useState(true),[email,setEmail]=useState(''),[password,setPassword]=useState(''),[code,setCode]=useState('');
 const [mode,setMode]=useState<'link'|'login'>('link'),[sent,setSent]=useState(false),[switchAccepted,setSwitchAccepted]=useState(false),[busy,setBusy]=useState(false),[notice,setNotice]=useState(''),[confirmSignOut,setConfirmSignOut]=useState(false);
 useEffect(()=>{let live=true;void auth.account().then(row=>{if(live){setAccount(row);if(row.kind==='signed_out')setMode('login');}}).catch(()=>{if(live)setNotice('Could not load your account.');}).finally(()=>{if(live)setAccountLoading(false);});return()=>{live=false;};},[auth]);
 async function run(action:()=>Promise<void>){setBusy(true);setNotice('');try{await action();}catch(error){setNotice(error instanceof Error?error.message:'Could not complete sign in.');}finally{setBusy(false);setPassword('');setCode('');}}
 const maySwitch=account?.kind==='signed_out'||account?.kind==='member'||(mode==='link'&&account?.kind==='guest')||(mode==='login'&&switchAccepted);
 const body=<>
 {account?.kind==='member'?<><p>{t('Login email')}: {account.email}</p><p>{t(account.verified?'Email verified':'Email verification pending')}</p><p>{t('Login methods')}: {t('Email sign-in link; password sign-in if previously enabled.')}</p><p>{t('Time zone')}: {preferences.timezone}</p>
 <button disabled={busy} onClick={()=>setConfirmSignOut(true)}>{t('Sign out')}</button></>:<>
 {account?.kind==='guest'?<><p>{t('Guest records are associated with this anonymous account. Linking an email may let you access them on another device; this has not been verified across hosted accounts.')}</p>
 <div className="segmented"><button aria-pressed={mode==='link'} onClick={()=>{setMode('link');setSent(false);}}>{t('Link email and keep my records')}</button><button aria-pressed={mode==='login'} onClick={()=>{setMode('login');setSent(false);}}>{t('Sign in to an existing account')}</button></div>
 {mode==='login'?<label className="consent"><input type="checkbox" checked={switchAccepted} onChange={event=>setSwitchAccepted(event.target.checked)}/>{t('Signing in switches accounts. Guest medication records will not be merged.')}</label>:null}</>:account?.kind==='local'?<p>{t('Email sign-in and account linking are unavailable in this local demo. No authenticated account is connected here.')}</p>:<p>{t('Sign in to an existing account. No guest account is currently active to link.')}</p>}
 <div className="field"><label htmlFor="login-email">{t('Email')}</label><input id="login-email" type="email" autoComplete="email" value={email} onChange={event=>{setEmail(event.target.value);setSent(false);}}/></div>
 <button className="primary" disabled={busy||!email||!auth.available||!maySwitch} onClick={()=>void run(async()=>{await auth.requestEmail(email,mode);setSent(true);setNotice(mode==='link'?'Check your email to confirm your address and keep your records.':'Check your email for a code or sign-in link.');})}>{t('Email code / Magic Link')}</button>
 {sent?<><div className="field"><label htmlFor="login-code">{t('Email code')}</label><input id="login-code" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={event=>setCode(event.target.value)} /></div><button disabled={busy||!code} onClick={()=>void run(async()=>{await auth.verifyEmail(email,code,mode);onIdentityChanged();})}>{t('Verify and continue')}</button></>:null}
 {mode==='login'&&account?.kind!=='local'?<details><summary>{t('Use email and password instead')}</summary><div className="field"><label htmlFor="login-password">{t('Password')}</label><input id="login-password" type="password" autoComplete="current-password" value={password} onChange={event=>setPassword(event.target.value)}/></div><button disabled={busy||!password||!email||!maySwitch||!auth.available} onClick={()=>void run(async()=>{await auth.passwordLogin(email,password);onIdentityChanged();})}>{t('Sign in')}</button></details>:null}
 </>}
 {notice?<div className="patient-toast" role="status"><p>{t(notice)}</p><button aria-label={t('Dismiss')} onClick={()=>setNotice('')}>{t('Close')}</button></div>:null}
 </>;

 if(standalone) return <section className="signin-screen">
  <p className="brand">MediThread</p>
  <p>{t('Your medication and self-care companion')}</p>
  <h1>{t('Sign in or continue as a guest')}</h1>
  <p className="signin-lead">{t('You can use every medication feature without an account. Signing in only keeps your records available on other devices.')}</p>
  <div className="signin-card">{body}</div>
  <div className="signin-actions">
   <button className="primary" onClick={onGuest}>{t('Continue as a guest')}</button>
   {onHelp?<button onClick={onHelp}>{t('Help / User Guide')}</button>:null}
  </div>
  {/* Informational, not a blocking gate: the guest path stays available
      without it, and no new mandatory agreement is introduced here. */}
  <p className="signin-privacy">{t('Your records stay private to this account or browser session. You choose what to export or share.')}</p>
 </section>;

 return <>{accountLoading?<Card title="Account & security"><p role="status">{t('Loading account...')}</p></Card>:account===null?<Card title="Account & security"><p role="alert">{t('Could not load your account. Please retry.')}</p><button onClick={()=>{setAccountLoading(true);void auth.account().then(setAccount).catch(()=>setNotice('Could not load your account.')).finally(()=>setAccountLoading(false));}}>{t('Retry')}</button></Card>:account.kind==='member'?<Card title="Account & security">{body}</Card>:account.kind==='signed_out'?<Card title="Sign in to an existing account">{body}</Card>:account.kind==='local'?<Card title="Local demo">{body}</Card>:<Card title="Guest Mode">{body}</Card>}{confirmSignOut?<BottomSheet title={t('Sign out?')} busy={busy} onCancel={()=>setConfirmSignOut(false)}><p>{t('You will leave this account on this device. Its records are not merged into another account.')}</p><button disabled={busy} onClick={()=>setConfirmSignOut(false)}>{t('Cancel')}</button><button className="primary" disabled={busy} onClick={()=>void run(async()=>{await disableWebPush();await auth.signOut();onIdentityChanged();})}>{t('Sign out')}</button></BottomSheet>:null}</>;
}
