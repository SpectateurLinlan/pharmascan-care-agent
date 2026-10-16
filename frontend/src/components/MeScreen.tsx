import {disableWebPush} from '../webPush';
import {useEffect,useState} from 'react';
import {accountAuth,type Account,type AccountPort} from '../api/auth';
import {useLanguage} from '../language';
import {Card} from './primitives';

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
 const {t,preferences}=useLanguage();const [account,setAccount]=useState<Account|null>(null),[email,setEmail]=useState(''),[password,setPassword]=useState(''),[code,setCode]=useState('');
 const [mode,setMode]=useState<'link'|'login'>('link'),[sent,setSent]=useState(false),[switchAccepted,setSwitchAccepted]=useState(false),[busy,setBusy]=useState(false),[notice,setNotice]=useState('');
 useEffect(()=>{let live=true;void auth.account().then(row=>{if(live){setAccount(row);if(row.kind==='signed_out')setMode('login');}}).catch(()=>{if(live)setNotice('Could not load your account.');});return()=>{live=false;};},[auth]);
 async function run(action:()=>Promise<void>){setBusy(true);setNotice('');try{await action();}catch(error){setNotice(error instanceof Error?error.message:'Could not complete sign in.');}finally{setBusy(false);setPassword('');setCode('');}}
 const maySwitch=account?.kind==='signed_out'||account?.kind==='member'||(mode==='link'&&account?.kind==='guest')||(mode==='login'&&switchAccepted);
 const body=<>
 <h3>{t(account?.kind==='member'?'Your account':account?.kind==='local'?'Guest':'Guest')}</h3>
 {account?.kind==='member'?<><p>{account.email}</p><p>{t(account.verified?'Email verified':'Email verification pending')}</p><p>{t('Time zone')}: {preferences.timezone}</p>
 <div className="field"><label htmlFor="backup-password">{t('Set a backup password')}</label><input id="backup-password" type="password" autoComplete="new-password" minLength={8} value={password} onChange={event=>setPassword(event.target.value)}/></div>
 <button disabled={busy||password.length<8||!account.verified} onClick={()=>void run(async()=>{await auth.setPassword(password);setNotice('Backup password saved.');})}>{t('Save password')}</button>
 <button disabled={busy} onClick={()=>void run(async()=>{await disableWebPush();await auth.signOut();onIdentityChanged();})}>{t('Sign out')}</button></>:<>
 <p>{t('Guest records stay with your guest account. Link an email to access them on other devices.')}</p>
 <div className="segmented"><button aria-pressed={mode==='link'} onClick={()=>{setMode('link');setSent(false);}}>{t('Keep my records with email')}</button><button aria-pressed={mode==='login'} onClick={()=>{setMode('login');setSent(false);}}>{t('Sign in to an account')}</button></div>
 {mode==='login'&&account?.kind!=='signed_out'?<label className="consent"><input type="checkbox" checked={switchAccepted} onChange={event=>setSwitchAccepted(event.target.checked)}/>{t('Signing in switches accounts. Guest medication records will not be merged.')}</label>:null}
 <div className="field"><label htmlFor="login-email">{t('Email')}</label><input id="login-email" type="email" autoComplete="email" value={email} onChange={event=>{setEmail(event.target.value);setSent(false);}}/></div>
 <button className="primary" disabled={busy||!email||!auth.available||!maySwitch} onClick={()=>void run(async()=>{await auth.requestEmail(email,mode);setSent(true);setNotice(mode==='link'?'Check your email to confirm your address and keep your records.':'Check your email for a code or sign-in link.');})}>{t('Email code / Magic Link')}</button>
 {sent?<><div className="field"><label htmlFor="login-code">{t('Email code')}</label><input id="login-code" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={event=>setCode(event.target.value)} /></div><button disabled={busy||!code} onClick={()=>void run(async()=>{await auth.verifyEmail(email,code,mode);onIdentityChanged();})}>{t('Verify and continue')}</button></>:null}
 {mode==='login'?<details><summary>{t('Use email and password instead')}</summary><div className="field"><label htmlFor="login-password">{t('Password')}</label><input id="login-password" type="password" autoComplete="current-password" value={password} onChange={event=>setPassword(event.target.value)}/></div><button disabled={busy||!password||!email||!maySwitch||!auth.available} onClick={()=>void run(async()=>{await auth.passwordLogin(email,password);onIdentityChanged();})}>{t('Sign in')}</button></details>:null}
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

 return <Card title="Your account">{body}</Card>;
}
