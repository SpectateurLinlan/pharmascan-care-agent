import {disableWebPush} from '../webPush';
import {useEffect,useState} from 'react';
import {accountAuth,type Account,type AccountPort} from '../api/auth';
import {useLanguage} from '../language';
import {Card} from './primitives';
import {BottomSheet} from './BottomSheet';
import {Icon} from './Icon';
import {Screen} from '../ui/primitives';

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
export function MeScreen({auth=accountAuth,onIdentityChanged,standalone=false,embedded=false,onGuest,onHelp}:{auth?:AccountPort;onSettings?:()=>void;onFeedback?:()=>void;onIdentityChanged:()=>void;standalone?:boolean;embedded?:boolean;onGuest?:()=>void;onHelp?:()=>void}){
 const {t,preferences}=useLanguage();const [account,setAccount]=useState<Account|null>(null),[accountLoading,setAccountLoading]=useState(true),[email,setEmail]=useState(''),[password,setPassword]=useState(''),[code,setCode]=useState('');
 const [mode,setMode]=useState<'link'|'login'>('link'),[sent,setSent]=useState(false),[showGuestForm,setShowGuestForm]=useState(false),[switchAccepted,setSwitchAccepted]=useState(false),[busy,setBusy]=useState(false),[notice,setNotice]=useState(''),[confirmSignOut,setConfirmSignOut]=useState(false),[showPasswordForm,setShowPasswordForm]=useState(false),[newPassword,setNewPassword]=useState('');
 useEffect(()=>{let live=true;void auth.account().then(row=>{if(live){setAccount(row);if(row.kind==='signed_out')setMode('login');}}).catch(()=>{if(live)setNotice('Could not load your account.');}).finally(()=>{if(live)setAccountLoading(false);});return()=>{live=false;};},[auth]);
 useEffect(()=>{if(!notice)return;const timer=window.setTimeout(()=>setNotice(''),4000);return()=>window.clearTimeout(timer);},[notice]);
 async function run(action:()=>Promise<void>,success?:string){setBusy(true);setNotice('');try{await action();if(success)setNotice(success);}catch(error){setNotice(error instanceof Error?error.message:'Could not complete sign in.');}finally{setBusy(false);setPassword('');setNewPassword('');setCode('');}}
 const maySwitch=account?.kind==='signed_out'||account?.kind==='member'||(mode==='link'&&account?.kind==='guest')||(mode==='login'&&switchAccepted);
 const signInForm=<>
  <div className="field"><label htmlFor="login-email">{t('Email')}</label><input id="login-email" type="email" autoComplete="email" value={email} onChange={event=>{setEmail(event.target.value);setSent(false);}}/></div>
  <button className="primary" disabled={busy||!email||!auth.available||!maySwitch} onClick={()=>void run(async()=>{await auth.requestEmail(email,mode);setSent(true);},mode==='link'?'Check your email to confirm the address and keep using this guest account.':'Check your email for a sign-in code or link.')}>{t('Email code / Magic Link')}</button>
  {sent?<><div className="field"><label htmlFor="login-code">{t('Email code')}</label><input id="login-code" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={event=>setCode(event.target.value)} /></div><button disabled={busy||!code} onClick={()=>void run(async()=>{await auth.verifyEmail(email,code,mode);onIdentityChanged();})}>{t('Verify and continue')}</button></>:null}
  {mode==='login'&&account?.kind!=='local'?<details><summary>{t('Use email and password instead')}</summary><div className="field"><label htmlFor="login-password">{t('Password')}</label><input id="login-password" type="password" autoComplete="current-password" value={password} onChange={event=>setPassword(event.target.value)}/></div><button disabled={busy||!password||!email||!maySwitch||!auth.available} onClick={()=>void run(async()=>{await auth.passwordLogin(email,password);onIdentityChanged();})}>{t('Sign in')}</button></details>:null}
 </>;
 const body=<>
 {account?.kind==='member'?<>
  <section className="account-summary"><h2>{t('Account information')}</h2><dl><div><dt>{t('Login email')}</dt><dd>{account.email??t('Email unavailable')}</dd></div><div><dt>{t('Verification')}</dt><dd><span className={account.verified?'account-verified':'account-unverified'}>{t(account.verified?'Email verified':'Email verification pending')}</span></dd></div><div><dt>{t('Time zone')}</dt><dd>{preferences.timezone}</dd></div></dl></section>
  <section className="account-login-methods"><h2>{t('Login methods')}</h2><div className="account-method-row"><span><strong>{t('Email sign-in link')}</strong><small>{t('Use a one-time link sent to your email address.')}</small></span><button disabled={busy||!account.email||!auth.available} onClick={()=>{if(account.email)void run(async()=>{await auth.requestEmail(account.email!,'login');},'Check your email for a sign-in code or link.');}}>{t('Send sign-in link')}</button></div><div className="account-method-row"><span><strong>{t('Password (optional)')}</strong><small>{t('A password can be set or updated after your email has been verified.')}</small></span><button disabled={!account.verified||busy||!auth.available} onClick={()=>{setShowPasswordForm(value=>!value);setNotice('');}}>{t(showPasswordForm?'Cancel':'Set or update password')}</button></div>
  {showPasswordForm?<div className="account-password-form"><label className="field" htmlFor="new-account-password">{t('New password')}<input id="new-account-password" type="password" autoComplete="new-password" value={newPassword} onChange={event=>setNewPassword(event.target.value)}/><small>{t('Use at least eight characters.')}</small></label><button className="primary" disabled={busy||newPassword.length<8||!auth.available} onClick={()=>void run(async()=>{await auth.setPassword(newPassword);setShowPasswordForm(false);},'Password updated.')}>{busy?t('Saving...'):t('Save password')}</button></div>:null}</section>
  <button className="danger-outline" disabled={busy} onClick={()=>setConfirmSignOut(true)}>{t('Sign out')}</button>
 </>:account?.kind==='guest'?<>
  <p className="guest-account-intro">{t('Guest records are associated with this anonymous account. Linking an email may let you access them on another device; this has not been verified across hosted accounts.')}</p>
  {showGuestForm?<section className="guest-account-form"><button type="button" className="guest-account-back" disabled={busy} onClick={()=>{setShowGuestForm(false);setSent(false);setNotice('');}}><Icon name="chevron-left"/>{t('Back to guest options')}</button><h3>{t(mode==='link'?'Link email and keep my records':'Sign in to an existing account')}</h3>{mode==='login'?<label className="consent"><input type="checkbox" checked={switchAccepted} onChange={event=>setSwitchAccepted(event.target.checked)}/>{t('Signing in switches accounts. Guest medication records will not be merged.')}</label>:null}{signInForm}</section>:<div className="guest-account-actions"><article><span className="guest-account-icon"><Icon name="mail"/></span><div><h3>{t('Link email and keep my records')}</h3><p>{t('Add an email to this guest account. Existing records remain with the same account.')}</p></div><button aria-label={t('Link email and keep my records')} disabled={!auth.available||busy} onClick={()=>{setMode('link');setShowGuestForm(true);setSent(false);setNotice('');}}>{t('Link email')}</button></article><article><span className="guest-account-icon"><Icon name="user"/></span><div><h3>{t('Sign in to an existing account')}</h3><p>{t('Switch to another account. Guest records are not merged into it.')}</p></div><button aria-label={t('Sign in to an existing account')} disabled={!auth.available||busy} onClick={()=>{setMode('login');setShowGuestForm(true);setSent(false);setNotice('');setSwitchAccepted(false);}}>{t('Sign in')}</button></article></div>}
 </>:account?.kind==='local'?<p>{t('Email sign-in and account linking are unavailable in this local demo. No authenticated account is connected here.')}</p>:<><p>{t('Sign in to an existing account. No guest account is currently active to link.')}</p>{signInForm}</>}
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

 const content=accountLoading?<Card title="Account & security"><p role="status">{t('Loading account...')}</p></Card>:account===null?<Card title="Account & security"><p role="alert">{t('Could not load your account. Please retry.')}</p><button onClick={()=>{setAccountLoading(true);void auth.account().then(setAccount).catch(()=>setNotice('Could not load your account.')).finally(()=>setAccountLoading(false));}}>{t('Retry')}</button></Card>:account.kind==='guest'&&!standalone&&!embedded?<Screen title="Guest Mode" className="guest-account-screen">{body}</Screen>:account.kind==='member'?<Card title="Account & security">{body}</Card>:account.kind==='signed_out'?<Card title="Sign in to an existing account">{body}</Card>:account.kind==='local'?<Card title="Local demo">{body}</Card>:<Card title="Guest Mode">{body}</Card>;
 return <>{embedded?<div className="account-security-panel">{content}</div>:content}{confirmSignOut?<BottomSheet title={t('Sign out?')} busy={busy} onCancel={()=>setConfirmSignOut(false)}><p>{t('You will leave this account on this device. Its records are not merged into another account.')}</p><button disabled={busy} onClick={()=>setConfirmSignOut(false)}>{t('Cancel')}</button><button className="primary" disabled={busy} onClick={()=>void run(async()=>{await disableWebPush();await auth.signOut();onIdentityChanged();})}>{t('Sign out')}</button></BottomSheet>:null}</>;
}
