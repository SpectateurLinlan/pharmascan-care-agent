import {ConversationHistory} from './ConversationHistory';
import {accountDisplayName} from '../accountPresentation';
import {useImageConsent} from '../imageConsent';
import {api,type AgentUsage} from '../api/client';
import {Icon} from './Icon';
import {useEffect,useState} from 'react';
import {accountAuth,type Account,type AccountPort} from '../api/auth';
import {useLanguage} from '../language';
import {AutoDismissNotice,Card} from './primitives';
import {Row, RowGroup, Screen} from '../ui/primitives';
import {appVersionLabel} from '../appMetadata';

const noDirtyChange=()=>undefined;

export type MeDestination='profile'|'account'|'caregivers'|'reminder-settings'|'language-settings'|'accessibility'|'privacy'|'conversations'|'about'|'feedback';

/** Kept as the app-wide row entry point so every list reads the same way. */
export function Entry({title,hint,onClick}:{title:string;hint?:string;onClick:()=>void}){
  return <Row title={title} hint={hint} onClick={onClick}/>;
}

export function PatientHub({onOpen,onGuide,auth=accountAuth}:{onOpen:(page:MeDestination)=>void;onGuide?:()=>void;auth?:AccountPort}){
 const {t,preferences}=useLanguage();const [account,setAccount]=useState<Account|null>(null),[accountLoading,setAccountLoading]=useState(true),[accountFailed,setAccountFailed]=useState(false);
 useEffect(()=>{let live=true;const load=()=>void auth.account().then(row=>{if(live){setAccount(row);setAccountFailed(false);setAccountLoading(false);}}).catch(()=>{if(live){setAccount(null);setAccountFailed(true);setAccountLoading(false);}});load();window.addEventListener('focus',load);return()=>{live=false;window.removeEventListener('focus',load);};},[auth]);
 const member=account?.kind==='member';const guest=account?.kind==='guest';const local=account?.kind==='local';const fallback=guest?t('Guest Mode'):local?t('Local demo'):t('Your profile');const name=accountLoading?t('Loading account...'):accountFailed?t('Account unavailable'):accountDisplayName(account,preferences.display_name,fallback);
 return <Screen title="Me" lead="Your account, and how this app works for you." className="ui-screen--me">
  <section className="card identity-card">
   <button aria-label={t('Personal profile')} className="identity-entry" onClick={()=>onOpen('profile')}>
    <span className="avatar"><Icon name="user"/></span>
    <span><strong>{name}</strong><small>{member?`${account.email}${account.verified?` · ${t('Email verified')}`:''}`:guest?t('Guest Mode'):local?t('Email sign-in is unavailable in this local demo.'):accountFailed?t('Retry account status'):t('Personal profile')}</small></span>
    <Icon name="chevron-right"/>
   </button>
   {guest
    ? <div className="guest-link"><p>{t('Linking an email may keep access to records on other devices. Existing-account sign-in switches accounts; records are not merged.')}</p><button className="primary" onClick={()=>onOpen('account')}>{t('Manage guest account')}</button></div>
    : null}
  </section>
  <RowGroup title="Care and reminders" className="me-category">
   <Row icon="user" title="Care contacts" onClick={()=>onOpen('caregivers')}/>
   <Row icon="bell" title="Reminders & Notifications" onClick={()=>onOpen('reminder-settings')}/>
  </RowGroup>
  <RowGroup title="Personalisation" className="me-category">
   <Row icon="languages" title="Language & Voice" onClick={()=>onOpen('language-settings')}/>
   <Row icon="info" title="Text size" onClick={()=>onOpen('accessibility')}/>
  </RowGroup>
  <RowGroup title="Privacy & Data" className="me-category me-category--privacy">
   <Row icon="message" title="AI Assistant & Chat History" onClick={()=>onOpen('conversations')}/>
   <Row icon="shield" title="Privacy Settings" onClick={()=>onOpen('privacy')}/>
  </RowGroup>
  <RowGroup title="Help & application information" className="me-app-info" spread>
   {onGuide?<Row icon="info" title="Help / User Guide" onClick={onGuide}/>:null}
   <Row icon="file" title="About MediThread" onClick={()=>onOpen('about')}/>
   <Row icon="message" title="Feedback & Suggestions" onClick={()=>onOpen('feedback')}/>
  </RowGroup>
 </Screen>;
}

export function ProfileScreen({onDirtyChange=noDirtyChange}:{onDirtyChange?:(dirty:boolean)=>void}){
 const {t,preferences,savePreferences}=useLanguage();const savedName=preferences.display_name??'';
 const [name,setName]=useState(savedName),[busy,setBusy]=useState(false),[error,setError]=useState(false),[saved,setSaved]=useState(false);
 useEffect(()=>setName(savedName),[savedName]);
 const dirty=name.trim()!==savedName.trim();useEffect(()=>{onDirtyChange(dirty);return()=>onDirtyChange(false);},[dirty,onDirtyChange]);
 async function save(){if(!dirty||!name.trim()||busy)return;setBusy(true);setError(false);setSaved(false);try{const ok=await savePreferences({display_name:name.trim()});if(ok){setName(name.trim());setSaved(true);}else setError(true);}catch{setError(true);}finally{setBusy(false);}}
 return <Card title="Personal profile"><label className="field">{t('Display name')}<input maxLength={80} value={name} onChange={event=>{setName(event.target.value);setError(false);setSaved(false);}}/></label><p>{t('Choose the name you would like us to use.')}</p>{error?<p role="alert">{t('Could not save profile. Your changes are still here.')}</p>:null}<div className="actions"><button disabled={!dirty||busy} onClick={()=>{setName(savedName);setError(false);setSaved(false);}}>{t('Cancel')}</button><button className="primary" disabled={!dirty||!name.trim()||busy} onClick={()=>void save()}>{busy?t('Saving...'):t('Save profile')}</button></div>{saved?<AutoDismissNotice>{t('Profile saved.')}</AutoDismissNotice>:null}</Card>;
}

export function InformationScreen({kind,onPrivacy,onFeedback,onConversationCleared,ownerId=''}:{onConversationCleared?:()=>void;ownerId?:string;kind:'privacy'|'conversations'|'about';onPrivacy?:()=>void;onFeedback?:()=>void;onHistory?:()=>void}){
 const {t,language}=useLanguage();const [photoConsent,setPhotoConsent]=useImageConsent(ownerId);const [usage,setUsage]=useState<AgentUsage|null>(null),[usageFailed,setUsageFailed]=useState(false);
 useEffect(()=>{if(kind!=='about')return;let live=true;void api.agentUsage().then(value=>{if(live){setUsage(value);setUsageFailed(false);}}).catch(()=>{if(live){setUsage(null);setUsageFailed(true);}});return()=>{live=false;};},[kind]);
 if(kind==='about'){
  const resetAt=usage?.next_reset_at&&Number.isFinite(Date.parse(usage.next_reset_at))?new Intl.DateTimeFormat(language==='zh'?'zh-CN':'en-SG',{dateStyle:'medium',timeStyle:'short',timeZone:'Asia/Singapore'}).format(new Date(usage.next_reset_at)):null;
  const features=[
   ['pill','Medication & regimen management','Review medication details, current plans and previous plan versions.'],
   ['image','Medication evidence & photo review','Read medication labels and compare eligible photos with available references. A photo alone does not confirm identity.'],
   ['bell','Reminders & care tasks','Set medication reminder preferences and manage medication-related follow-ups.'],
   ['clipboard','Adherence & health records','Record your dose reports and health notes, then review them over time.'],
   ['message','AI assistant','Ask questions about medicines and your saved records. Review answers against your own instructions.'],
   ['calendar','Healthcare visit preparation','Create a medication and health summary to review, copy, print or export before a visit.'],
  ] as const;
  const steps=['Add and review medication information','Manage daily medicines and record what happened','Review history and prepare for a visit'] as const;
  return <article className="about-page" aria-labelledby="about-title">
   <header className="about-hero"><img src="/branding/medithread-mark.svg" alt=""/><div><h1 id="about-title">{t('About MediThread')}</h1><p className="about-tagline">{t('Make everyday medication management clearer and easier to follow.')}</p></div></header>
   <p className="about-lead">{t('MediThread brings medication plans, reminders and your own health notes together to support everyday medication management and visit preparation.')}</p>
   <section className="about-section" aria-labelledby="about-capabilities"><h2 id="about-capabilities">{t('What you can do')}</h2><div className="about-features">{features.map(([icon,title,description])=><article className="about-feature" key={title}><Icon name={icon}/><div><h3>{t(title)}</h3><p>{t(description)}</p></div></article>)}</div></section>
   <section className="about-section" aria-labelledby="about-workflow"><h2 id="about-workflow">{t('How MediThread fits your day')}</h2><ol className="about-workflow">{steps.map((title,index)=><li key={title}><span aria-hidden="true">{index+1}</span><div><h3>{t(title)}</h3><p>{t(index===0?'Check medication details against the source information you provide, then review the plan before using it.':index===1?'Use reminders as prompts and record your own dose reports and health notes.':'Bring together medication plans, reports and health notes in an exportable summary.')}</p></div></li>)}</ol></section>
   <section className="about-trust" aria-labelledby="about-trust-title"><div className="about-trust__heading"><Icon name="shield"/><h2 id="about-trust-title">{t('Trust & responsible AI')}</h2></div><div className="about-trust__grid"><div><h3>{t('You confirm medication information')}</h3><p>{t('Extracted or entered details remain for your review. Follow the instructions from your healthcare professional and medicine label.')}</p></div><div><h3>{t('Sources when available')}</h3><p>{t('Some assistant answers include links to their supporting information. Review the source and its scope before relying on it.')}</p></div><div><h3>{t('AI supports review, not medication decisions')}</h3><p>{t('AI responses may help explain available information. They do not replace confirmed instructions and do not change prescriptions or doses.')}</p></div><div><h3>{t('Your reports are self-reported')}</h3><p>{t('A dose report records what you tell MediThread; it does not prove that a dose was taken. MediThread is not a substitute for clinical judgement.')}</p></div></div></section>
   <section className="about-section" aria-labelledby="about-roadmap"><h2 id="about-roadmap">{t('Future work')}</h2><div className="about-roadmap"><article><span className="about-status">{t('Planned')}</span><div><h3>{t('Prescription PDF understanding')}</h3><p>{t('Future work may add OCR and structured extraction of medication and instruction details, followed by your review. Current PDF storage does not read or verify prescriptions.')}</p></div></article><article><span className="about-status about-status--exploring">{t('Exploring')}</span><div><h3>{t('More languages & caregiver support')}</h3><p>{t('Additional interface languages and consent-based caregiver support are being explored; they are not presented as available features.')}</p></div></article></div></section>
   <section className="about-section about-product" aria-labelledby="about-product-title"><h2 id="about-product-title">{t('Product & service information')}</h2><dl>
    <div><dt>{t('AI assistant allowance')}</dt><dd>{usage?`${t('Daily limit:')} ${usage.limit} ${t('conversations per day. Next reset')} ${resetAt?`${resetAt} (${t('Singapore time')})`:t('Reset time is unavailable.')}`:t(usageFailed?'Usage details are temporarily unavailable.':'Loading…')}</dd></div>
    <div><dt>{t('Interface & voice')}</dt><dd>{t('Interface languages: English and Simplified Chinese. Voice input and playback depend on your browser, device and settings.')}</dd></div>
    <div><dt>{t('Privacy & your records')}</dt><dd>{t('Your records are private to your account. Photo processing requires your choice; conversation saving is optional.')}</dd></div>
    <div><dt>{t('Version')}</dt><dd>{appVersionLabel}</dd></div>
   </dl><div className="about-links">{onPrivacy?<button type="button" onClick={onPrivacy}>{t('Privacy controls')} <Icon name="chevron-right"/></button>:null}{onFeedback?<button type="button" onClick={onFeedback}>{t('Send feedback')} <Icon name="chevron-right"/></button>:null}</div></section>
  </article>;
 }
 return <Screen title={kind==='privacy'?'Privacy Settings':'AI Assistant & Chat History'} className="me-child-screen"><Card>{kind==='privacy'?<><label className="consent image-consent"><input type="checkbox" checked={photoConsent} onChange={event=>setPhotoConsent(event.target.checked)}/>{t('Allow medication photo processing')}</label><p>{t('This preference is saved in this browser for this account. When you choose recognition, the image is sent to the recognition service. It does not control photos you separately choose to save.')}</p><p>{t('Saved evidence is private to this account. This page does not provide full data export or account deletion.')}</p></>:<><p>{t('Recent conversation context is separate from saved history. Turning saving off affects new conversations; it does not delete earlier saved messages.')}</p><ConversationHistory onCleared={()=>onConversationCleared?.()}/><p>{t('Raw audio is not saved. Browser speech may use an online service.')}</p></>}</Card></Screen>;
}
