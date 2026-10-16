import {api,type AgentUsage} from '../api/client';
import {Icon} from './Icon';
import {useEffect,useState} from 'react';
import {accountAuth} from '../api/auth';
import {useLanguage} from '../language';
import {Card} from './primitives';
import {Row, RowGroup, Screen} from '../ui/primitives';

export type MeDestination='profile'|'account'|'caregivers'|'reminder-settings'|'language-settings'|'accessibility'|'privacy'|'about'|'feedback';

/** Kept as the app-wide row entry point so every list reads the same way. */
export function Entry({title,hint,onClick}:{title:string;hint?:string;onClick:()=>void}){
  return <Row title={title} hint={hint} onClick={onClick}/>;
}

export function PatientHub({onOpen,onGuide}:{onOpen:(page:MeDestination)=>void;onGuide?:()=>void}){
 const {t,preferences}=useLanguage();const [member,setMember]=useState(false);
 useEffect(()=>{let live=true;void accountAuth.account().then(row=>{if(live)setMember(row.kind==='member');}).catch(()=>{if(live)setMember(false);});return()=>{live=false;};},[]);
 const name=member&&preferences.display_name?.trim()?preferences.display_name:t('Guest');
 return <Screen title="Me" lead="Your account, and how this app works for you.">
  <section className="card identity-card">
   <button aria-label={t('Personal profile')} className="identity-entry" onClick={()=>onOpen('profile')}>
    <span className="avatar"><Icon name="user"/></span>
    <span><strong>{name}</strong><small>{t(member?'Your account':'Guest demo')}</small></span>
    <Icon name="chevron-right"/>
   </button>
   {!member
    ? <div className="guest-link"><p>{t('Link your guest account to restore your records on another device.')}</p><button className="primary" onClick={()=>onOpen('account')}>{t('Login or register')}</button></div>
    : <Row title="Account and login" hint="Email and sign-in options" onClick={()=>onOpen('account')}/>}
  </section>
  <RowGroup>
   <Row icon="user" title="Caregiver contacts" hint="Private contact details" onClick={()=>onOpen('caregivers')}/>
   <Row icon="bell" title="Medication reminders" hint="In-app prompts and notifications" onClick={()=>onOpen('reminder-settings')}/>
  </RowGroup>
  <RowGroup>
   <Row icon="languages" title="Language and speech" hint="English / 中文" onClick={()=>onOpen('language-settings')}/>
   <Row icon="settings" title="Accessibility" hint="Text size and touch controls" onClick={()=>onOpen('accessibility')}/>
   <Row icon="shield" title="Privacy and data" hint="Your records and conversation privacy" onClick={()=>onOpen('privacy')}/>
  </RowGroup>
  {/* A menu of equal destinations, so it takes the full width and spreads. */}
  <RowGroup spread>
   {onGuide?<Row icon="info" title="Help / User Guide" onClick={onGuide}/>:null}
   <Row icon="file" title="About MediThread" onClick={()=>onOpen('about')}/>
   <Row icon="message" title="Feedback" onClick={()=>onOpen('feedback')}/>
  </RowGroup>
 </Screen>;
}

export function ProfileScreen(){const {t,preferences,updatePreferences}=useLanguage();const [name,setName]=useState(preferences.display_name??'');return <Card title="Personal profile"><label className="field">{t('Display name')}<input maxLength={80} value={name} onChange={event=>setName(event.target.value)}/></label><button className="primary" disabled={!name.trim()} onClick={()=>updatePreferences({display_name:name.trim()})}>{t('Save profile')}</button><p>{t('Use a display name only. No identity document is needed for this demo.')}</p></Card>;}

export function InformationScreen({kind,onHistory,onPrivacy}:{kind:'privacy'|'about';onHistory:()=>void;onPrivacy?:()=>void}){
 const {t}=useLanguage();const [usage,setUsage]=useState<AgentUsage|null>(null);
 useEffect(()=>{if(kind!=='about')return;let live=true;void api.agentUsage().then(value=>{if(live)setUsage(value);}).catch(()=>{if(live)setUsage(null);});return()=>{live=false;};},[kind]);
 return <Card title={kind==='privacy'?'Privacy and data':'About MediThread'}>{kind==='privacy'?<><p>{t('Your records are private to your account. You choose what to export or share.')}</p><p>{t('The assistant uses six recent turns for context. Optional history shows up to 200 conversations from the last 30 days; older stored text is not deleted on a timer. Use Clear saved conversations to remove chat text. Health records remain separate.')}</p><p>{t('Raw audio is not saved. Browser speech may use an online service.')}</p><button onClick={onHistory}>{t('View and export my summary')}</button></>:<>
 <p className="about-intro">{t('Your medication and self-care companion')}</p><p>{t('MediThread brings your medication plans, reminders and your own reports together, so you can prepare for everyday care and professional reviews.')}</p>
 <h3>{t('What you can do')}</h3><p>{t('Add and review medication information, check a photo against available references, keep track of supply, note how you feel and prepare a medication summary.')}</p>
 <h3>{t('Speak in English or Chinese')}</h3><p>{t('Ask by voice or text, edit your words and listen to replies. Voice availability depends on your browser and device.')}</p>
 <h3>{t('Your free AI demo allowance')}</h3><p>{usage?`${t('Daily AI conversations')}: ${usage.limit}. `:''}{t('The demo has a daily allowance to share free AI capacity fairly. It resets at midnight Singapore time. Your medication records and basic reminders remain available when AI usage runs out.')}</p>
 <h3>{t('AI helps you review')}</h3><p>{t('Check your original instructions before you confirm. This prototype is not clinically validated and does not replace your doctor or pharmacist.')}</p>
 <h3>{t('Looking ahead')}</h3><p>{t('More languages, authorised caregiver notifications and native mobile reminders are future directions.')}</p>{onPrivacy?<button onClick={onPrivacy}>{t('Privacy and data')}</button>:null}</>}</Card>;
}
